# Syringe / Extrusion Calibration

Calibrate each independently driven syringe mechanism separately.

1. Confirm which controller driver maps to the syringe motor.
2. Remove/avoid material pressure during initial direction testing.
3. Command a small displacement.
4. Verify plunger direction.
5. Measure actual linear plunger travel.
6. Calculate corrected steps per unit:
   `new_steps = old_steps * commanded_travel / measured_travel`
7. Repeat until measured and commanded travel agree within the project's required tolerance.
8. Only after mechanical calibration, characterize dispensed volume versus commanded displacement for the actual syringe/nozzle/material.

Do not assume two heads share identical calibration.
