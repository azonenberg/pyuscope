pyuscope controls digital microscopes using Python.
It primarily focuses on metallurgical microscopes with an emphasis on high resolution panoramas and advanced scripting.

Interested in purchasing a microscope? Please reach out to support@labsmore.com

Features:
* Argus GUI for easy imaging
  * Panoramic imaging including simple 2D and advanced 3D tracking
  * Focus stacking
  * HDR capture
  * Chain batch jobs together
  * Automatic panorama image stitching CloudStitch
* CLI applications for batch jobs
* Simple Python API for advanced applications


# Quick start

OS: we primarily test on Ubuntu 20.04 but other versions of Linux or MacOS might work

If you'd like a basic setup:

PYUSCOPE_MICROSCOPE=none setup_ubuntu_20.04.sh

Alternatively if you know your microscope configuration file (ie a dir in configs/) do something like this:

PYUSCOPE_MICROSCOPE=ls-hvy-2 setup_ubuntu_20.04.sh

After rebooting your system you can launch the PYUSCOPE_MICROSCOPE default microscope with:

./app/argus.py

If you want to explicitly specify a microscope:

./app/argus.py --microscope mock


# Supported hardware
Microscopes tend to be based on a GRBL motion controller + a Touptek USB camera. There are some older LinuxCNC and/or v4l flows but they aren't currently actively developed.

It's also possible to use the motion HAL / planner without gstreamer if you are ok launching from the CLI or writing your own GUI. Ex: we may add some basic SEM support this way



# User Guide

## Imaging

### Select lens configuration

![image](https://user-images.githubusercontent.com/463376/221096635-35fa9287-15cd-4cbc-a770-b1422c7006b8.png)

This dropdown displays a list of lens setups that exist in the configuration file used during application startup. Pick option that matches the lens currently being used to image.

This selection is required for correctly performing motion and imaging tasks and should be set when switching lenses, or performing any operations.

### Camera View and Focus View

![image](https://user-images.githubusercontent.com/463376/221098557-716aafc0-d8d9-4f4d-96d2-cb430581a49c.png)

The view in section `1` provides a video feed from the camera.

The view in section `2` provides a magnified sub-area of the camera feed to aid in fine tuning focus. _Note:_ since this view is highly magnified, it may never appear completely sharp, and is intended to be a guide to maximum achievable sharpness.

### Motion Controls

![image](https://user-images.githubusercontent.com/463376/221099110-2a0b45c0-d4a8-4ea5-b2f3-69053fcce966.png)

The `Motion` section provides controls to:
 * Set the bounding box for scans.
 * Enable `Jog` mode to move the microscope and in X, Y and Z directions.

#### `Jog` mode

Jog mode allows moving the microscope along the X, Y and Z axis. 

Enter and exit `Jog` mode by toggling the "Jog" button. 

The slider controls the speed and amount of each motion command. Use slider value `1` for fine grained motion, and increase the slider for a larger movement amount.

Enter `Jog` mode, by clicking the "Jog" button, then move the microscope via the following hotkeys:
 * `A` and `D` for the X-axis motion
 * `W` and `S` for the Y-axis motion
 * `Q` and `E` for the Z-axis motion
 * `Z` and `C` to change rate
 * `F` to toggle fine mode
  
  
#### Set Scan Bounding Box Coordinates

The two buttons `Lower left` and `Upper right` provide coordinates to define the area for a scan. To set either, move the microscope to the desired location, and click the button to set the current coordinate as that point.

Note: depending on the configuration of your specific microscope, these points might be flipped (e.g. "Upper left" vs. "Lower left").

### Snapshot

![image](https://user-images.githubusercontent.com/463376/221101267-117bf33c-b7b7-44b9-a5b6-09be092c7391.png)

Snapshot saves the current image to the filename specified with a datetime postfix.

### Scan

![image](https://user-images.githubusercontent.com/463376/221101432-259f1e5c-20b1-419f-aeae-c668bd8ef794.png)

A scan performs a motion controlled capture over the area that has been defined by the bounding box points set in the "Motion" section.

If the `Dry` checkbox is selected, clicking `Go` will output the expected images that will be taken for the scan.

### Log output

![image](https://user-images.githubusercontent.com/463376/221101844-1504a86d-90df-4c03-ad3c-72bd73c756f2.png)

This area provides logging output and debug information.




# Why?

Originally I needed to support specialized hardware and wasn't enthusiastic to use Java for
MicroManager, the flagship FOSS microchip software.
In general the security and lab automation communities continue to revolve around Python which makes integrating
various instruments easy into my workflows.


# Version history

## 0.0.0
* Works with custom motor driver board ("pr0ndexer")
* Job setup is done through our GUI
* In practice only works with MU800 camera
* Tested Ubuntu 16.04

## 1.0.0
 * Motor contril via LinuxCNC
 * Job setup is primarily done through Axis (LinuxCNC GUI)
 * Tested Ubuntu 16.04

## 2.0.0
* gst-toupcamsrc supported
* GUI simplified
* Job setup is entirely done through Axis (LinuxCNC GUI)
* Major configuration file format changes
* python2 => python3
* gstreamer-0.10 => gstreamer-1.0
* PyQt4 => PyQT5
* Tested Ubuntu 16.04 and 20.04

## 2.1.0
* HDR support
* First packaged release

## 2.2.0
* Enforce output file naming convention
 
## 3.0.0
* GRBL support
* Jog support (GRBL only)
* Coordiante system defaults to lower left instead of upper left
* Move imager controls from floating window into tab
* Major API restructure
* microscope.json changes and moved to microscope.j5
* planner.json major changes
* Drop obsolete "Controller" motion control API (including Axis object)
* Drop obsolete pr0ndexer motion control support
* Drop obsolete MC motion control support
* Motion HAL plugin architecture
* main_gui is now "argus"
* Options for argus output file naming
* --microscope command line argument
* Axis scalar support (gearbox workaround)
* Test suite
* Expanded CLI programs
* Expanded microscope calibration suite (namely fiducial tracking)

## 3.1.0
* Soft axis limit support
* lip-a1 real machine values
* Planner end_at option
* Add PYUSCOPE_MICROSCOPE
* Better GRBL automatic serial port selection
* Misc fixes

## 3.2.0
* Compatible with
  * gst-plugin-toupcam: v0.3.0
  * Motion HAL: GRBL
    * LinuxCNC was not removed but was not updated either
* Known bugs
  * Argus: first time connecting to GRBL may cuase failed start
    * Workaround: re-launch GUI or first run "python3 test/grbl/status.py"
  * Axis soft limit may be exceeded during long jog
    * Workaround: be careful and/or do shorter jogs
  * Auto-exposure may cause image to flicker
    * Workaround: toggle auto-exposure off then on to stabalize
* Microscope
  * lip-m1-beta support
  * ls-hvy-1: moved from LinuxCNC to GRBL
  * brainscope: moved from LinuxCNC to GRBL
* Argus
  * Add Advanced tab
    * Focus stack support (beta quality)
    * HDR support (beta quality)
  * Manual move w/ backlash compensation option
* Config improvements and changes
  * Config: add imager.source_properties_mod
    * ex: reduce exposure time to practical range)
  * Config: add imager.crop
    * Use an oversized sensor by cropping it down
  * Config: add planner.backlash_compensate
    * More aggressively backlash compensate to improve xy alignment
  * Config: backlash can be specified per axis
    * Intended to support XY vs Z
  * Config API cleaned up
* Bug fixes / usability improvements
  * Argus: update position during long moves
  * Fix image flickering during move
  * Fix image flickering caused by GUI exposure fighting auto-exposure
  * Reduce console verbosity
  * Unit test suite significantly expanded

## 4.0.0
 * Compatible with
   * gst-plugin-toupcam: v0.4.0
     * Rev for toupcamsrc automatic resolution detection
   * Motion HAL: GRBL
 * Significant code restructure (Argus, planner, motion)
 * Config API clean up
 * Argus split into smaller widgets
 * Planner V2 (now plugin based)
 * Motion HAL V2 (now plugin based)
 * XY3P algorithm (beta)
 * Batch imaging (beta)
 * Fixed GRBL Argus launch bug

## 4.0.1
  * Fix race condition on creating data dir

## 4.0.2
  * Config file rename

## 4.1.0
 * Compatible with
   * gst-plugin-toupcam: v0.4.2
   * Motion HAL: GRBL
 * Argus
   * Persist some GUI state across launches
   * Jogging fine mode, more keyboard shortcuts
   * XY2P/XY3P "Go" to coordinate buttons
   * HDR usability improvements. cs_auto.py can also ingest now
 * Homing beta support
   * Configuration: add motion.use_wcs_offsets (as opposed to MPos)
   * utils/home_run.sh wrapper script
 * Core
   * New kinematics model to significantly improve image throughput
   * Coordinates are now relative to image center (was image corner)
 * Add microscope_info.py
 * Misc bug fixes
   * Argus: crash on data dir missing
   * Argus: log crash on scan abort
   * Argus: auto exposure issues
   * Argus: planner thread stops more reliably
   * Calibration fixes
