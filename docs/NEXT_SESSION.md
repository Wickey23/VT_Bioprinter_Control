# When the Raspberry Pi Cable Arrives

1. Power the Pi.
2. Complete Raspberry Pi OS first-boot setup.
3. Clone this repository.
4. Run:
   ```bash
   cd VT_Bioprinter_Control/raspberry_pi
   chmod +x install.sh detect_printer.sh
   ./install.sh
   sudo reboot
   ```
5. Connect the Ender 5 controller by USB.
6. Run `./detect_printer.sh`.
7. Photograph the controller board and MCU.
8. Fill in `../marlin/HARDWARE_PROFILE.md`.
9. Query existing firmware with `M115`, settings with `M503`, and endstops with `M119`.
10. Only then finalize/build/flash Marlin.
