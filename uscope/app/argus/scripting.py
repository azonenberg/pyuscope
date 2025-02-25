from uscope.app.argus.widgets import ArgusTab
from uscope.config import get_data_dir, get_bc

from PyQt5 import Qt
from PyQt5.QtGui import *
from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
import importlib.util
import sys
import imp
import os
import ctypes
import threading
import time
import traceback


class TestFailed(Exception):
    pass


class TestAborted(Exception):
    pass


# class ArgusScriptingPlugin(threading.Thread):
# needed to do signals
class ArgusScriptingPlugin(QThread):
    log_msg = pyqtSignal(str)
    done = pyqtSignal()

    def __init__(self, ac):
        super().__init__()
        self._ac = ac
        self._input = None
        # Graceful shutdown request
        self._running = threading.Event()
        self.reset()

    def reset(self):
        self._succeeded = None
        self.result_message = None
        self._running.set()

    def log(self, s):
        """
        Log a message to the script window
        (not the main window)
        """
        self.log_msg.emit(s)

    def shutdown(self):
        """
        Request graceful termination
        """
        self._running.clear()

    def get_input(self):
        """
        Return the simple text input field value
        """
        return self._input

    def fail(self, message):
        """
        Thread should call this to abort a run
        Indicates the operation failed
        """
        self._succeeded = False
        self.result_message = message
        raise TestFailed(message)

    def check_running(self):
        """
        This thread should periodically check for graceful shutdown
        """
        if not self._running.is_set():
            raise TestAborted()

    def succeeded(self):
        return bool(self._succeeded)

    def run(self):
        try:
            self.run_test()
            self._succeeded = True
        except TestAborted:
            self._succeeded = False
            self.result_message = "Aborted"
        except TestFailed:
            self._succeeded = False
            self.result_message = "Failed"
        except Exception as e:
            self._succeeded = False
            self.result_message = f"Exception: {e}"
            print("")
            print("Script generated unhandled exception")
            traceback.print_exc()
        finally:
            self._running.clear()
            self.done.emit()

    """
    Main API
    """

    def run_scan(self, scanj):
        assert 0, "fixme"

    def snap_image(self, filename=None):
        assert 0, "fixme"

    def autofocus(self):
        """
        Autofocus at the current location
        """
        assert 0, "fixme"

    def pos(self):
        """
        Get current stage position
        Returns a dictionary like:
        {"x": 12.345, "y": 2.356, "z": 4.5}
        """
        self.check_running()
        return self._ac.motion_thread.pos_cache

    def move_absolute(self, pos, block=True):
        """
        Set current position
        Pos can include one or more positions like:
        {"z": 4.5}
        {"x": 12.345, "y": 2.356, "z": 4.5}
        """
        self.check_running()
        self._ac.motion_thread.move_absolute(pos, block=block)
        self.check_running()

    def sleep(self, t):
        self.check_running()
        # TODO: break this into smaller sleeps to check running
        time.sleep(t)
        self.check_running()

    def image(self):
        """
        Request and return a snapshot as PIL image
        """
        imager = self.imager()
        return imager.get()["0"]

    """
    Advanced API
    Try to use the higher level functions first if possible
    """

    def run_planner(self, pconfig):
        assert 0, "FIXME"

    def motion(self):
        """
        Get a (thread safe) motion object
        Access to the more powerful but less stable stage API
        """
        self._ac.motion_thread.get_planner_motion()

    def imager(self):
        """
        Get a (thread safe) imager object
        Access to the more powerful but less stable camera API
        """
        # Planner uses this directly / is already thread safe
        return self._ac.imager

    def kinematics(self):
        """
        Get a (thread safe) kinematics object
        Access to the more powerful but less stable system synchronization API
        """
        assert 0, "fixme"

    def backlash_disable(self, block=True):
        """
        Disable backlash compensation
        """
        self._ac.motion_thread.backlash_disable(block=block)

    def backlash_enable(self, block=True):
        """
        Enable backlash compensation
        """
        self._ac.motion_thread.backlash_enable(block=block)

    """
    Plugin defined functions
    """

    def run_test(self):
        """
        The script entry point
        The most important user function
        """
        pass

    def show_input(self):
        """
        Return a string label to get a simple text input field
        """
        return None


class ScriptingTab(ArgusTab):
    def __init__(self, ac, parent=None):
        super().__init__(ac=ac, parent=parent)
        self.stitcher_thread = None
        self.last_cs_upload = None

        fn = os.path.join(get_data_dir(), "script_log.txt")
        existed = os.path.exists(fn)
        self.log_all_fd = open(fn, "w+")
        if existed:
            self.log_all_fd.write("\n\n\n")
            self.log_all_fd.flush()

        self.plugin = None
        self.running = False

    def initUI(self):
        layout = QGridLayout()
        row = 0

        self.select_pb_rhodium_path = get_bc().script_rhodium_dir()

        if self.select_pb_rhodium_path:
            self.select_pb1 = QPushButton("Select script (uscope)")
        else:
            self.select_pb1 = QPushButton("Select script")
        self.select_pb1.clicked.connect(self.select_pb1_clicked)
        layout.addWidget(self.select_pb1, row, 0)
        row += 1

        if self.select_pb_rhodium_path:
            self.select_pb_rhodium = QPushButton("Select script (rhodium)")
            self.select_pb_rhodium.clicked.connect(
                self.select_pb_rhodium_clicked)
            layout.addWidget(self.select_pb_rhodium, row, 0)
            row += 1

        # self.test_name_cb = QComboBox()

        self.run_pb = QPushButton("Run")
        self.run_pb.setEnabled(False)
        self.run_pb.clicked.connect(self.run_pb_clicked)
        layout.addWidget(self.run_pb, row, 0)
        row += 1

        self.stop_pb = QPushButton("Stop gracefully")
        self.stop_pb.setEnabled(False)
        self.stop_pb.clicked.connect(self.stop_pb_clicked)
        layout.addWidget(self.stop_pb, row, 0)
        row += 1

        self.kill_pb = QPushButton("Kill")
        self.kill_pb.setEnabled(False)
        self.kill_pb.clicked.connect(self.kill_pb_clicked)
        layout.addWidget(self.kill_pb, row, 0)
        row += 1

        self.input_label = QLabel("Input")
        self.input_label.setVisible(False)
        layout.addWidget(self.input_label, row, 0)
        row += 1
        self.input_le = QLineEdit("")
        self.input_le.setVisible(False)
        layout.addWidget(self.input_le, row, 0)
        row += 1

        self.status_le = QLineEdit("Status: idle")
        layout.addWidget(self.status_le, row, 0)
        row += 1
        self.status_le.setReadOnly(True)

        # TODO: save button
        # Should always log to filesystem?
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        layout.addWidget(self.log_widget, row, 0)
        row += 1

        self.setLayout(layout)

    def select_pb1_clicked(self):
        filename = QFileDialog.getOpenFileName(None, "Select script",
                                               './uscope/script',
                                               "Script (*.py)")
        if not filename:
            return
        filename = str(filename[0])
        self.select_script(filename)

    def select_pb_rhodium_clicked(self):
        filename = QFileDialog.getOpenFileName(None, "Select script",
                                               self.select_pb_rhodium_path,
                                               "Script (*.py)")
        if not filename:
            return
        filename = str(filename[0])
        self.select_script(filename)

    def select_script(self, filename):
        spec = importlib.util.spec_from_file_location("pyuscope_plugin",
                                                      filename)
        plugin_module = importlib.util.module_from_spec(spec)
        sys.modules["pyuscope_plugin"] = plugin_module
        spec.loader.exec_module(plugin_module)
        # Entry point: construct the ArgusScriptingPlugin class named Plugin
        self.plugin = plugin_module.Plugin(ac=self.ac)

        self.input_label.setText(self.plugin.show_input())
        self.input_label.setVisible(bool(self.plugin.show_input()))
        self.input_le.setVisible(bool(self.plugin.show_input()))

        self.plugin.log_msg.connect(self.log_local)
        self.plugin.done.connect(self.plugin_done)

        self.log_widget.clear()
        self.status_le.setText("Status: idle")
        self.run_pb.setEnabled(True)

        # self.test_name_cb.clear()
        # for now just support one function
        # self.test_name_cb.addItem("run")
        # self.pconfig_sources[self.pconfig_source_cb.currentIndex()]
        self.log_local(f"Script selected: {filename}")

    def run_pb_clicked(self):
        if self.running:
            self.log_local("Can't run while already running")
            return

        if self.plugin.show_input():
            self.plugin._input = str(self.input_le.text())
        self.stop_pb.setEnabled(True)
        self.kill_pb.setEnabled(True)
        self.log_local("Plugin loading")
        self.plugin.reset()
        self.plugin.start()
        # pool = QThreadPool.globalInstance()
        # pool.start(self.plugin)
        self.status_le.setText("Status: running")
        self.running = True

    def stop_pb_clicked(self):
        if not self.running:
            self.log_local("Plugin isn't running")
            return
        self.plugin.shutdown()

    def kill_pb_clicked(self):
        if not self.running:
            self.log_local("Plugin isn't running")
            return

        thread_id = self.plugin.ident
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            thread_id, ctypes.py_object(SystemExit))
        if res > 1:
            ctypes.pythonapi.PyThreadState_SetAsyncExc(thread_id, 0)
            self.log_local("Exception raise failure")

    def plugin_done(self):
        if self.plugin.succeeded():
            status = "Status: finished ok"
        else:
            status = "Status: failed :("
        self.status_le.setText(status)
        self.stop_pb.setEnabled(False)
        self.kill_pb.setEnabled(False)
        if self.plugin.succeeded():
            self.log_local("Plugin completed ok")
        else:
            self.log_local("Plugin completed w/ issue")
            self.log_local(self.plugin.result_message)
        self.running = False

    def post_ui_init(self):
        pass

    def shutdown(self):
        if self.plugin:
            self.plugin.shutdown()
            self.plugin = None

    def log_local(self, s='', newline=True):
        s = str(s)
        # print("LOG: %s" % s)
        if newline:
            s += '\n'

        c = self.log_widget.textCursor()
        c.clearSelection()
        c.movePosition(QTextCursor.End)
        c.insertText(s)
        self.log_widget.setTextCursor(c)

        self.log_all_fd.write(s)
        self.log_all_fd.flush()
        """
        if self.log_plugin_fd is not None:
            self.log_plugin_fd.write(s)
            self.log_plugin_fd.flush()
        """
