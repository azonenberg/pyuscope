from uscope.config import get_bc, get_usc
from uscope.motion.plugins import get_motion_hal, configure_motion_hal
from uscope.kinematics import Kinematics
from uscope.imager import gst
from uscope.gui import plugin
from uscope.imager.imager_util import auto_detect_source
"""
CLI capable
Do not use any Qt concepts?
    Could consider signals / slots w/o GUI though
"""
"""
Initialization passes:
-Create basic objects
-Configure objects

Two phases are required as some parameters depend on others
Ex: timing parameters are generated based on misc factors
"""


class Microscope:
    def __init__(self, log=None, configure=True, **kwargs):
        self.bc = None
        self.usc = None
        self.imager = None
        self.motion = None
        self.kinematics = None

        if log is None:
            log = print
        self._log = log

        self.init(**kwargs)
        if configure:
            self.configure()

    def log(self, msg):
        self._log(msg)

    def init(
        self,
        bc=None,
        usc=None,
        imager=None,
        kinematics=None,
        motion=None,
        joystick=None,
        imager_cli=False,
        auto=True,
    ):
        if bc is None:
            bc = get_bc()
        self.bc = bc

        if usc is None:
            usc = get_usc()
        self.usc = usc

        if imager is None and imager_cli and auto:
            imager = gst.get_cli_imager_by_config(usc=self.usc,
                                                  microscope=self)
        self.imager = imager

        if motion is None and auto:
            motion = get_motion_hal(usc=self.usc,
                                    microscope=self,
                                    log=self.log)
        self.motion = motion

        if kinematics is None and auto:
            kinematics = Kinematics(
                microscope=self,
                log=self.log,
            )
        self.kinematics = kinematics
        """
        if joystick is None and auto:
            try:
                joystick = Joystick(ac=self.ac)
            except JoystickNotFound:
                pass
        """
        self.joystick = joystick

    def configure(self):
        if self.motion:
            # self.motion.configure()
            configure_motion_hal(self)
        if self.imager:
            self.imager.configure()
        if self.kinematics:
            self.kinematics.configure()
        if self.joystick:
            self.joystick.configure()

    def get_planner(self, pconfig, out_dir):
        raise Exception("fixme")


def get_cli_microscope(name=None):
    usc = get_usc(name=name)
    return Microscope(usc=usc, imager_cli=True)


def get_gui_microscope(name=None):
    usc = get_usc(name=name)
    return Microscope(usc=usc, imager_gui=True)
