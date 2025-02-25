"""
[HLP:$$ $# $G $I $N $x=val $Nx=line $J=line $SLP $C $X $H ~ ! ? ctrl-x]
ok

Case insensitive best I can tell
"""

from uscope.motion.hal import MotionHAL, MotionCritical

from uscope import util
from uscope.motion.motion_util import parse_move
import termios
import serial
import time
import os
import threading
import glob
import struct
from uscope.util import tobytes, tostr
import hashlib
from uscope.config import default_microscope_name


class GrblException(Exception):
    pass


class Timeout(GrblException):
    pass


class HomingFailed(GrblException):
    pass


class Estop(GrblException):
    pass


def default_port():
    port = os.getenv("GRBL_PORT", None)
    if port:
        return port
    # https://github.com/Labsmore/pyuscope/issues/62
    # /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0
    # When two are plugged in only one shows up
    ports = glob.glob("/dev/serial/by-id/usb-1a86_USB_Serial-*")
    if len(ports) == 0:
        raise Exception("Failed to auto detect any GRBL serial ports")
    if len(ports) == 1:
        return ports[0]
    raise Exception("Need explicit GRBL serial port (ie GRBL_PORT=/dev/blah)")


def trim_data_line(l):
    # print("test", l)
    assert l[0] == "["
    assert l[-1] == "]"
    return l[1:-1]


def trim_status_line(l):
    if len(l) < 2:
        raise ValueError("bad status line, len=%u" % len(l))
    # print("test", l)
    assert l[0] == "<"
    assert l[-1] == ">"
    return l[1:-1]


def format_axis3(v):
    """
    Rounding errors on float can cause fine positioning errors?
    """
    ret = "%0.3f" % v
    # print("axis3", ret)
    return ret


"""
https://www.sainsmart.com/blogs/news/grbl-v1-1-quick-reference
"""

error_i2s = {
    1: "GCode Command letter was not found",
    2: "GCode Command value invalid or missing",
    3: "Grbl '$' not recognized or supported",
    4: "Negative value for an expected positive value",
    5: "Homing fail. Homing not enabled in settings",
    6: "Min step pulse must be greater than 3usec",
    7: "EEPROM read failed. Default values used",
    8: "Grbl '$' command Only valid when Idle",
    9: "GCode commands invalid in alarm or jog state",
    10: "Soft limits require homing to be enabled",
    11: "Max characters per line exceeded. Ignored",
    12: "Grbl '$' setting exceeds the maximum step rate",
    13: "Safety door opened and door state initiated",
    14: "Build info or start-up line > EEPROM line length",
    15: "Jog target exceeds machine travel, ignored",
    16: "Jog Cmd missing '=' or has prohibited GCode",
    17: "Laser mode requires PWM output",
    20: "Unsupported or invalid GCode command",
    21: "> 1 GCode command in a modal group in block",
    22: "Feed rate has not yet been set or is undefined",
    23: "GCode command requires an integer value",
    24: "> 1 GCode command using axis words found",
    25: "Repeated GCode word found in block",
    26: "No axis words found in command block",
    27: "Line number value is invalid",
    28: "GCode Cmd missing a required value word",
    29: "G59.x WCS are not supported",
    30: "G53 only valid with G0 and G1 motion modes",
    31: "Unneeded Axis words found in block",
    32: "G2/G3 arcs need >= 1 in-plane axis word",
    33: "Motion command target is invalid",
    34: "Arc radius value is invalid",
    35: "G2/G3 arcs need >= 1 in-plane offset word",
    36: "Unused value words found in block",
    37: "G43.1 offset not assigned to tool length axis",
    38: "Tool number greater than max value",
}

alarm_i2s = {
    1: "Hard limit triggered. Position Lost",
    2: "Soft limit alarm, position kept. Unlock is Safe",
    3: "Reset while in motion. Position lost",
    4: "Probe fail. Probe not in expected initial state",
    5: "Probe fail. Probe did not contact the work",
    6: "Homing fail. The active homing cycle was reset",
    7: "Homing fail. Door opened during homing cycle",
    8: "Homing fail. Pull off failed to clear limit switch",
    9: "Homing fail. Could not find limit switch",
}

config_i2s = {
    0: "Step pulse, microseconds",
    1: "Step idle delay, milliseconds",
    2: "Step port invert, XYZmask*",
    3: "Direction port invert, XYZmask*",
    4: "Step enable invert, (0=Disable, 1=Invert)",
    5: "Limit pins invert, (0=N-Open. 1=N-Close)",
    6: "Probe pin invert, (0=N-Open. 1=N-Close)",
    10:
    "Status report, ‘?’ status.  0=WCS position, 1=Machine position, 2= plan/buffer and WCS position, 3=plan/buffer and Machine position",
    11: "Junction deviation, mm",
    12: "Arc tolerance, mm",
    13: "Report in inches, (0=mm. 1=Inches)**",
    20: "Soft limits, (0=Disable. 1=Enable, Homing must be enabled)",
    21: "Hard limits, (0=Disable. 1=Enable)",
    22: "Homing cycle, (0=Disable. 1=Enable)",
    23: "Homing direction invert, XYZmask* Sets which corner it homes to",
    24: "Homing feed, mm/min",
    25: "Homing seek, mm/min",
    26: "Homing debounce, milliseconds",
    27: "Homing pull-off, mm",
    30: "Max spindle speed, RPM",
    31: "Min spindle speed, RPM",
    32: "Laser mode, (0=Off, 1=On)",
    100: "Number of X steps to move 1mm",
    101: "Number of Y steps to move 1mm",
    102: "Number of Z steps to move 1mm",
    110: "X Max rate, mm/min",
    111: "Y Max rate, mm/min",
    112: "Z Max rate, mm/min",
    120: "X Acceleration, mm/sec^2",
    121: "Y Acceleration, mm/sec^2",
    122: "Z Acceleration, mm/sec^2",
    130: "X Max travel, mm Only for Homing and Soft Limits",
    131: "Y Max travel, mm Only for Homing and Soft Limits",
    132: "Z Max travel, mm Only for Homing and Soft Limits",
}
"""
Firmware configuration
Cannot be changed after build w/o reflashing
vm1: V
    VARIABLE_SPINDLE
x1: VZL
    VARIABLE_SPINDLE
    HOMING_FORCE_SET_ORIGIN
    HOMING_INIT_LOCK_N
Settings ending in _N are inverted
"""
info_c2s = {
    'V': "VARIABLE_SPINDLE",
    'N': "USE_LINE_NUMBERS",
    'M': "ENABLE_M7",
    'C': "COREXY",
    'P': "PARKING_ENABLE",
    'Z': "HOMING_FORCE_SET_ORIGIN",
    'H': "HOMING_SINGLE_AXIS_COMMANDS",
    'T': "LIMITS_TWO_SWITCHES_ON_AXES",
    'A': "ALLOW_FEED_OVERRIDE_DURING_PROBE_CYCLES",
    'D': "USE_SPINDLE_DIR_AS_ENABLE_PIN",
    '0': "SPINDLE_ENABLE_OFF_WITH_ZERO_SPEED",
    'S': "ENABLE_SOFTWARE_DEBOUNCE",
    'R': "ENABLE_PARKING_OVERRIDE_CONTROL",
    # Inverted
    'L': "HOMING_INIT_LOCK_N",
    '+': "ENABLE_SAFETY_DOOR_INPUT_PIN",
    '*': "ENABLE_RESTORE_EEPROM_WIPE_ALL_N",
    '$': "ENABLE_RESTORE_EEPROM_DEFAULT_SETTINGS_N",
    '#': "ENABLE_RESTORE_EEPROM_CLEAR_PARAMETERS_N",
    'I': "ENABLE_BUILD_INFO_WRITE_COMMAND_N",
    'E': "FORCE_BUFFER_SYNC_DURING_EEPROM_WRITE_N",
    'W': "FORCE_BUFFER_SYNC_DURING_WCO_CHANGE_N",
    '2': "ENABLE_DUAL_AXIS",
}


class GrblError(Exception):
    def __init__(self, msg):
        # error:9
        try:
            if "error" in msg:
                code = int(msg.split(":")[1])
                human = error_i2s[code]
                new_msg = f"error {code} ({human})"
            else:
                new_msg = f"unknown error {msg}"
        except:
            new_msg = f"unknown error {msg}"
        super().__init__(new_msg)


class GRBLSer:
    def __init__(
        self,
        port=None,
        # All commands I've seen so far complete responses in < 10 ms
        # so this should be plenty of margin for now
        ser_timeout=0.15,
        flush=True,
        verbose=None):
        self.serial = None
        if port is None:
            port = default_port()
        self.verbose = verbose if verbose is not None else bool(
            int(os.getenv("GRBLSER_VERBOSE", "0")))
        # For debugging concurrency issue
        self.poison_threads = False
        self.last_thread = None
        self.ser_timeout = ser_timeout

        self.verbose and print("opening %s in thread %s" %
                               (port, threading.get_ident()))

        # workaround for pyserial toggling flow control lines on open
        # https://github.com/pyserial/pyserial/issues/124
        f = open(port)
        attrs = termios.tcgetattr(f)
        """
       HUPCL  Lower modem control lines after last process closes the
              device (hang up).

       TCSAFLUSH
              the change occurs after all output written to the object
              referred by fd has been transmitted, and all input that
              has been received but not read will be discarded before
        """
        attrs[2] = attrs[2] & ~termios.HUPCL
        termios.tcsetattr(f, termios.TCSAFLUSH, attrs)
        f.close()

        # Now carefuly do an open
        self.serial = serial.Serial(
            port,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            rtscts=False,
            dsrdtr=False,
            xonxoff=False,
            timeout=ser_timeout,
            # Blocking writes
            writeTimeout=None)

        if flush:
            # Try to abort an in progress command
            # ^X will also work but resets whole controller
            # ^C does not work
            # WARNING: ! will also freeze most commands but not ?
            # they will buffer into unfrozen
            self.flush()

    def close(self):
        if self.serial:
            self.serial.close()
            self.serial = None

    def __del__(self):
        self.close()

    def flush(self):
        """
        Wait to see if there is anything in progress

        NOTE: blue system
        flushing b'[MSG:Estop is activated!]\r\nok\r\n[MSG:Estop is activated!]\r\nok\r\n'
        """
        self.serial.flushInput()
        self.serial.flushOutput()
        timeout = self.serial.timeout
        try:
            self.serial.timeout = 0.1
            while True:
                c = self.serial.read(1024)
                if b"Estop is activated" in c:
                    raise Estop()
                if not c:
                    return
        finally:
            self.serial.timeout = timeout

    def tx(self, out, nl=True):
        self.verbose and print("tx '%s'" % (out, ))

        if self.poison_threads:
            if self.last_thread:
                assert self.last_thread == threading.get_ident(), (
                    self.last_thread, threading.get_ident())
            else:
                self.last_thread = threading.get_ident()
            print("grbl thread: %s" % threading.get_ident())

        if nl:
            out = out + '\r'
        out = out.encode('ascii')
        # util.hexdump(out)
        self.serial.write(out)
        self.serial.flush()

    def txb(self, out):
        # self.verbose and print("tx '%s'" % (out, ))
        # util.hexdump(out)
        self.serial.write(out)
        self.serial.flush()

    def readline(self):
        tstart = time.time()
        b = self.serial.readline()
        if self.verbose:
            tend = time.time()
            print("rx %u bytes in %0.3f sec" % (len(b), tend - tstart))
            if self.verbose >= 2:
                util.hexdump(b)
        return b.decode("ascii").strip()

    def txrxs(self, out, nl=True, trim_data=True, timeout=None):
        """
        Send a command and return array of lines before ok line
        """
        if timeout is None:
            timeout = self.ser_timeout
        self.tx(out, nl=nl)
        ret = []
        tstart = time.time()
        while True:
            if time.time() - tstart > timeout:
                raise Timeout()
            l = self.readline().strip()
            self.verbose and print("rx '%s'" % (l, ))
            if not l:
                continue
            elif l == "ok":
                return ret
            elif l.find("error") == 0:
                raise GrblError(l)
            else:
                if trim_data:
                    ret.append(trim_data_line(l))
                else:
                    ret.append(l)

    def txrx0(self, out, nl=True):
        """
        Send a command and expect nothing back before ok
        """
        ret = self.txrxs(out, nl=nl)
        assert len(ret) == 0

    def txrx(self, out, nl=True):
        """
        Send a command and expect one line back before ok
        """
        ret = self.txrxs(out, nl=nl)
        assert len(ret) == 1
        return ret[0]

    def help(self):
        """
        [HLP:$$ $# $G $I $N $x=val $Nx=line $J=line $SLP $C $X $H ~ ! ? ctrl-x]
        """
        return self.txrx("$")

    def reset(self):
        """
        ^X
        Grbl 1.1f ['$' for help]
        """
        self.tx("\x18", nl=False)
        # Leave recovery to higher level logic
        """
        l = self.readline().strip()
        assert l == ""
        l = self.readline().strip()
        assert "Grbl" in l, l
        """

    def tilda(self):
        """Cycle Start/Resume from Feed Hold, Door or Program pause"""
        self.tx("~", nl=False)

    def exclamation(self):
        """Feed Hold – Stop all motion"""
        self.tx("!", nl=False)

    def dollar(self):
        """
        $$
        $0=10
        $1=25
        $2=0
        $3=2
        $4=0
        $5=0
        $6=0
        $10=1
        $11=0.010
        $12=0.002
        $13=0
        $20=0
        $21=0
        $22=0
        $23=0
        $24=25.000
        $25=500.000
        $26=250
        $27=1.000
        $30=1000
        $31=0
        $32=0
        $100=800.000
        $101=800.000
        $102=800.000
        $110=1000.000
        $111=1000.000
        $112=600.000
        $120=30.000
        $121=30.000
        $122=30.000
        $130=200.000
        $131=200.000
        $132=200.000
        """
        return self.txrxs("$$", trim_data=False)

    def hash(self):
        """
        [G54:0.000,0.000,0.000]
        [G55:0.000,0.000,0.000]
        [G56:0.000,0.000,0.000]
        [G57:0.000,0.000,0.000]
        [G58:0.000,0.000,0.000]
        [G59:0.000,0.000,0.000]
        [G28:0.000,0.000,0.000]
        [G30:0.000,0.000,0.000]
        [G92:0.000,0.000,0.000]
        [TLO:0.000]
        [PRB:0.000,0.000,0.000:0]
        ok
        """
        return self.txrxs("$#")

    def question(self):
        """
        <Idle|MPos:0.000,0.000,0.000|FS:0,0|WCO:0.000,0.000,0.000>
        <Idle|MPos:0.000,0.000,0.000|FS:0,0|Ov:100,100,100>
        <Idle|MPos:0.000,0.000,0.000|FS:0,0>
        """
        self.tx("?", nl=False)
        l = self.readline()
        self.verbose and print("rx '%s'" % (l, ))
        return trim_status_line(l)

    def c(self):
        """
        $C
        """

    def g(self):
        """
        $G
        [GC:G0 G54 G17 G21 G90 G94 M5 M9 T0 F0 S0]
        """
        return self.txrx("$G")

    def h(self):
        """
        2023-09-04
        timeout was 120, but now that it homes in one pass needs to be longer
        Move to 180

        run homing cycle
        Can take a long time, easily 85 seconds
        Doesn't seem to be a way to get status while its running
        
        From homed positioned it took about 85 seconds to re-home
        
        from really far on z
        actually crashed and rebooted...
        10 or 15 sec
        output
            ALARM:9
            ok
            
            Grbl 1.1h ['$' for help]
            [MSG:'$H'|'$X' to unlock]
        """

        lines = self.txrxs("$H", trim_data=False, timeout=180)
        for line in lines:
            if line.find("ALARM") >= 0:
                raise HomingFailed()

    def i(self):
        """
        [VER:1.1f.20170801:]
        [OPT:V,15,128]
        ok

        "VER:ARM32 V2.2.20220826:",
        "OPT:VZL,35,254",
        """
        return self.txrxs("$I")

    def info(self):
        ver, opt = self.i()
        return ver, opt

    def j(self, command):
        """
        $J=G90 X0.0 Y0.0 F1
        """
        self.txrx0("$J=" + command)

    def n(self):
        """
        $N
        $N0=
        $N1=
        """
        return self.txrxs("$N")

    def x(self):
        """
        Clear alarm
        """
        self.txrx0("$X")

    def cancel_jog(self):
        """
        Immediately cancels the current jog state by a feed hold and
        automatically flushing any remaining jog commands in the buffer.
        """
        self.txb(b"\x85")

    def in_reset(self):
        self.tx("?", nl=False)
        l = self.readline()
        # print("got", len(l), l)
        # Line shoudl be quite long and have markers
        if len(l) > 4 and "<" in l and ">" in l:
            # Connection ok, no need to
            return False
        return True

    def reset_recover(self):
        # Prompt should come in about 1.5 seconds from start
        tbegin = time.time()
        while time.time() - tbegin < 2.0:
            l = self.readline()
            if len(l):
                break
        else:
            raise Exception("Timed out reestablishing communications")

        # Initial response should be newline
        # Wait until grbl reset prompt
        tstart = time.time()
        while time.time() - tstart < 1.0:
            # Grbl 1.1f ['$' for help]
            if "Grbl" in l:
                break
            # Normal timeout here?
            # Should be moving quickly now
            l = self.readline()


"""
Emulate a GRBL serial port for testng on the go
"""


class MockGRBLSer(GRBLSer):
    STATE_RESET = None
    STATE_IDLE = "Idle"

    def __init__(
        self,
        port="/dev/ttyUSB0",
        # some boards take more than 1 second to reset
        ser_timeout=3.0,
        flush=True,
        verbose=None):
        print("GRBL mock")
        self.verbose = verbose if verbose is not None else bool(
            int(os.getenv("GRBLSER_VERBOSE", "0")))
        self.verbose and print("MOCK: opening", port)
        self.ser_timeout = -1
        self.serial = None
        self.poison_threads = False
        self.reset()

    def in_reset(self):
        return self.state == self.STATE_RESET

    def reset_recover(self):
        if self.state == self.STATE_RESET:
            time.sleep(1.4)
            self.state = self.STATE_IDLE
        elif self.state != self.STATE_IDLE:
            assert 0

    def tx(self, out, nl=True):
        self.verbose and print("MOCK: tx", out)

    def txb(self, out):
        self.verbose and print("MOCK: txb", out)

    def txrx0(self, out, nl=True):
        self.verbose and print("MOCK: txrx0", out)

    def question(self):
        """
        Idle|MPos:8.000,0.000,0.000|FS:0,0|WCO:0.000,0.000,0.000
        Idle|MPos:8.000,0.000,0.000|FS:0,0|Ov:100,100,100
        Idle|MPos:8.000,0.000,0.000|FS:0,0
        """
        assert self.state
        time.sleep(0.05)
        return "%s|MPos:%0.3f,%0.3f,%0.3f|FS:0,0" % (
            self.state, self.mpos["x"], self.mpos["y"], self.mpos["z"])

    def j(self, command):
        # Parse a jog command and update state
        # Command completes instantly
        command = command.upper()
        # remove feedrate
        if "F" in command:
            command = command.split("F")[0]
        parts = command.split(" ")
        g = parts[0]
        if g == "G90":
            pos = parse_move(command.replace("G90 ", ""))
            for k, v in pos.items():
                k = k.lower()
                assert k in self.mpos
                assert type(v) in (int, float)
                self.mpos[k] = v
        elif g == "G91":
            pos = parse_move(command.replace("G91 ", ""))
            for k, v in pos.items():
                k = k.lower()
                assert k in self.mpos
                assert type(v) in (int, float)
                self.mpos[k] += v
        else:
            raise ValueError(command)
        time.sleep(0.05)

    def reset(self):
        self.mpos = {
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
        }
        self.state = self.STATE_RESET
        time.sleep(0.05)

    def cancel_jog(self):
        self.state = self.STATE_IDLE
        time.sleep(0.05)

    def tilda(self):
        time.sleep(0.05)

    def flush(self):
        time.sleep(0.05)

    def txrxs(self, out, nl=True, trim_data=True, timeout=None):
        return "mock"

    def hash(self):
        return ["[G54:0.000,0.000,0.000]"]


class GRBL:
    def __init__(self,
                 port=None,
                 flush=True,
                 probe=True,
                 reset=False,
                 gs=None,
                 scalar=None,
                 verbose=None):
        """
        port: serial port file name
        gs: supply your own serial port object
        flush: try to clear old serial port communications before initializing
        probe: check communications at init to make sure controlelr is working
        reset: do a full reset at initialization. You will loose position and it will take a while
        verbose: yell stuff to the screen
        """

        self.gs = None
        self.qstatus_updated_cb = None
        self.pos_cache = None
        self.verbose = verbose if verbose is not None else bool(
            int(os.getenv("GRBL_VERBOSE", "0")))
        self.port = None
        if gs is None:
            if port == "mock":
                gs = MockGRBLSer(verbose=verbose)
            else:
                gs = GRBLSer(port=port, verbose=verbose)
                self.port = port
        assert gs
        self.gs = gs
        if flush:
            pass
        if probe:
            self.reset_probe()
        # WARNING: probe issue makes this unsafe to use first
        # CPU must be safely brought out of reset
        if reset:
            self.reset()

        # See move_relative
        self.use_soft_move_relative = int(os.getenv("GRBL_SOFT_RELATIVE", "1"))

    def set_qstatus_updated_cb(self, cb):
        self.qstatus_updated_cb = cb

    def close(self):
        if self.gs:
            self.gs.close()
            self.gs = None

    def __del__(self):
        self.close()

    def stop(self):
        # sometimes the stop is ignored
        # seems to happen especially for very low jog amounts
        while True:
            self.cancel_jog()
            if self.qstatus()["status"] == "Idle":
                break
            time.sleep(0.01)

    def reset(self):
        self.gs.reset()
        self.gs.reset_recover()

    def reset_probe(self):
        """
        Try to establish communications as a reset may be occurring
        Workaround for poorly understood issue (see below)
        Takes about 1.5 seconds typically to get response

        Weird connection startup issue
        Connecting serial port may reset the device (???)
        Workaround: probe will try to establish connection
        If can't get response, try to get the sync message back

        rx 2 bytes in 1.379 sec
        00000000  0D 0A

        typical resposne is < 0.05 sec
        """
        tbegin = time.time()

        if not self.gs.in_reset():
            return
        print("grbl: failed to respond, attempting reset recovery")
        self.gs.reset_recover()

        # Run full status command to be sure
        self.qstatus()
        # grbl: recovered after 1.388 sec
        print("grbl: recovered after %0.3f sec" % (time.time() - tbegin, ))

    def general_recover(self, retry=True):
        """
        Recover after communication issue when not in reset
        """
        tries = 3
        for tryi in range(tries):
            try:
                self.verbose and print("Recovering")
                # might have been put into hold
                self.gs.tilda()
                # Clear any commands in progress
                self.gs.flush()
                # Try a simple command
                self.qstatus(retry=retry)
                # Success!
                return
            except Exception:
                if not retry:
                    raise
                if tryi == tries - 2:
                    raise MotionCritical("Unable to recover GRBL comms")
                continue

    def set_pos_cache(self, pos):
        self.pos_cache = dict(pos)

    def update_pos_cache(self):
        self.qstatus()

    def qstatus(self, retry=True):
        """
        Idle|MPos:8.000,0.000,0.000|FS:0,0|WCO:0.000,0.000,0.000
        Idle|MPos:8.000,0.000,0.000|FS:0,0|Ov:100,100,100
        Idle|MPos:8.000,0.000,0.000|FS:0,0

        noisy example:
        rx '<Idle|MPos:-72.425,-25.634,0.000FS:0,0>'
        """
        tries = 3
        for i in range(tries):
            try:
                raw = self.gs.question()
                parts = raw.split("|")
                # FIXME: extra
                ij, mpos, fs = parts[0:3]
                mpos = (float(x) for x in mpos.split(":")[1].split(","))
                mpos = dict([(k, v) for k, v in zip("xyz", mpos)])
                self.set_pos_cache(mpos)
                ret = {
                    # Idle, Jog
                    "status": ij,
                    "MPos": mpos,
                    "FS": fs,
                }
                if self.qstatus_updated_cb:
                    self.qstatus_updated_cb(ret)
                return ret
            except Exception:
                if not retry:
                    raise
                self.verbose and print("WARNING: bad qstatus")
                if i == tries - 1:
                    raise
                # Uses qstatus
                self.general_recover(retry=False)
        assert 0

    def mpos(self):
        """Return current absolute machine position (as opposed to WCS)"""
        return self.qstatus()["MPos"]

    def wcs_offsets(self):
        """
        https://github.com/Labsmore/pyuscope/issues/135
        Take offsets from WCS1 but operate on WCS2
        Consider making this configurable / explicit
        """
        for l in self.gs.hash():
            if "G54" not in l:
                continue
            # [G54:0.000,0.000,0.000]
            l = l.split(":")[1].replace("]", "")
            parts = [float(x) for x in l.split(",")]
            return dict(zip("xyz", parts))
        assert 0, "Failed to parse WCS offset"

    def move_absolute(self, pos, f, blocking=True):
        tries = 3
        for i in range(tries):
            try:
                # implies G1
                ax_str = ''.join([
                    ' %c%s' % (k.upper(), format_axis3(v))
                    for k, v in pos.items()
                ])
                self.gs.j("G90 %s F%u" % (ax_str, f))
                if blocking:
                    self.wait_idle()
            except Exception:
                self.verbose and print("WARNING: bad absolute move")
                if i == tries - 1:
                    raise
                self.general_recover()

    def soft_move_relative(self, pos, f, blocking=True):
        # Could use old cache but probably an over optimization
        self.update_pos_cache()
        apos = {}
        for k, v in pos.items():
            apos[k] = self.pos_cache[k] + v
        self.move_absolute(apos, f=f, blocking=blocking)

    def move_relative(self, pos, f, blocking=True, soft=None):
        """
        WARNING: if a command errors its easy to move position
        You will need to deal with raised exceptions (which can be frequent)
        and recover based on whether or not the move happened
        Use soft_move_relative instead
        """
        if soft is None:
            soft = self.use_soft_move_relative
        if soft:
            return self.soft_move_relative(pos, f, blocking=blocking)
        else:
            # implies G1
            ax_str = ''.join([
                ' %c%s' % (k.upper(), format_axis3(v)) for k, v in pos.items()
            ])
            self.gs.j("G91 %s F%u" % (ax_str, f))
            if blocking:
                self.wait_idle()

    def wait_idle(self):
        while True:
            qstatus = self.qstatus()
            if qstatus["status"] == "Idle":
                break
            time.sleep(0.1)

    def jog(self, scalars, rate):
        """
        Note: jog is skipped in the case of command error
        """

        try:
            for axis, scalar in scalars.items():
                cmd = "G91 %s%0.3f F%u" % (axis, scalar, rate)
                self.verbose and print("JOG:", cmd)
                self.gs.j(cmd)
                if 0 and self.verbose:
                    mpos = self.qstatus()["MPos"]
                    print("jog: X%0.3f Y%0.3f Z%0.3F" %
                          (mpos["x"], mpos["y"], mpos["z"]))
        except Timeout:
            # Better to under jog than retry and over jog
            self.verbose and print("WARNING: dropping jog")
            self.general_recover()

    def do_cancel_jog(self):
        tries = 3
        timeout = 0.5
        for i in range(tries):
            try:
                tstart = time.time()
                while True:
                    if time.time() - tstart > timeout:
                        raise Timeout("Failed to cancel jog")
                    self.gs.cancel_jog()
                    if self.qstatus()["status"] == "Idle":
                        return
                    self.verbose and print("cancel: not idle yet")
            except Exception:
                self.verbose and print("WARNING: bad cancel jog")
                if i == tries - 1:
                    raise
                self.general_recover()

    def cancel_jog(self):
        self.do_cancel_jog()
        # Remove the feed hold a jog cancel causes
        self.gs.tilda()

    def i_parsed(self):
        # xxx: could cache this info. Its fixed
        ret = {}
        lines = self.gs.i()
        assert "VER" in lines[0]
        ret["VER"] = lines[0].split(":")[1]
        assert "OPT" in lines[1]
        l = lines[1].split(":")[1]
        opts_raw, block_buffer_size, rx_buffer_size = l.split(",")
        # Convert letter like L into HOMING_INIT_LOCK_N
        # XXX: should add HOMING_INIT_LOCK when HOMING_INIT_LOCK_N is not present?
        options = set([info_c2s[x] for x in opts_raw])
        if "HOMING_INIT_LOCK_N" not in options:
            options.add("HOMING_INIT_LOCK")
        ret["OPT"] = {
            "options": options,
            "block_buffer_size": int(block_buffer_size),
            "rx_buffer_size": int(rx_buffer_size),
        }
        return ret

    def selected_tool(self):
        for part in self.gs.g().split():
            if part[0] != "T":
                continue
            return int(part[1:])
        else:
            raise Exception("failed to parse")

    def dollar_kvs(self):
        for l in self.gs.dollar():
            if "=" not in l:
                continue
            k, v = l.strip().split("=")
            yield k, v

    def steps_per_mm(self):
        """
        Number steps to move x, y, and z axis
        Parameters 100, 101, and 102
        """
        ret = {}
        for k, v in self.dollar_kvs():
            """
            $100=800.000
            $101=800.000
            $102=800.000
            Sometimes the output is a string similar to:
            500.000 (x axis pulse:step/mm)
            """
            v = v.strip().split()[0]
            if k == "$100":
                ret["x"] = float(v)
            elif k == "$101":
                ret["y"] = float(v)
            elif k == "$102":
                ret["z"] = float(v)
        assert len(ret) == 3
        return ret


class GrblHal(MotionHAL):
    def __init__(self, verbose=None, port=None, grbl=None, **kwargs):
        self.grbl = None
        self.feedrate = None
        self._steps_per_mm = None

        MotionHAL.__init__(self, verbose=verbose, **kwargs)
        if grbl:
            self.grbl = grbl
        else:
            self.grbl = GRBL(port=port, verbose=verbose)

        # Hack, move out of here to Microscope or similar
        # Run early before any config is overriten though
        microscope_name = default_microscope_name()
        if microscope_name:
            self.validate_microscope_model(microscope_name)

        # hack: qstatus will fail before home
        self.home()
        self.grbl.set_qstatus_updated_cb(self.qstatus_updated)

    def _configured(self):
        self.calc_steps_per_mm()

    def calc_steps_per_mm(self):
        """
        Figure out the smallest possible machine delta
        Find the native machine epsilons and then multiply by config scalars
        """
        steps_per_mm = self.grbl.steps_per_mm()
        if "scalar" in self.modifiers:
            scalars = self.modifiers["scalar"].scalars
            steps_per_mm["x"] *= scalars["x"]
            steps_per_mm["y"] *= scalars["y"]
            steps_per_mm["z"] *= scalars["z"]
        self.steps_per_mm = steps_per_mm

    def epsilon(self):
        return {
            "x": 1 / self.steps_per_mm["x"],
            "y": 1 / self.steps_per_mm["y"],
            "z": 1 / self.steps_per_mm["z"],
        }

    def home(self):
        # Commands will fail until homed
        self.check_home()

    def qstatus_updated(self, status):
        # careful this will get modified up the stack
        self.update_status({"pos": dict(status["MPos"])})

    def axes(self):
        return {'x', 'y', 'z'}

    def _wcs_offsets(self):
        return self.grbl.wcs_offsets()

    def command(self, cmd):
        return "\n".join(self.grbl.gs.txrxs(cmd))

    def rc_commands(self, cmds):
        for cmd in cmds:
            rx = self.grbl.gs.txrxs(cmd)
            if "error" in rx:
                raise Exception("cmd failed: %s => %s" % (cmd, rx))

    def _pos(self):
        return self.grbl.qstatus()["MPos"]

    def _move_absolute(self, pos, tries=3):
        # print("grbl mv_abs", pos)
        self.grbl.move_absolute(pos, f=1000)

    def _move_relative(self, pos):
        # print("grbl mv_rel", pos)
        self.grbl.move_relative(pos, f=1000)

    def _jog(self, scalars):
        self.grbl.jog(scalars, self.jog_rate)

    def stop(self):
        # May be called during unclean shutdown
        if self.grbl:
            self.grbl.stop()

    def log_info(self):
        self.log("GRBL info")
        try:
            info = grbl_read_meta(self.grbl.gs)
        except NoGRBLMeta:
            self.log("  Config magic number not found")
            return
        self.log("  Comment: %s" % (info["comment"], ))
        self.log("  S/N: %s" % (info["sn"], ))
        self.log("  Config: %s" % (info["config"].hex(), ))

    def validate_microscope_model(self, name):
        try:
            info = grbl_read_meta(self.grbl.gs)
        except NoGRBLMeta:
            # No metadata => skip sanity check
            # Not all microscopes have this set
            return
        """
        If the controller supports self-reporting the microscpoe name
        Hack to verify at least until can be auto selected
        """
        expected = microscope_name_hash(name)
        if info["config"] != expected:
            print("Expected name: %s" % name)
            print("Expected config: %s" % (expected.hex(), ))
            print("Comment: %s" % (info["comment"], ))
            print("S/N: %s" % (info["sn"], ))
            print("Config: %s" % (info["config"].hex(), ))
            raise Exception(
                "Selected microscope config doesn't match expected model")

    def is_homed(self):
        """
        If HOMING_INIT_LOCK is set, we can rely on user hitting home button and maybe be homed
        Otherwise we need to emulate it through a hack
        """
        compile_options = self.grbl.i_parsed()["OPT"]["options"]
        # print("compile_options", compile_options)
        # The clean way: system is locked until homed
        if "HOMING_INIT_LOCK" in compile_options:
            status = self.grbl.qstatus()["status"]
            print(f"GRBL homing w/ INIT_LOCK, main status: {status}")
            # Otherwise should be Alarm state
            return status == "Idle"
        # A BadThing TM: no way to natively know if homed
        else:
            # Hack: use current tool to indicate homing
            # its volatile and resets to 0 on power off
            selected_tool = self.grbl.selected_tool()
            print(f"GRBL homing w/ hack, selected tool: {selected_tool}")
            return bool(selected_tool)

    def set_is_homed(self, is_homed=True):
        flags = int(is_homed)
        self.grbl.gs.txrxs("T%u" % flags)

    def check_home(self, lazy=True, force=False):
        """
        Depending on machine configuration homing may or may not be required
        """
        if not force and self.is_homed() and lazy:
            return

        tstart = time.time()
        # TLDR: gearbox means we need ot home several times
        # 2023-04-19: required 7 cycles in worst case...hmm add more wiggle room for now
        # related to 8/5 adjustment?
        for homing_try in range(8):
            print("Sending home command %u" % (homing_try + 1, ))
            try:
                self.grbl.gs.h()
                break
            except HomingFailed:
                print("Homing timed out, nudging again")
        else:
            raise HomingFailed("Failed to home despite several attempts :(")
        deltat = time.time() - tstart
        print("Homing successful after %0.1f sec. Ready to use!" % (deltat, ))
        self.set_is_homed()


class NoGRBLMeta(Exception):
    pass


# https://oeis.org/A245461
# USCOPE_MAGIC = (121, 966, 989)
# rounding issue, see below
# USCOPE_MAGIC = (12, 9, 68)
USCOPE_MAGIC = struct.pack("<I", 121966989)
"""
32 bit signed value
divided by 1000
Then multiplied by 1000
Loose about 1 bit each time => +/- 4
30 * 3 = 90 bits
88 bits => 11 bytes
28 bits should be safer though => 10 bytes


WCS max value
2147483
1000001100010010011011

In [3]: bin(2147483*1000)
Out[3]: '0b1111111111111111111110101111000'
In [4]: (1<<31)/2147483
Out[4]: 1000.0003017486052


2147483999

Must be some weird artifact from fractional part
999 => 3.5 * 3 = 10 bits
2147483 => 22 bits
sign: 1 bit
so yeah about 32 bits total
hmm

or put real ECC values on this?
whole: 23 bits
fractional: 

fractional bit rounds
loose 2 bits on each and/or 

mcmaster@thudpad:~/doc/ext/pyuscope$ ./test/grbl/write_meta.py --model "lipvm1" --sn "tst123"
out G10 L2 P5 X29556.000 Y12660.000 Z13106.000
out G10 L2 P6 X26988.121 Y30320.966 Z12653.989
mcmaster@thudpad:~/doc/ext/pyuscope$ ./test/grbl/read_meta.py
meta G58:29556.000,12660.000,13106.000
meta G59:26988.120,30320.968,12653.990
Config magic number not found

mcmaster@thudpad:~/doc/ext/pyuscope$ ./test/grbl/write_meta.py --model "lipvm1" --sn "tst123"
out G10 L2 P5 X29556.000 Y12660.000 Z13106.000
out G10 L2 P6 X26988.120 Y30320.968 Z12653.990
mcmaster@thudpad:~/doc/ext/pyuscope$ ./test/grbl/read_meta.py
meta G58:29556.000,12660.000,13106.000
meta G59:26988.120,30320.970,12653.990
Config magic number not found

Is there an advantage to 1024 vs 1000?
"""

WCS_STR_LEN = 9
WCS_COMMENT = 4
WCS_SN = 5
WCS_CONFIG = 6


def write_wcs_packed(gs, wcs, data):
    assert len(data) == WCS_STR_LEN
    assert 1 <= wcs <= 6
    nums = {}
    data = tobytes(data)
    for i in range(3):
        offset = 3 * i
        # Pad the unused byte and then normalize to the decimal version
        thisi = struct.unpack("<i", data[offset:offset + 3] + b"\x00")[0]
        nums[i] = thisi / 1000
    # Might be loosing a digit here to rounding
    # but we have enough wiggle room just drop it for now
    out = "G10 L2 P%u X%.3f Y%.3f Z%.3f" % (wcs, nums[0], nums[1], nums[2])
    # print("out", out)
    gs.txrxs(out)


def wcs_pad_str(s):
    assert len(s) <= WCS_STR_LEN

    if len(s) < WCS_STR_LEN:
        s = s + (" " * (WCS_STR_LEN - len(s)))
    return s


def wcs_pad_bytes(s):
    assert len(s) <= WCS_STR_LEN

    if len(s) < WCS_STR_LEN:
        s = s + (b" " * (WCS_STR_LEN - len(s)))
    return s


def grbl_write_meta(gs, config=None, sn=None, comment=None):
    """
    Write pyuscope metadata into GRBL controller
    Hack where metadata is stored as unused WCS sets
    """
    if not comment:
        comment = ""
    if not config:
        config = "     "
    if not sn:
        sn = ""

    # 4 / 9 bytes used. Others RFU
    # 4 / 9 for config hash
    # 1 reserved (config rev?)
    assert len(config) == 4
    config = USCOPE_MAGIC + tobytes(config) + b"\x00"

    write_wcs_packed(gs, WCS_COMMENT, wcs_pad_str(comment))
    write_wcs_packed(gs, WCS_SN, wcs_pad_str(sn))
    write_wcs_packed(gs, WCS_CONFIG, config)


def grbl_read_meta(gs):
    """
    Read pyuscope metadata from GRBL controller
    Hack where metadata is stored as unused WCS sets
    return
    {
        4 bytes fixed
        "config": b"",
        9 chars max
        "comment": "",
        9 chars max
        "sn": "",
    }
    """
    def parse_wcs_packed(numstr):
        pass

    items = {}
    for l in gs.hash():
        # WCS 4/5/6
        if "G56:" not in l and "G57:" not in l and "G58:" not in l and "G59:" not in l:
            continue
        # print("meta", l)
        # [G56:123.456,234.123,312.789]
        # 123.456,234.123,312.789
        gcode, coords = l.split(":")
        # G54 => 1
        wcsn = int(gcode[1:]) - 53
        buf = b""
        for part in coords.split(","):
            buf += struct.pack("<i", int(float(part) * 1000))[0:3]
        items[wcsn] = buf

    if items[WCS_CONFIG][0:len(USCOPE_MAGIC)] != USCOPE_MAGIC:
        raise NoGRBLMeta()
    ret = {}
    ret["config"] = items[WCS_CONFIG][len(USCOPE_MAGIC):len(USCOPE_MAGIC) + 4]
    # one unused reserved byte
    ret["config_rev"] = items[WCS_CONFIG][-1]
    ret["comment"] = tostr(items[WCS_COMMENT]).strip()
    ret["sn"] = tostr(items[WCS_SN]).strip()
    return ret


def microscope_name_hash(microscope):
    return hashlib.sha1(microscope.encode("ascii")).digest()[0:4]


def get_grbl(port=None, gs=None, reset=False, verbose=False):
    return GRBL(port=port, gs=gs, reset=reset, verbose=verbose)
