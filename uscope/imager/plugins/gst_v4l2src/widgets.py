from PyQt5 import Qt
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *

from uscope.gui.control_scroll import GstControlScroll

from collections import OrderedDict

groups_gst = OrderedDict([
    ("HSV+", [
        {
            "prop_name": "brightness",
            "min": 0,
            "max": 255
        },
        {
            "prop_name": "contrast",
            "min": 0,
            "max": 255
        },
        {
            "prop_name": "saturation",
            "min": 0,
            "max": 100
        },
        {
            "prop_name": "hue",
            "min": -180,
            "max": 180
        },
    ]),
])


class V4L2GstControlScroll(GstControlScroll):
    """
    Display a number of gst-toupcamsrc based controls and supply knobs to tweak them
    """
    def __init__(self, vidpip, usc=None, parent=None):
        GstControlScroll.__init__(self,
                                  vidpip=vidpip,
                                  groups_gst=groups_gst,
                                  usc=usc,
                                  parent=parent)

    def auto_exposure_enabled(self):
        # FIXME: is this accurate? There might be a prop
        return True
