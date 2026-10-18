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
