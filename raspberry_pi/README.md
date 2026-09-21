# Raspberry Pi Setup

Recommended starting point: Raspberry Pi OS 64-bit.

After first boot:

```bash
chmod +x install.sh detect_printer.sh
./install.sh
sudo reboot
```

After reboot, connect the printer controller to the Pi by USB and run:

```bash
./detect_printer.sh
```

Do not install or configure a printer host against a guessed serial port. Prefer the stable `/dev/serial/by-id/...` path when available.

The host software layer will be finalized after the controller is identified and serial communication is verified.
