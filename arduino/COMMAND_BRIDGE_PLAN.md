# DFRduino Command-Bridge Plan

## Confirmed role

The DFRduino UNO is being used as the command/control interface that sends information toward the printer. The Creality V4.2.2 board remains the controller that actually executes Marlin motion and drives the printer stepper channels.

## Current commissioning architecture

For initial testing, both devices connect to the Windows host by USB:

DFRduino UNO (COM6, 9600)
-> Windows PowerShell bridge
-> Creality V4.2.2 (COM7, 115200)
-> Marlin
-> printer motion hardware

This USB/host bridge is deliberate for commissioning. It lets the command path be tested while the printer is not yet ready for main motor power and avoids making an unverified 5 V Arduino-UART connection to the 3.3 V printer controller.

## Verified round-trip — 2026-10-02

The complete communication path was verified successfully in the lab.

Observed sequence:

    Arduino -> ARDUINO_READY
    Arduino -> PRINTER:M115
    Sending M115 to Marlin...
    Printer <- FIRMWARE_NAME:Marlin V1.0.8 ...
    Printer <- ok
    ROUND-TRIP SUCCESS

Verified components:

- DFRduino UNO command generation
- DFRduino USB serial on COM6
- Windows bridge
- Creality V4.2.2 USB serial on COM7
- Marlin command execution
- Marlin response returned through the bridge
- PRINTER_OK acknowledgement returned to the DFRduino

The split output around `Cap:AUTOREPORT_TEMP:1` seen in the PowerShell log was caused by serial chunking in the bridge display and does not indicate a Marlin firmware fault.

## Safe diagnostic commands

The commissioning bridge currently permits only:

- M105
- M115
- M119
- M503

No motion or homing commands are enabled at this stage.

## Later direct link

If the final design requires DFRduino -> Creality direct TTL UART with no host in between, do not wire TX/RX yet. First identify the exact Creality UART pins and verify logic-voltage compatibility. The UNO TX is 5 V logic while the GD32 controller is a 3.3 V device, so use appropriate level shifting unless the exact printer input is verified to tolerate 5 V.

## Motion gate

Do not enable G0/G1 or homing through the bridge until:
- printer main power is ready,
- X/Y/Z motors are correctly connected,
- endstops are verified,
- movement direction is verified one axis at a time,
- emergency power-off is available.
