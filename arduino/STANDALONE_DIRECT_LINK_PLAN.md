# Standalone DFRduino -> Creality Plan

## Goal

Eliminate the Windows computer and Raspberry Pi from normal operation.

Final architecture:

DFRduino UNO
-> direct TTL UART
-> Creality V4.2.2 (GD32F303)
-> Marlin
-> X / Y / Z / E motion

The computer remains useful only for development, firmware updates, logging, and troubleshooting. It is not required during normal printing once the direct link is commissioned.

## Important electrical constraint

The DFRduino UNO uses 5 V logic. The Creality GD32 controller uses 3.3 V logic.

Do NOT connect the UNO TX pin directly to a GD32 RX pin.

Use a proper 5 V <-> 3.3 V UART level shifter (preferred), or an engineered one-way level reduction on UNO TX -> Creality RX. A common ground is required.

## Creality V4.2.2 UART facts

Current Marlin pin definitions for the GD32 Creality V4 board identify:

- UART0 TX: PA9 (used by the onboard CH340 RX)
- UART0 RX: PA10 (used by the onboard CH340 TX)
- UART2 TX: PB10 (on the LCD connector)
- UART2 RX: PB11 (on the LCD connector)

The default USB path currently proven in the lab is:

PC USB -> CH340 -> UART0 -> Marlin

A direct DFRduino connection can bypass the USB/CH340 path, but the exact physical connection point must be chosen and verified before wiring.

## Recommended final implementation

Prefer an accessible secondary UART rather than soldering directly to MCU pins.

If the LCD UART is not needed, configure custom Marlin to accept host commands on the PB10/PB11 UART, then connect:

DFRduino hardware UART
-> 5 V / 3.3 V level shifter
-> Creality PB10/PB11 UART
-> Marlin SERIAL_PORT_2

This preserves the existing CH340 USB connection as a service/debug port.

If the LCD must remain connected, choose another verified UART route or redesign the host interface rather than sharing the same pins.

## DFRduino final wiring concept

- UNO D1 / TX -> level shifter -> Creality RX
- Creality TX -> level shifter (or verified 3.3 V input path) -> UNO D0 / RX
- UNO GND -> Creality GND
- Power the UNO from a proper regulated supply; do not assume an arbitrary printer pin can safely power it.

Disconnect the direct UART link while uploading a new sketch to an UNO if it interferes with the bootloader / USB serial path.

## Software protocol

The UNO can send normal Marlin G-code as newline-terminated ASCII, for example:

- M115
- M119
- M105
- G91
- G1 X1 F60

The first standalone firmware should keep the existing allowlist and state machine. Motion commands stay disabled until motor power, wiring, endstops, and direction have been commissioned.

## Commissioning order

1. Identify the exact accessible Creality UART connector/pins.
2. Confirm whether the LCD connection is required.
3. Add the 5 V <-> 3.3 V UART level shifting.
4. Build custom Marlin with the selected secondary serial port enabled.
5. Prove direct M115 round-trip with NO motor motion.
6. Prove M119 endstop reads.
7. Connect and verify X/Y/Z motors and endstops.
8. Enable only 1 mm relative moves.
9. Add syringe/extrusion command mapping.
10. Move the final command sequences/state machine into the DFRduino.
11. Remove the computer from the normal operating path.

## Current status

The temporary PC bridge has already proven the logical command path:

DFRduino -> Marlin command -> Creality response -> DFRduino

The remaining work is replacing the temporary PC transport with a verified direct UART transport.
