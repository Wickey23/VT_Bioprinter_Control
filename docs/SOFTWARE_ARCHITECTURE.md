# Software Architecture

```text
Windows development PC
  |
  | Git / VS Code / PlatformIO
  v
GitHub: VT_Bioprinter_Control
  |
  +--> Marlin firmware source/configuration
  |
  v
Raspberry Pi host
  |
  | USB serial / G-code
  v
Printer controller
  |
  | Marlin step generation
  v
X / Y / Z / syringe stepper drivers
```

## Responsibility split

### Windows development PC
- source control
- Marlin editing/building
- documentation

### Raspberry Pi
- printer host
- serial connection
- G-code/job delivery
- logs and operator interface

### Printer controller
- real-time motion
- endstop handling
- stepper control
- firmware safety behavior

The Raspberry Pi does not directly generate step pulses for the printer motors in this architecture.
