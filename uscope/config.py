import json5
import os
from collections import OrderedDict
from uscope.util import writej, readj
'''
A few general assumptions:
-Camera is changed rarely.  Therefore only one camera per config file
-Objectives are changed reasonably often
    They cannot changed during a scan
    They can be changed in the GUI
'''
"""
defaults = {
    "out_dir": "out",
    "imager": {
        "hal": 'mock',
        "snapshot_dir": "snapshot",
        "width": 3264,
        "height": 2448,
        "scalar": 0.5,
    },
    "motion": {
        # Good for testing and makes usable to systems without CNC
        "hal": "mock",
        "startup_run": False,
        "startup_run_exit": False,
        "overwrite": False,
        "backlash": 0.0,
    }
}
"""
defaults = {}

# microscope.j5
usj = None
config_dir = None


def get_usj(config_dir=None, name=None):
    global usj

    if usj is not None:
        return usj

    if not config_dir:
        if not name:
            name = os.getenv("PYUSCOPE_MICROSCOPE")
        if name:
            config_dir = "configs/" + name
        # Maybe just throw an exception at this point?
        else:
            config_dir = "config"
    globals()["config_dir"] = config_dir
    fn = os.path.join(config_dir, "microscope.j5")
    if not os.path.exists(fn):
        fn = os.path.join(config_dir, "microscope.json")
        if not os.path.exists(fn):
            raise Exception("couldn't find microscope.j5 in %s" % config_dir)
    with open(fn) as f:
        j = json5.load(f, object_pairs_hook=OrderedDict)

    def default(rootj, rootd):
        for k, v in rootd.items():
            if not k in rootj:
                rootj[k] = v
            elif type(v) is dict:
                default(rootj[k], v)

    default(j, defaults)
    usj = j
    return usj


"""
Calibration broken out into separate file to allow for easier/safer frequent updates
Ideally we'd also match on S/N or something like that
"""


def cal_fn(mkdir=False):
    if not config_dir:
        return None
    if mkdir and not os.path.exists(config_dir):
        os.mkdir(config_dir)
    return os.path.join(config_dir, "imager_calibration.j5")


def cal_load(source):
    fn = cal_fn()
    if fn is None or not os.path.exists(fn):
        return {}
    configj = readj(fn)
    configs = configj["configs"]
    for config in configs:
        if config["source"] == source:
            return config["properties"]
    return {}


def cal_load_all(source):
    fn = cal_fn()
    if not os.path.exists(fn):
        return
    configj = readj(fn)
    configs = configj["configs"]
    for config in configs:
        if config["source"] == source:
            return config
    return None


def cal_save(source, j):
    fn = cal_fn(mkdir=True)
    if not os.path.exists(fn):
        configj = {"configs": []}
    else:
        configj = readj(fn)

    configs = configj["configs"]

    jout = {"source": source, "properties": j}

    # Replace old config if exists
    for configi, config in enumerate(configs):
        if config["source"] == source:
            configs[configi] = jout
            break
    # Otherwise create new config
    else:
        configs.append(jout)

    print("Saving cal to %s" % fn)
    writej(fn, configj)


def get_planner_step(usj):
    """
    ideal faction of image to move between images
    Default: 0.7 => only overlap adjacent image by 30%
    """
    return float(usj.get("planner", {}).get("overlap", 0.7))


def get_planner_border(usj):
    """
    Automatically add this many mm to the edges of a panorama
    """
    return float(usj.get("planner", {}).get("border", 0.0))
