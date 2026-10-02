# DFRduino Command-Bridge Plan

## Confirmed role

The DFRduino UNO is being used as the command/control interface that sends information toward the printer. The Creality V4.2.2 board remains the controller that actually executes Marlin motion and drives the printer stepper channels.

## Current commissioning architecture

For initial testing, both devices connect to the Windows host by USB:

DFRduino UNO (COM6, 9600)
-> host bridge
-> Creality V4.2.2 (COM5, 115200)
-> Marlin
-> printer motion hardware

This USB/host bridge is deliberate for commissioning. It lets the command path be tested while the printer is not yet ready for main motor power and avoids making an unverified 5 V Arduino-UART connection to the 3.3 V printer controller.

## First proof

The DFRduino sends:

    PRINTER:M115

The host bridge forwards only an allowlist of non-motion Marlin commands:

- M105
- M115
- M119
- M503

The printer response is returned to the DFRduino. The UNO built-in LED turns on when it receives PRINTER_OK.

## Later direct link

If the final design requires DFRduino -> Creality direct TTL UART with no host in between, do not wire TX/RX yet. First identify the exact Creality UART pins and verify logic-voltage compatibility. The UNO TX is 5 V logic while the GD32 controller is a 3.3 V device, so use appropriate level shifting unless the exact printer input is verified to tolerate 5 V.

## Motion gate

Do not enable G0/G1 or homing through the bridge until:
- printer main power is ready,
- X/Y/Z motors are correctly connected,
- endstops are verified,
- movement direction is verified one axis at a time,
- emergency power-off is available.
