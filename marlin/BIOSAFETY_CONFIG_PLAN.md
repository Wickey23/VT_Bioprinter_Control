# Bioprinter Marlin Configuration Plan

The stock 3D-printer configuration is **not** automatically the final bioprinter configuration.

## Motion layer

The final firmware must define and verify:

- X/Y/Z travel and homing directions
- endstop/probe behavior
- steps per unit
- conservative feedrate and acceleration limits
- machine bounds

## Syringe layer

Each independently controlled syringe needs:

- a physical stepper driver/channel
- known motor direction
- calibrated linear plunger travel
- a documented G-code mapping

Do not set `EXTRUDERS > 1` merely because the bioprinter has multiple syringes. First verify that the controller has the required independent drivers and determine how the research design expects the heads to be addressed.

## Temperature layer

Do not disable Marlin thermal safety merely to bypass missing thermistors/heaters. The final configuration should match the actual hardware architecture. If the bioprinter does not use stock thermal hardware, document the intended electronics and configure it deliberately.

## First-flash policy

The first custom build should change as little as possible from a verified machine baseline. Establish communication and safe X/Y/Z behavior first. Add syringe/multihead behavior only after base motion is confirmed.
