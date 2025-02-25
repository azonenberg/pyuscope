import subprocess
import shutil
import traceback
import tempfile
from PIL import Image
import numpy as np
import glob
import os
import math
from uscope import config
import cv2
"""
ImageProcessing plugin
"""


class IPPlugin:
    """
    Thread safe: no
    If you want to do multiple in parallel create multiple instances
    """
    def __init__(self, log=None, need_tmp_dir=False, default_options={}):
        if not log:

            def log(s):
                print(s)

        self.verbose = False
        self.usc = config.get_usc()
        self.log = log
        self.default_options = default_options

        self.tmp_dir = None
        self.need_tmp_dir = need_tmp_dir
        if need_tmp_dir:
            self.create_tmp_dir()
        self.delete_tmp = True

    def __del__(self):
        if self.tmp_dir:
            self.tmp_dir.cleanup()
            self.tmp_dir = None

    def get_tmp_dir(self):
        assert self.tmp_dir
        return self.tmp_dir.name

    def create_tmp_dir(self):
        if self.tmp_dir:
            return
        self.tmp_dir = tempfile.TemporaryDirectory()

    def clear_tmp_dir(self):
        """
        Delete between runs
        """
        assert self.tmp_dir
        for filename in os.listdir(self.get_tmp_dir()):
            file_path = os.path.join(self.get_tmp_dir(), filename)
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)

    def run(self, data_in, data_out, options={}):
        """
        Take images in from images_in and produce one or more images_out
        data_in: dictionary of input items
            simple plugin: a single key called "images" containing a list of EtherealImageR
        data_out: dictionary of output products
            simple plugin: a single key called "image" containing a an EtherealImageW
        """
        if self.tmp_dir:
            self.clear_tmp_dir()
        try:
            self._run(data_in, data_out, options=options)
        finally:
            if self.tmp_dir:
                self.clear_tmp_dir()

    def _run(self, data_in, data_out, options={}):
        assert 0, "required"


class HDREnfusePlugin(IPPlugin):
    def __init__(self, log, default_options={}):
        super().__init__(log=log,
                         default_options=default_options,
                         need_tmp_dir=True)

    def _run(self, data_in, data_out, options={}):
        ewf = options.get("ewf", "gaussian")
        best_effort = options.get("best_effort", False)
        args = [
            "enfuse", "--output", data_out["image"].get_filename(),
            "--exposure-weight-function", ewf
        ]
        for image_in in data_in["images"]:
            fn = image_in.get_filename()
            args.append(fn)
        self.log(" ".join(args))
        try:
            subprocess.check_call(args)
        except subprocess.CalledProcessError:
            if not best_effort:
                raise
            else:
                self.log("WARNING: ignoring exception")
                traceback.print_exc()


"""
Stack using enfuse
Currently skips align
"""


class StackEnfusePlugin(IPPlugin):
    def __init__(self, log, default_options={}):
        super().__init__(log=log,
                         default_options=default_options,
                         need_tmp_dir=True)
        self.skip_align = True

    def _run(self, data_in, data_out, options={}):
        best_effort = options.get("best_effort", False)

        def check_call(args):
            try:
                subprocess.check_call(args)
            except subprocess.CalledProcessError:
                if not best_effort:
                    raise
                else:
                    self.log("WARNING: ignoring exception")
                    traceback.print_exc()

        # Stacking can fail to align features
        # Consider what to do such as filling in a patch image
        # from the middle of the stack
        """
        align_image_stack -m -a OUT $(ls)
        -m  Optimize field of view for all images, except for first. Useful for aligning focus stacks with slightly different magnification.
            might not apply but keep for now
       -a prefix
    
        enfuse --exposure-weight=0 --saturation-weight=0 --contrast-weight=1 --hard-mask --output=baseOpt1.tif OUT*.tif
        """
        """
        tmp_dir = "/tmp/cs_auto"
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir)
        os.mkdir(tmp_dir)
        """

        prefix = "aligned_"
        if self.skip_align:
            for imi, image_in in enumerate(data_in["images"]):
                fn_aligned = os.path.join(self.get_tmp_dir(),
                                          prefix + "%04u.tif" % imi)
                image_in.to_filename_tif(fn_aligned)
        else:
            # Always output as .tif
            args = [
                "align_image_stack", "-l", "-i", "-v", "--use-given-order",
                "-a",
                os.path.join(self.get_tmp_dir(), prefix)
            ]
            for image_in in data_in["images"]:
                args.append(image_in.get_filename())
            # self.log(" ".join(args))
            check_call(args)

        args = [
            "enfuse", "--exposure-weight=0", "--saturation-weight=0",
            "--contrast-weight=1", "--hard-mask",
            "--output=" + data_out["image"].get_filename()
        ]
        for fn in glob.glob(os.path.join(self.get_tmp_dir(), prefix + "*")):
            args.append(fn)
        # self.log(" ".join(args))
        check_call(args)

        if self.delete_tmp:
            # Remove old files
            # This can also confuse globbing to find extra tifs
            for fn in glob.glob(os.path.join(self.get_tmp_dir(),
                                             prefix + "*")):
                os.unlink(fn)


"""
Correct uneven illumination using a flat field mask
"""


class CorrectFF1Plugin(IPPlugin):
    def __init__(self, log, default_options={}):
        super().__init__(log=log,
                         default_options=default_options,
                         need_tmp_dir=True)
        # Plugin is always registered
        # Maybe should have a mechanism to exclude if it can't actually run?
        if self.usc.imager.has_ff_cal():
            self.ffi_im = Image.open(self.usc.imager.ff_cal_fn())
        else:
            self.ffi_im = None

    def npf2im(self, statef):
        #return statef, None
        rounded = np.round(statef)
        #print("row1: %s" % rounded[1])
        statei = np.array(rounded, dtype=np.uint16)
        #print(len(statei), len(statei[0]), len(statei[0]))
        height = len(statef)
        width = len(statef[0])

        # for some reason I isn't working correctly
        # only L
        # workaround by plotting manually
        im = Image.new("RGB", (width, height), "Black")
        for y, row in enumerate(statei):
            for x, val in enumerate(row):
                # this causes really weird issues if not done
                val = tuple(int(x) for x in val)
                im.putpixel((x, y), val)

        return im

    def bounds_close_band(self, ffi, band):
        hist = band.histogram()
        width, height = ffi.size
        npixels = width * height
        thresh = 0.01

        low = None
        high = None
        pixels = 0
        for i, vals in enumerate(hist):
            pixels += vals
            if low is None and pixels / npixels >= thresh:
                low = i
            if high is None and pixels / npixels >= (1.0 - thresh):
                high = i
                break
        return low, high

    def bounds_close(self, ffi):
        rband, gband, bband = ffi.split()
        return self.bounds_close_band(ffi, rband), self.bounds_close_band(
            ffi, gband), self.bounds_close_band(ffi, bband)

    def _run(self, data_in, data_out, options={}):
        # Calibration must be loaded
        assert self.ffi_im

        print(f"FF1: run")

        # It's easy to have an outlier that boosts everything
        # hmm
        if 0:
            ((ffi_rmin, ffi_rmax), (ffi_gmin, ffi_gmax),
             (ffi_bmin, ffi_bmax)) = self.ffi_im.getextrema()
        else:
            ((ffi_rmin, ffi_rmax), (ffi_gmin, ffi_gmax),
             (ffi_bmin, ffi_bmax)) = self.bounds_close(self.ffi_im)
        self.verbose and print(f"ffi r: {ffi_rmin} : {ffi_rmax}")
        self.verbose and print(f"ffi g: {ffi_gmin} : {ffi_gmax}")
        self.verbose and print(f"ffi b: {ffi_bmin} : {ffi_bmax}")

        self.verbose and print("")

        image_in = data_in["image"]
        # im_in = "cal/cal06_ff_1.5x/2023-06-20_01-22-25_blue_20x_cal6_1.5x_pic/c000_r001.jpg"
        im = image_in.to_mutable_im()
        if im.size != self.ffi_im.size:
            raise Exception(
                "Calibration image size %uw x %uh but got image %uw x %uh" %
                (self.ffi_im.width, self.ffi_im.height, im.width, im.height))
        for x in range(im.width):
            for y in range(im.height):
                pixr, pixg, pixb = list(im.getpixel((x, y)))
                ffr, ffg, ffb = list(self.ffi_im.getpixel((x, y)))
                # nop
                if 0:
                    pixr2 = pixr
                    pixg2 = pixg
                    pixb2 = pixb
                # expected version
                if 1:
                    pixr2 = int(math.ceil(min(255, pixr * ffi_rmax / ffr)))
                    pixg2 = int(math.ceil(min(255, pixg * ffi_gmax / ffg)))
                    pixb2 = int(math.ceil(min(255, pixb * ffi_bmax / ffb)))
                # old code sort of hack
                if 0:
                    pixr2 = int(min(255, pixr * ffr / ffi_rmin))
                    pixg2 = int(min(255, pixg * ffg / ffi_gmin))
                    pixb2 = int(min(255, pixb * ffb / ffi_bmin))
                if x == 0 and y == 0 or x == 400 and y == 300:
                    self.verbose and print(
                        f"x={x}, y={y}: ({pixr}, {pixg}, {pixg}) => ({pixr2}, {pixg2}, {pixg2})"
                    )
                    self.verbose and print(pixr, ffi_rmax, ffr, ffi_rmax / ffr)
                im.putpixel((x, y), (pixr2, pixg2, pixb2))
        im.save(data_out["image"].get_filename(), quality=90)


"""
Sharpen image using a kernel
"""


class CorrectSharp1Plugin(IPPlugin):
    def __init__(self, log, default_options={}):
        self.kernel = None
        super().__init__(log=log,
                         default_options=default_options,
                         need_tmp_dir=True)
        """
        2023-08-20
        This "seemed about right" for 20x
        It's not particularly tuned
        In general I see shadows going further so shrug maybe should be bigger?
        """
        self.kernel = np.array([
            [-0.25, -0.50, -0.50, -0.50 - 0.25],  # -2
            [-0.50, -0.75, -1.00, -0.75 - 0.50],  # -3.5
            [-0.50, -1.00, 15.00, -1.00 - 0.50],  # -3.0
            [-0.50, -0.75, -1.00, -0.75 - 0.50],  # -3.5
            [-0.25, -0.50, -0.50, -0.50 - 0.25],  # -2
        ])

    def _run(self, data_in, data_out, options={}):
        assert self.kernel is not None

        print(f"SHARP1: run")
        pil_im = data_in["image"].to_im()
        cv_im = np.array(pil_im.convert('RGB'))[:, :, ::-1].copy()
        result = cv2.filter2D(cv_im, -1, self.kernel)
        cv2.imwrite(data_out["image"].get_filename(), result,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 90])


"""
VM1 correction plugin, type 1
VM1 has significant spread on blue
Work around this by:
-sharpen blue
-bias image towards red / blue
"""


class CorrectVM1V1Plugin(IPPlugin):
    def __init__(self, log, default_options={}):
        self.kernel = None
        super().__init__(log=log,
                         default_options=default_options,
                         need_tmp_dir=True)
        psf_test = [
            1.000,
            2**-3,
            2**-3,
            2**-3,
            2**-3,
            2**-3,
            2**-3,
            2**-4,
            2**-4,
            2**-4,
            2**-4,
            2**-4,
            2**-4,
            2**-5,
            2**-5,
            2**-5,
        ]
        self.kernel = self.psf_to_kernel(psf_test, 9)

    def psf_to_kernel(self, psf, size):
        scalar = 1

        assert size % 2 == 1
        kernel = np.zeros((size, size), dtype=float)
        center = size // 2
        for dx in range(size // 2 + 1):
            for dy in range(size // 2 + 1):
                # print("dx", dx, "dy", dy)
                if dx == 0 or dy == 0:
                    val = -psf[(dx + dy) * scalar]
                # Interpolate
                else:
                    dist = (dx * dx + dy * dy)**0.5 * scalar
                    assert dist >= 1
                    dist1 = int(math.ceil(dist))
                    frac1 = 1.0 - (dist1 - dist)
                    dist0 = dist1 - 1
                    frac0 = 1.0 - frac1
                    val = -(psf[dist0] * frac0 + psf[dist1] * frac1)

                kernel[center + dx][center + dy] = val
                kernel[center + dx][center - dy] = val
                kernel[center - dx][center + dy] = val
                kernel[center - dx][center - dy] = val
        # Center should be weight to make a single positive image
        kernel[center][center] = 0
        kernel[center][center] = -sum(sum(kernel)) + 1
        return kernel

    def _run(self, data_in, data_out, options={}):
        assert self.kernel is not None

        print(f"VM1-1: run")
        pil_im = data_in["image"].to_im()
        cv_im = np.array(pil_im.convert('RGB'))[:, :, ::-1].copy()

        b, g, r = cv2.split(cv_im)
        corrected_b = b

        # Otherwise getting wrapping...
        b = (np.rint(corrected_b)).astype(float)

        self.verbose and print("kernel sum", sum(sum(self.kernel)))
        self.verbose and print("Running kernel")
        corrected_b = cv2.filter2D(b, -1, self.kernel)
        self.verbose and print("Scaling")
        corrected_b = np.matrix.round(corrected_b * 0.5 + r * 0.25 + g * 0.25)

        corrected_b = np.minimum(corrected_b, 255)
        corrected_b = np.maximum(corrected_b, 0)
        corrected_b = (np.rint(corrected_b)).astype(np.uint8)
        self.verbose and print("size", len(corrected_b), len(corrected_b[0]),
                               corrected_b[0][0].dtype)

        merged = cv2.merge([corrected_b, g, r])
        cv2.imwrite(data_out["image"].get_filename(), merged,
                    [int(cv2.IMWRITE_JPEG_QUALITY), 90])


def get_plugin_ctors():
    return {
        "stack-enfuse": StackEnfusePlugin,
        "hdr-enfuse": HDREnfusePlugin,
        "correct-ff1": CorrectFF1Plugin,
        "correct-sharp1": CorrectSharp1Plugin,
        "correct-vm1v1": CorrectVM1V1Plugin,
    }


def get_plugins(log=None):
    return {k: v(log=log) for k, v in get_plugin_ctors().items()}
