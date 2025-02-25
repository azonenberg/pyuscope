#!/usr/bin/python
"""
See PLANNER.md for configuration info

pr0ncnc: IC die image scan
Copyright 2010 John McMaster <JohnDMcMaster@gmail.com>
Licensed under a 2 clause BSD license, see COPYING for details

au was supposed to be a unitless unit
In practice I do everything in mm
So everything is represented as mm, but should work for any unit
"""

from collections import OrderedDict
import json
import math
import os
import threading
import time
import datetime

from uscope.motion.hal import DryHal
# FIXME: hack, maybe just move the baacklash parsing out
# at least to stand alone function
from uscope.config import PC
from uscope.planner.plugin import get_planner_plugin


class PlannerStop(Exception):
    pass


# Version 2 w/ pipeline
class Planner:
    """
    config: JSON like configuration settings
    """
    def __init__(
        self,
        # JSON like configuration settings affecting produced data
        # ex: verbosity, dry, objects are not included
        pconfig=None,
        pc=None,
        # Movement HAL
        motion=None,

        # Image parameters
        # Imaging HAL
        # Takes pictures but doesn't know about physical world
        imager=None,
        # Supply one of the following
        # Most users should supply mm_per_pix
        # mm_per_pix=None,
        # (w, h) in movement units
        # image_wh_mm=None,
        out_dir=None,
        # No movement without setting true
        dry=False,
        meta_base=None,
        # Log message callback
        # Inteded for main GUI log window
        # Defaults to printing to stdout
        log=None,
        # As objectives
        pipeline=None,
        # As plugin names
        pipeline_names=None,
        microscope=None,
        verbosity=None):
        if verbosity is None:
            verbosity = 2
        if log is None:

            def log(msg='', verbosity=None):
                print(msg)

        self._log = log
        self.v = verbosity
        self.out_dir = out_dir

        if pc:
            self.pc = pc
        else:
            self.pc = PC(j=pconfig)

        self.dry = dry
        if self.dry:
            self.motion = DryHal(motion, log=log)
        else:
            self.motion = motion
        if not self.motion:
            self.log("WARNING: no mention")
        self.pc.motion.set_axes_meta(self.motion.axes())

        self.imager = imager
        if not self.motion:
            self.log("WARNING: no imager")

        self.microscope = microscope

        if not meta_base:
            self.meta_base = {}
        else:
            self.meta_base = meta_base

        if pipeline is not None:
            self.pipeline = pipeline
        elif pipeline_names is not None:
            self.pipeline = self.make_pipeline(pipeline_names)
        else:
            raise ValueError("Need pipeline")
        self.log("Planner pipeline: %s" % (self.pipeline.keys(), ))

        self.progress_callbacks = []

        # Optimization for planner stacking to avoid extra movements
        # https://github.com/Labsmore/pyuscope/issues/180
        self.z_center = None

        # polarity such that can wait on being set
        self.unpaused = threading.Event()
        self.unpaused.set()
        self.running = True

    def make_pipeline(self, pipeline):
        # Currently pipeline elements must be unique by name
        ret = OrderedDict()
        for name in pipeline:
            ret[name] = get_planner_plugin(self, name)
        return ret

    def image_wh(self):
        """Final snapshot image width, height after scaling"""
        raww, rawh = self.imager.wh()
        """
        w = int(raww * self.pc.image_scalar_hint())
        h = int(rawh * self.pc.image_scalar_hint())
        return w, h
        """
        # planner no longer scales the images, now the Imager does
        return raww, rawh

    def check_running(self):
        if not self.running:
            raise PlannerStop()

    def log(self, msg='', verbosity=2):
        if verbosity <= self.v:
            self._log(str(msg))

    def is_paused(self):
        return not self.unpaused.is_set()

    def pause(self):
        '''Used to pause movement'''
        self.unpaused.clear()

    def unpause(self):
        self.unpaused.set()

    def wait_unpaused(self):
        if not self.unpaused.is_set():
            self.log('Planner paused')
            while True:
                val = self.unpaused.wait(timeout=0.1)
                self.check_running()
                if val:
                    break
            self.log('Planner unpaused')

    def stop(self):
        self.running = False

    def write_meta(self):
        # Copy config for reference
        def dumpj(j, fn):
            if self.dry:
                return
            with open(os.path.join(self.out_dir, fn), 'w') as f:
                f.write(
                    json.dumps(j,
                               sort_keys=True,
                               indent=4,
                               separators=(',', ': ')))

        meta = self.gen_meta()
        dumpj(meta, 'uscan.json')
        return meta

    def img_fn_prefix(self):
        return "_".join(self.state.fn_prefixes)

    def scan_begin(self):
        self.log('Generated by pyuscope on %s' %
                 (time.strftime("%Y-%m-%d %H:%M:%S"), ))
        self.log("General notes:")
        self.log(
            "  Pixel counts are for final scaled image as written to disk")
        self.imager.log_planner_header(self.log)
        for plugin in self.pipeline.values():
            plugin.log_scan_begin()
        if self.dry:
            self.log('DRY: mkdir(%s)' % self.out_dir)
        else:
            if not os.path.exists(self.out_dir):
                self.log('Creating output directory %s' % self.out_dir)
                os.mkdir(self.out_dir)
        # self.motion.begin()
        state = {
            "type": "begin",
            "images_to_capture": self.images_expected(),
        }
        for plugin in self.pipeline.values():
            self.check_yield()
            plugin.scan_begin(state)
        self.emit_progress(state)

    def scan_end(self):
        self.log("")
        self.log("Cleaning up scan")
        state = {
            "type": "end",
            "images_to_capture": self.images_expected(),
        }
        for plugin in self.pipeline.values():
            self.check_yield()
            plugin.scan_end(state)
        assert state["images_to_capture"] == state["images_captured"]
        self.log()
        self.log()
        self.log()
        self.log("Done!")
        for plugin in self.pipeline.values():
            plugin.log_scan_end()
        # Really done, make it the last thing we do
        self.emit_progress(state)

    def make_state2(self, state, modifiers, replace_keys):
        # FIXME: should do deep copy? Need to think this out a bit more
        # For now keep things simple
        # Or maybe top level only is in fact the contract?
        ret = dict(state)
        for k, v in modifiers.items():
            if k == "filename_part":
                parts = list(ret.get("filename_parts", []))
                parts.append(v)
                ret["filename_parts"] = parts
            else:
                assert 0, f"unexpected modifier {k}"
        for k, v in replace_keys.items():
            ret[k] = v
        return ret

    def check_yield(self):
        self.check_running()
        self.wait_unpaused()

    def run_pipeline(self, pipeline_list=None, state=None):
        """
        Depth first iteration down pipeline values
        """
        if pipeline_list is None:
            pipeline_list = list(self.pipeline.values())
        if state is None:
            # Anything directly here has to be of type image
            # However a plugin can directly call emit_progress() if it really needs another message type
            state = {"type": "image"}
        if len(pipeline_list) == 0:
            yield state
            return
        plugin = pipeline_list[0]
        # print("pipeline: %s" % (state, ))
        for val in plugin.iterate(state):
            self.check_yield()
            if val is None:
                state2 = state
            else:
                modifiers, replace_keys = val
                # print("mk state2", modifiers, replace_keys)
                state2 = self.make_state2(state, modifiers, replace_keys)
            # print("state2: %s" % (state2, ))
            for state3 in self.run_pipeline(pipeline_list=pipeline_list[1:],
                                            state=state2):
                # print("state3: %s" % (state3, ))
                self.check_yield()
                yield state3

    def run(self):
        self.check_yield()
        self.full_start_time = time.time()
        self.scan_begin()
        self.scan_start_time = time.time()
        for state in self.run_pipeline():
            self.emit_progress(state)
        self.scan_end_time = time.time()
        self.check_yield()
        self.scan_end()
        meta = self.write_meta()
        state = {
            "type": "meta",
            "meta": meta,
        }
        self.emit_progress(state)
        return meta

    def emit_progress(self, state):
        # self.pipeline["scraper"].emit_progress(state)
        for callback in self.progress_callbacks:
            callback(state)

    def gen_meta(self):
        '''Can only be called after run'''
        """
        Bump patch when adding w/o breaking something
        Bump minor when making a small breaking change
        Bump major when making a big breaking change
        """

        ret = self.meta_base
        ret["version"] = "2.0.0"
        # User scan parameters
        ret['pconfig'] = self.pc.j
        """
        axesj = {}
        plannerj["axes"] = axesj
        for axisc, axis in self.axes.items():
            axesj[axisc] = axis.meta()
        """

        # In seconds
        # Running scan
        ret['scan_time'] = self.scan_end_time - self.scan_start_time
        # Including setup / teardown
        ret["time_end"] = datetime.datetime.utcnow().isoformat()

        for plugin in self.pipeline.values():
            plugin.gen_meta(ret)

        self.full_end_time = time.time()
        ret['full_time'] = self.full_end_time - self.full_start_time
        ret["pipeline"] = list(self.pipeline.keys())

        return ret

    """
    Convenience functions
    """

    def filanme_prefix(self, state):
        return os.path.join(self.out_dir, "_".join(state["filename_parts"]))

    def register_progress_callback(self, callback):
        # self.pipeline["scraper"].register_progress_callback(callback)
        self.progress_callbacks.append(callback)

    def images_expected(self):
        ret = 1
        for plugink, plugin in self.pipeline.items():
            expected = plugin.images_expected()
            if expected is not None:
                assert expected > 0, (plugink, expected)
                ret *= expected
        # print('ret', ret)
        return ret

    def images_captured(self):
        return self.pipeline["scraper"].images_captured

    def stacking(self):
        """Return true if focus stacking enabled"""
        return "points-stacker" in self.pipeline
