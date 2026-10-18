# Hardware Profile — REQUIRED BEFORE FLASHING

Filled from the physical machine inspection on 2026-10-02.

- Mechanical platform / printer variant: Custom bioprinter assembly using Creality hardware; base electronics label identifies **Ender-3 V2**
- Controller manufacturer: Creality
- Controller board revision: **V4.2.2**
- MCU marking: **GigaDevice GD32F303-series**. Package marking is partially obscured by installed wiring in the inspection photos; exact suffix still needs direct visual confirmation before first custom flash.
- Existing firmware/version (M115): **Marlin V1.0.8**, build timestamp **Jan 29 2023 08:45:37**
- Existing machine identity (M115): **Ender-3 V2**
- Existing extruder count (M115): **1**
- Existing firmware capabilities observed: EEPROM enabled; SD card enabled; thermal protection enabled; auto-leveling / Z probe not enabled
- Windows USB serial device: **USB-SERIAL CH340 (COM5)**
- Raspberry Pi host: **Raspberry Pi 4 (4 GB), hostname `vt-3dprinter`, Raspberry Pi OS 64-bit / aarch64**
- Raspberry Pi host software status (2026-10-18): **staged and verified** — Python 3.13.5, PySerial 3.5, `dialout` membership active, SSH active, Raspberry Pi Connect active
- Raspberry Pi no-printer USB baseline (2026-10-18): no `/dev/ttyUSB*` or `/dev/ttyACM*` devices present and `/dev/serial/by-id` absent, as expected with the Creality controller disconnected
- Raspberry Pi printer serial path: **pending lab connection to the Creality V4.2.2 controller**
- X/Y/Z motor wiring: **Not connected yet at time of inspection**
- X stepper driver: Board hardware code **T8** observed; driver type not yet independently verified
- Y stepper driver: Board hardware code **T8** observed; driver type not yet independently verified
- Z stepper driver: Board hardware code **T8** observed; driver type not yet independently verified
- Extruder/syringe driver(s): Board hardware code **T8** observed; final syringe-channel mapping not yet verified
- X endstop status (M119 baseline): **open**
- Y endstop status (M119 baseline): **TRIGGERED**
- Z endstop status (M119 baseline): **open**
- Endstop physical mapping / polarity verification: **Not yet completed**
- Number of independently driven syringe heads: Not yet verified
- Power supply voltage: Not yet verified from PSU output label
- AC input / rated power from printer label: 100–120 V / 200–240 V AC, 50/60 Hz, **350 W**
- Notes/photos: Physical inspection confirms Creality V4.2.2 controller. Windows direct communication to the printer controller over CH340 USB serial has been verified previously. The Raspberry Pi host is now fully staged; printer-side serial detection on the Pi is pending the next lab connection. Do not flash firmware until the remaining electrical and motion fields are verified.

## Gate

Current Marlin source includes a Creality V4.2.2 GD32F303RE target (`BOARD_CREALITY_V422_GD32_MFL`), but the first custom flash remains gated on confirming the complete MCU package marking, endstop behavior, motor wiring/directions, and syringe-head wiring.

Do not home or command axis motion until the X/Y/Z motors are correctly wired and each endstop has been physically verified with `M119`.
