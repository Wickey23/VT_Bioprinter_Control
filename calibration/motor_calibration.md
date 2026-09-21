# Axis Motor Calibration

For each axis:

1. Verify endstop state before homing.
2. Verify motor direction using a very small commanded move.
3. Command a known safe distance.
4. Measure actual travel.
5. Calculate:

`new_steps_per_mm = old_steps_per_mm * commanded_distance / measured_distance`

6. Repeat measurement and record the final value.
7. Only then establish normal travel/feedrate limits.

Record every change in version control.
