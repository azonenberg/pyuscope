#!/usr/bin/env python3
from PIL import Image
import numpy as np
import glob
import os


def npf2im(statef):
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


def average_imgs(imgs, scalar=None):
    width, height = imgs[0].size
    if not scalar:
        scalar = 1.0
    scalar = scalar / len(imgs)

    statef = np.zeros((height, width, 3), np.float)
    for im in imgs:
        assert (width, height) == im.size
        statef = statef + scalar * np.array(im, dtype=np.float)

    return statef, npf2im(statef)


def average_dir(din, images=0, verbose=1, scalar=None):
    imgs = []

    files = list(glob.glob(os.path.join(din, "*.jpg")))
    verbose and print('Reading %s w/ %u images' % (din, len(files)))

    for fni, fn in enumerate(files):
        imgs.append(Image.open(fn))
        if images and fni + 1 >= images:
            verbose and print("WARNING: only using first %u images" % images)
            break
    return average_imgs(imgs, scalar=scalar)


"""
def histeq_np_create(npim, nbr_bins=256, verbose=0):
    '''
    Given a numpy nD array (ie image), return a histogram equalized numpy nD array of pixels
    That is, return 2D if given 2D, or 1D if 1D
    '''

    # get image histogram
    flat = npim.flatten()
    verbose and print('flat', flat)
    imhist, bins = np.histogram(flat, nbr_bins)
    verbose and print('imhist', imhist)
    verbose and print('imhist', bins)
    cdf = imhist.cumsum()  #cumulative distribution function
    verbose and print('cdfraw', cdf)
    cdf = 0xFFFF * cdf / cdf[-1]  #normalize
    verbose and print('cdfnorm', cdf)
    return cdf, bins


def histeq_np_apply(npim, create):
    cdf, bins = create

    # use linear interpolation of cdf to find new pixel values
    ret1d = np.interp(npim.flatten(), bins[:-1], cdf)
    return ret1d.reshape(npim.shape)

def histeq_np(npim, nbr_bins=256):
    '''
    Given a numpy nD array (ie image), return a histogram equalized numpy nD array of pixels
    That is, return 2D if given 2D, or 1D if 1D
    '''
    return histeq_np_apply(npim, histeq_np_create(npim, nbr_bins=nbr_bins))

def histeq_im(im, nbr_bins=256):
    imnp2 = np.array(im)
    imnp2_eq = histeq_np(imnp2, nbr_bins=nbr_bins)
    imf = Image.fromarray(imnp2_eq)
    return imf.convert("RGB")
"""


def bounds10(ffi, band):
    hist = band.histogram()
    width, height = ffi.size
    npixels = width * height

    low = None
    high = None
    pixels = 0
    for i, vals in enumerate(hist):
        pixels += vals
        if low is None and pixels / npixels >= 0.1:
            low = i
        if high is None and pixels / npixels >= 0.9:
            high = i
            break
    return low, high


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate calibreation files from specially captured frames'
    )
    parser.add_argument('--images',
                        type=int,
                        default=0,
                        help='Only take first n images, for debugging')
    parser.add_argument('--dir-in', help='Sample images')
    parser.add_argument('--dir-out', help='Sample images')
    args = parser.parse_args()

    dir_out = args.dir_out
    if not dir_out:
        dir_out = args.dir_in + "/cal"
    if not os.path.exists(dir_out):
        os.mkdir(dir_out)

    _fff, ffi = average_dir(args.dir_in, images=args.images)
    ffi.save(dir_out + '/ff.tif')
    # histeq_im(ffi).save(dir_out + '/ffe.tif')

    ((ffi_rmin, ffi_rmax), (ffi_gmin, ffi_gmax),
     (ffi_bmin, ffi_bmax)) = ffi.getextrema()
    print(f"ffi r: {ffi_rmin} : {ffi_rmax}")
    print(f"ffi g: {ffi_gmin} : {ffi_gmax}")
    print(f"ffi b: {ffi_bmin} : {ffi_bmax}")

    pixmin = (ffi_rmin + ffi_gmin + ffi_bmin) / 3
    pixmax = (ffi_rmax + ffi_gmax + ffi_bmax) / 3
    print("Percent ratio: %0.2f" % (pixmax / pixmin * 100.0))

    rband, gband, bband = ffi.split()
    rlo, rhi = bounds10(ffi, rband)
    glo, ghi = bounds10(ffi, gband)
    blo, bhi = bounds10(ffi, bband)
    print("10% lo/hi")
    print("  R: %u : %u => %0.2f" % (rlo, rhi, rhi / rlo * 100.0))
    print("  G: %u : %u => %0.2f" % (glo, ghi, ghi / glo * 100.0))
    print("  B: %u : %u => %0.2f" % (blo, bhi, bhi / blo * 100.0))


if __name__ == "__main__":
    main()
