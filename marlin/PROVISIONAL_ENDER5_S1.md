# Provisional Ender-5 S1 Development Target

> **DEVELOPMENT ONLY — DO NOT FLASH UNTIL THE PHYSICAL PRINTER/BOARD IS VERIFIED.**

Current provisional target:

- Printer family: Creality Ender-5 S1
- Marlin board symbol: `BOARD_CREALITY_F401RE`
- Board noted by current Marlin: `CR4NS200141C13`
- MCU family: STM32F401RE
- Nominal build area: 220 x 220 x 280 mm
- Host architecture: Raspberry Pi -> USB serial -> printer controller -> Marlin

This profile exists so software development can continue while the research machine's exact identity is being confirmed.

## Verification gate

Before compiling/flashing for the physical research printer, confirm:

1. Printer model from chassis label.
2. Controller PCB identifier.
3. MCU marking.
4. Number of installed stepper-driver channels.
5. Which driver/channel controls each syringe actuator.
6. Endstop/probe wiring.
7. Whether stock heater/thermistor hardware is retained or removed.

If any item differs from the provisional Ender-5 S1 profile, update the hardware profile before flashing.
