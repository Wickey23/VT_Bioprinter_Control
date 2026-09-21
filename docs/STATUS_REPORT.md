# Project Status Report

## Complete / prepared

- GitHub project and repository structure
- Raspberry Pi base installation script
- USB/serial printer-detection script
- software architecture documentation
- hardware-identification template
- read-only Marlin diagnostic G-code
- motor calibration procedure
- syringe calibration procedure
- wiring checklist
- commissioning checklist
- provisional Ender-5 S1 development profile
- official-Marlin retrieval script

## In development

- board-specific Marlin configuration
- Raspberry Pi printer-host selection/configuration
- multihead/syringe G-code mapping

## Blocked on physical verification

- exact research printer model
- exact controller PCB and MCU
- actual stepper-driver availability
- syringe motor wiring
- endstop/probe verification
- serial-port verification
- firmware flashing
- X/Y/Z movement testing
- syringe testing and calibration

## Definition of done

The software portion is complete when the verified hardware profile has a reproducible Marlin build, the Pi can connect over a stable serial path, X/Y/Z and every syringe actuator pass commissioning tests, calibration values are recorded, and another team member can reproduce the setup from this repository.
