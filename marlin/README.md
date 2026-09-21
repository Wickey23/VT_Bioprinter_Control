# Marlin Firmware

This directory intentionally does not contain a guessed `Configuration.h`.

The exact Ender 5 controller and multihead wiring must be identified first. After that, use the matching upstream Marlin configuration as the baseline and commit the verified `Configuration.h`, `Configuration_adv.h`, and build environment here.

## Values to verify

- `MOTHERBOARD`
- serial baud rate
- X/Y/Z/E driver types
- axis directions
- endstop logic
- bed dimensions/travel limits
- steps-per-unit
- acceleration/feedrate limits
- number and mapping of syringe/extrusion steppers
- heater/temperature behavior for the actual bioprinter

See `HARDWARE_PROFILE.md`.
