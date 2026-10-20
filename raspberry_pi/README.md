# Raspberry Pi Setup

The Raspberry Pi is the high-level host for the bioprinter.

Final host architecture:

Raspberry Pi -> USB serial -> Creality V4.2.2 -> Marlin -> X/Y/Z + syringe/extrusion motion

No Arduino is required in the current design.

## First setup

Raspberry Pi OS 64-bit is recommended. SSH and Raspberry Pi Connect can remain enabled for remote maintenance.

After cloning the repository:

```bash
cd ~/VT_Bioprinter_Control
git pull
cd raspberry_pi
chmod +x complete_setup.sh
./complete_setup.sh
sudo reboot
```

The setup script installs the serial/USB tools, creates a Python virtual environment, installs PySerial, adds the user to the `dialout` group, and runs a host health check.

## At home / without the printer

The Raspberry Pi can be fully prepared without the Creality controller attached. After setup and reboot, verify:

```bash
cd ~/VT_Bioprinter_Control/raspberry_pi
source .venv/bin/activate
python --version
python -c "import serial; print(serial.__version__)"
```

## In the lab

Connect only the Creality controller to a Raspberry Pi USB port, then run:

```bash
cd ~/VT_Bioprinter_Control/raspberry_pi
./detect_printer.sh
./.venv/bin/python printer_probe.py
```

`printer_probe.py` prefers the known CH340/CH341 USB-serial interface and refuses to guess when it cannot identify the printer confidently. It sends only:

- `M115` — firmware identity
- `M119` — endstop state
- `M503` — current configuration

It does not send motion or homing commands.

## Safety gate

Do not enable motion until:
- printer main power is ready,
- X/Y/Z motors are connected correctly,
- all endstops are physically verified,
- axis directions are checked one at a time,
- an immediate power-off method is available.

Prefer the stable `/dev/serial/by-id/...` path when available for the final service configuration.


## Web controller

A browser-based controller is available in `raspberry_pi/webapp/`. It is designed to run continuously on the Pi and currently provides:

- Raspberry Pi health/status
- printer USB/CH340 detection
- read-only Marlin diagnostics (`M105`, `M114`, `M115`, `M119`, `M503`)
- commissioning lock for all motion/homing/extrusion controls
- Wi-Fi status, scanning, switching, and saved-network management
- responsive phone/tablet/laptop interface
- access-key protection

Install it after the base Pi setup:

```bash
cd ~/VT_Bioprinter_Control
git pull
cd raspberry_pi
chmod +x install_webapp.sh
./install_webapp.sh
```

The installer prints the controller access key and enables the service at boot. On the same network, open:

```text
http://vt-3dprinter.local:8080
```

or use the IPv4 address printed by the installer.

Changing Wi-Fi can interrupt the current browser session while the Pi obtains a new address. Reopen the hostname or new IP after the network transition.

The web controller is intended for a trusted local research network or trusted remote access. Do not expose port 8080 directly to the public internet.


## Direct-access setup hotspot

The controller can also broadcast its own Wi-Fi network so a phone, tablet, or laptop can reach the printer without sharing an existing Wi-Fi network.

Default direct-access settings:

- SSID: `VT-Bioprinter-Setup`
- Wi-Fi password: `bioprinter`
- Controller URL: `http://10.42.0.1:8080`
- Web-controller access key: `enter`

Behavior:

1. On a normal boot, the Pi first gets a chance to connect to a saved Wi-Fi network.
2. If no Wi-Fi connection is active after about 25 seconds, the fallback service activates `VT-Bioprinter-Setup`.
3. A user can connect directly to that SSID and open `http://10.42.0.1:8080`.
4. From the Network page, the user can scan for normal Wi-Fi or manually enter an SSID and password.
5. When a normal Wi-Fi connection is requested from hotspot mode, the hotspot is stopped and the Pi attempts to join the requested network.
6. If that connection attempt fails, the helper restores the setup hotspot.

The Network page also includes a manual **Start setup hotspot** control. Starting it intentionally disconnects the Pi from its current Wi-Fi because the built-in Wi-Fi adapter is being switched into access-point mode.

This hotspot is for local/direct controller access. It should not be treated as an internet-facing management interface.


## Intel RealSense D405 sensing

The web controller includes a Camera page for the lab's Intel RealSense D405. USB presence is detected immediately with `lsusb`. Depth-frame capture requires librealsense and its Python bindings.

Connect the D405 to a blue USB 3 port on the Raspberry Pi, then install the sensing stack:

```bash
cd ~/VT_Bioprinter_Control
git pull
cd raspberry_pi
bash install_realsense.sh
```

The RealSense source build is intentionally separate from the normal web-controller install because it can take substantially longer on a Raspberry Pi 4.

After installation, the Camera page can:
- identify the RealSense device
- report model / serial / firmware when available
- capture a colorized depth frame
- report center-pixel distance
- report median/min/max depth over a 21×21 center ROI

The initial depth measurements are commissioning data only. They are not yet calibrated as nozzle-to-bed or layer-height measurements.

## Motion commissioning controls

The Printer page now includes guarded 0.1 mm and 1.0 mm X/Y/Z jog tests. Motion stays locked until the operator explicitly confirms:
- X/Y/Z motors are connected correctly
- X/Y/Z endstop states were physically verified with `M119`
- the workspace is clear
- printer main power is ready
- a physical power-off / emergency stop is immediately reachable

Homing remains intentionally unavailable during this commissioning stage. Syringe motion remains locked until the syringe driver mapping and calibration are verified.

The dashboard also provides an `M112` software emergency-stop button. A software stop is not a substitute for cutting printer power in a hardware emergency.


## Live D405 camera feed

The Camera page can now run one persistent D405 pipeline for both RGB video and depth sensing.

- RGB browser view: 640x480, target 15 FPS.
- Depth stream: 848x480, target 15 FPS.
- The browser requests the latest JPEG frames with the normal controller authentication header.
- Depth measurements and depth snapshots reuse the same running camera pipeline, avoiding multiple processes fighting over the D405.
- Leaving the Camera page stops the live feed to reduce Raspberry Pi load.
- The live feed is for monitoring/commissioning. Closed-loop printer decisions should use validated depth/feature measurements rather than raw RGB pixels alone.

Use **Start live feed** on the Camera page to begin the stream and **Stop live feed** to release the D405 pipeline.


## Camera-to-printer calibration and intelligent monitor

The controller now includes a **Calibration** workspace and an **Observe-mode Monitor**.

### Calibration workflow

1. Rigidly mount the D405. Moving the camera after calibration invalidates the transform.
2. Open **Calibration** and capture a frame.
3. Verify the physical usable bed dimensions shown in the form.
4. Click the four bed corners in this printer-coordinate order:
   - front-left
   - front-right
   - rear-right
   - rear-left
5. Each click samples aligned D405 depth and deprojects the pixel into a 3D camera-space point.
6. **Solve & save calibration** performs a four-point rigid Kabsch fit from camera-space coordinates to printer-space X/Y/Z.
7. The profile stores:
   - D405 serial/model
   - camera intrinsics
   - bed dimensions and image points
   - 3×3 rotation matrix
   - translation vector
   - per-corner fit errors and RMS error
8. After the bed transform is valid, use **Mark nozzle tip on image** to save a syringe/nozzle reference point in printer coordinates.

Calibration profiles are stored outside the repository under the VT Bioprinter config directory, normally:

```text
~/.config/vt-bioprinter/calibration/active.json
```

### Surface map

**Analyze surface** samples a grid across the calibrated bed polygon using one synchronized live depth frame. Each valid sample is transformed into printer coordinates. The controller reports mean Z, RMS Z error, minimum/maximum Z, peak-to-peak variation, and displays a simple deviation overlay.

This is a measurement/commissioning feature. Treat the result as research data until the calibration error has been independently checked against physical measurements.

### Monitor workspace

The **Monitor** page is currently locked to **OBSERVE** behavior:
- live D405 image
- calibrated bed outline
- saved nozzle marker
- click-to-query printer X/Y/Z coordinates
- optional surface deviation overlay
- expected G-code extrusion-path overlay when a plan is loaded

It does not autonomously move, pause, or correct the printer.

## G-code print plan

The **Print** page can load a local G-code file in the browser. The backend parses:
- G0/G1 motion
- absolute/relative XYZ modes
- absolute/relative extrusion modes
- G92 position resets
- feed rate
- estimated layers
- extrusion-positive path segments
- XYZ bounds and path lengths

Loading G-code **does not execute it**.

When a valid D405 calibration profile exists, the controller applies the inverse camera/printer transform and stored camera intrinsics to project expected extruding G-code segments into the Monitor camera image. This is the first expected-vs-observed layer for future extrusion-quality analysis.


## Reference surface and deposition-height comparison

After camera-to-printer calibration, the Calibration page can save a clean **reference surface**. The baseline stores a synchronized grid of printer-space Z measurements across the calibrated bed region.

Later surface scans use the same grid and report:
- current printer-space Z
- baseline Z
- per-sample ΔZ
- mean/RMS ΔZ
- maximum/minimum ΔZ
- positive-height sample count

This creates the first depth-based deposition-height measurement layer. The overlay uses ΔZ when a compatible baseline exists. It is still an observe-only research measurement and must be physically validated before it is used for automatic correction.

## Experiment recording

The **Experiments** page creates research sessions under:

```text
~/.local/share/vt-bioprinter/experiments/
```

Each session records:
- start/end time
- OBSERVE operating mode
- calibration metadata
- active G-code plan metadata
- coordinate-probe events
- surface-scan summary events
- reference-baseline events
- synchronized RGB + depth JPEG snapshots
- center depth measurement associated with each snapshot

Experiment data is intentionally stored outside the Git repository.

The current controller does **not** automatically move, pause, or correct the printer based on camera data. The sensing/quality pipeline must first be experimentally validated.


## Observe-only nozzle tracking

When the nozzle/syringe tip is marked during calibration, the controller now stores a small grayscale visual template around the selected tip. In **Monitor**, an experimental normalized-template-correlation tracker can:

- search around the projected Marlin M114 position when available
- fall back to the saved tip location
- recover with a coarse whole-frame search if the local match is weak
- report visual similarity confidence
- sample D405 depth at the tracked image location
- transform the tracked tip into printer X/Y/Z coordinates

This tracker is experimental. Its confidence is a visual similarity score, not a calibrated probability. It is OBSERVE-only and is never used to move the printer.

## Final-surface quality analytics

The **Analytics** page combines:

- saved clean reference surface
- current D405 depth surface
- camera-to-printer transform
- loaded G-code extrusion path
- user-selected path radius
- minimum detected deposition height
- user-selected height tolerance

The controller classifies coarse sampled points as:
- within tolerance
- too low
- too high
- missing expected deposition
- excess/off-path deposition
- background

It reports path coverage, within-tolerance percentage, missing/excess sample counts, mean absolute height error, RMS height error, and an informational NORMAL/WARNING/FAULT advisory.

The advisory is OBSERVE-only. It does not pause, stop, or correct the printer.

## Continuous integration

The repository includes `.github/workflows/controller-ci.yml`, which checks:
- Python syntax for the controller modules
- offline calibration/G-code/quality self-tests
- browser JavaScript syntax

The offline checks can also be run manually on the Pi:

```bash
cd ~/VT_Bioprinter_Control/raspberry_pi
./.venv/bin/python controller_self_test.py
```
