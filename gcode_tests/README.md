# Commissioning G-code

Start with the read-only files:

1. `00_identify.gcode` — firmware/settings report
2. `01_endstops.gcode` — endstop state
3. `02_position.gcode` — position report

Movement G-code is deliberately not pre-authorized here because axis direction, endstop polarity, travel limits, and syringe mapping are not yet verified.

After those checks, create small relative-motion tests (for example 1 mm) for one axis at a time and keep a hand at the machine's power switch.
