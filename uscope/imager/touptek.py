import re
import subprocess
from uscope.util import tostr


class CameraNotFound(Exception):
    pass


def toupcamsrc_info():
    """
    Requires plugin 0.3.1+

    https://github.com/Labsmore/pyuscope/issues/82
    $ GST_TOUPCAMSRC_INFO=Y gst-launch-1.0 toupcamsrc
    ...
    Camera info
      MaxBitDepth(): 12
      FanMaxSpeed(): -2147467263
      MaxSpeed(): 2
      MonoMode(): 1
      StillResolutionNumber(): 3
        eSize=0
              StillResolution(): 4928w x 4928h
              PixelSize(): 1.1w x 1.1h um
        eSize=1
              StillResolution(): 2464w x 2464h
              PixelSize(): 2.2w x 2.2h um
        eSize=2
              StillResolution(): 1648w x 1648h
              PixelSize(): 3.4w x 3.4h um
      Negative(): 0
      Chrome(): 0
      HZ(): 2
      RealTime(): 0
      Revision(): 2
      SerialNumber(): TP2210101618037715CAC72D6E44CF4
      FwVersion(): 3.6.5.20220711
      HwVersion(): 3.0
      ProductionDate(): 20221010
      FpgaVersion(): 1.1
      Option(PIXEL_FORMAT): 0
        RawFormat(): FourCC RGGB, BitsPerPixel 8
        """
    # 750 ms
    # But we really only need the init info
    # Where is the time spent?
    # Wonder if there is a quick way to speed this up
    buf = tostr(
        subprocess.check_output(
            "GST_TOUPCAMSRC_INFO=Y gst-launch-1.0 toupcamsrc num-buffers=0 ! fakesink",
            shell=True))
    # buf = subprocess.check_output("gst-launch-1.0 toupcamsrc", shell=True)

    if "No ToupCam devices found" in buf:
        raise CameraNotFound()

    lines = buf.split("\n")

    def pop_line():
        ret = lines[0]
        # print("l", ret)
        del lines[0]
        return ret

    while True:
        if pop_line().find("Camera info") >= 0:
            break
    ret = {}

    def func_str(func, store=True):
        l = pop_line()
        m = re.match(r"[ ]+%s\(.*\): (.+)" % func, l)
        if not m:
            raise ValueError(l)
        s = m.group(1)
        if store:
            ret[func] = s
        return s

    def func_i(func, positive=True, store=True):
        i = int(func_str(func, store=False))
        if positive and i < 0:
            i = None
        if store:
            ret[func] = i
        return i

    def func_wh(func, t=int):
        l = func_str(func, store=False)
        m = re.match(r"(.+)w x (.+)h", l)
        if not m:
            raise ValueError(l)
        w = t(m.group(1))
        h = t(m.group(2))
        return w, h

    func_i("MaxBitDepth")
    func_i("FanMaxSpeed")
    func_i("MaxSpeed")
    func_i("MonoMode")
    """
      StillResolutionNumber(): 3
        eSize=0
              StillResolution(): 4928w x 4928h
              PixelSize(): 1.1w x 1.1h um
        eSize=1
              StillResolution(): 2464w x 2464h
              PixelSize(): 2.2w x 2.2h um
        eSize=2
              StillResolution(): 1648w x 1648h
              PixelSize(): 3.4w x 3.4h um
    """
    func_i("StillResolutionNumber")
    eSizes = {}
    for eSize in range(ret["StillResolutionNumber"]):
        pop_line()
        sw, sh = func_wh("StillResolution", t=int)
        pw, ph = func_wh("PixelSize", t=float)
        je = {
            "StillResolution": {
                "w": sw,
                "h": sh
            },
            "PixelSize": {
                "w": pw,
                "h": ph
            },
        }
        eSizes[eSize] = je
    ret["eSizes"] = eSizes

    func_i("Negative")
    func_i("Chrome")
    func_i("HZ")
    func_i("RealTime")
    func_i("Revision")
    func_str("SerialNumber")
    func_str("FwVersion")
    func_str("HwVersion")
    func_str("ProductionDate")
    func_str("FpgaVersion")
    """
      Option(PIXEL_FORMAT): 0
        RawFormat(): FourCC RGGB, BitsPerPixel 8
    """
    options = {}
    ret["Options"] = options
    val = func_i("Option", store=False)
    fline = func_str("RawFormat", store=False)
    m = re.match(r"FourCC (.+), BitsPerPixel ([0-9+])", fline)
    FourCC = m.group(1)
    BitsPerPixel = int(m.group(2))
    j = {
        "val": val,
        "FourCC": FourCC,
        "BitsPerPixel": BitsPerPixel,
    }
    options["PIXEL_FORMAT"] = j

    return ret
