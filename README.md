# VT Bioprinter Control

Software/integration workspace for the Virginia Tech Ender-5-based open-source multihead bioprinter project.

## Architecture

Raspberry Pi (host) -> USB serial -> printer controller -> Marlin -> X/Y/Z + syringe/extrusion motors.

The Raspberry Pi is the host computer. It does **not** directly drive the stepper motors.

## Project status

Software scaffolding is ready. Final firmware values must not be flashed until the exact controller board, MCU, stepper-driver arrangement, endstops, and syringe-head wiring are physically verified.

## Repository layout

- `marlin/` - Marlin configuration notes and hardware profile template
- `raspberry_pi/` - Raspberry Pi setup/verification scripts
- `gcode_tests/` - conservative commissioning tests
- `calibration/` - axis and syringe calibration procedures
- `docs/` - wiring, setup, commissioning, and safety documentation

## Commissioning order

1. Power Raspberry Pi and complete Raspberry Pi OS setup.
2. Connect printer controller by USB.
3. Run `raspberry_pi/detect_printer.sh`.
4. Record controller details in `marlin/HARDWARE_PROFILE.md`.
5. Select/build the correct Marlin target only after hardware verification.
6. Establish serial communication and run `M115`.
7. Verify endstops with `M119` before any homing.
8. Test one axis at a time using the files in `gcode_tests/`.
9. Calibrate syringe/extrusion motion.
10. Record final values and commit the verified configuration.

## Important

Do not guess motherboard/pin/driver settings. Do not home an axis until its endstop state and motor direction have been checked. Initial movement tests should be performed with tooling/syringes clear of the bed and people.
