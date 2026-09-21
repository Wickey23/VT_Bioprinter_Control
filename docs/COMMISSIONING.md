# Commissioning Checklist

## Before power
- Mechanical axes move freely where appropriate.
- Wiring is secure.
- Added syringe mechanisms cannot collide during initial tests.
- Controller board and PSU voltage are identified.

## First controller connection
- Run Pi USB/serial detection.
- Record stable serial path.
- Query `M115`.
- Save existing settings with `M503`.
- Query endstops with `M119`.

## Before homing
- Confirm each endstop changes state when physically actuated.
- Confirm axis direction with tiny individual moves.
- Confirm configured travel limits match the machine.

## Firmware
- Build only for verified controller/MCU.
- Preserve a copy of the known-working firmware/configuration.
- Flash.
- Re-run identification/endstop checks.

## Bioprinter
- Verify each syringe driver independently.
- Calibrate mechanical displacement.
- Calibrate dispensed volume using the intended syringe/nozzle/material.
- Run a dry path before a material print.
