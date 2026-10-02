# DFRduino UNO Integration

## Verified lab baseline — 2026-10-02

- Board: DFRobot DFRduino UNO V3.0 (Arduino Uno compatible)
- MCU: ATmega328P
- Windows serial port during lab verification: COM6
- Arduino IDE target: Arduino AVR Boards -> Arduino Uno
- Serial test baud: 9600
- Upload and execution: verified
- Serial output verified:
  - VT Bioprinter DFRduino OK
  - Controller alive

The block/square characters seen immediately before the valid serial text are consistent with reset/startup bytes being interpreted at the wrong moment/baud and are not considered a failure when the subsequent 9600-baud output is correct.

## Safety / integration status

The DFRduino is verified as a standalone controller only. Do not connect unknown motor-driver, shield, syringe, or Creality-controller wiring until the attached hardware and pin mapping are identified.

## Next steps

1. Identify any motor driver or shield connected to the DFRduino.
2. Map every Arduino pin used by that hardware.
3. Record motor supply voltage separately from USB logic power.
4. Add conservative single-channel motor tests.
5. Define the serial command protocol between the host computer and DFRduino.
