#!/usr/bin/env python3
"""
VT Bioprinter - Arduino -> Marlin serial bridge

Current safe commissioning mode:
  DFRduino UNO (COM6 @ 9600)
      -> this host bridge
      -> Creality V4.2.2 / Marlin (COM5 @ 115200)

Only non-motion diagnostic commands are accepted by default.
This lets us prove the command path before the printer is ready
for main motor power.

Install:
    py -m pip install pyserial

Run:
    py host_bridge/arduino_to_marlin_bridge.py --arduino COM6 --printer COM5
"""

import argparse
import time
import serial

SAFE_COMMANDS = {
    "M105",  # temperatures
    "M115",  # firmware info
    "M119",  # endstop status
    "M503",  # report settings
}


def read_marlin_response(port: serial.Serial, timeout_s: float = 3.0) -> list[str]:
    lines: list[str] = []
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        raw = port.readline()
        if not raw:
            continue

        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            continue

        lines.append(text)
        if text == "ok" or text.startswith("Error:"):
            break

    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arduino", default="COM6")
    parser.add_argument("--printer", default="COM5")
    parser.add_argument("--arduino-baud", type=int, default=9600)
    parser.add_argument("--printer-baud", type=int, default=115200)
    args = parser.parse_args()

    print(f"Opening Arduino {args.arduino} @ {args.arduino_baud}")
    print(f"Opening printer {args.printer} @ {args.printer_baud}")
    print("SAFE MODE: only M105, M115, M119, M503 will be forwarded.")

    with serial.Serial(args.printer, args.printer_baud, timeout=0.25) as printer:
        time.sleep(1.0)
        printer.reset_input_buffer()

        with serial.Serial(args.arduino, args.arduino_baud, timeout=0.25) as arduino:
            time.sleep(2.0)
            arduino.reset_input_buffer()

            print("Bridge ready.")

            while True:
                raw = arduino.readline()
                if not raw:
                    continue

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                print(f"Arduino -> {line}")

                if not line.startswith("PRINTER:"):
                    continue

                command = line.split(":", 1)[1].strip().upper()

                if command not in SAFE_COMMANDS:
                    msg = f"PRINTER_REJECTED:{command}"
                    print(msg)
                    arduino.write((msg + "\n").encode())
                    continue

                printer.reset_input_buffer()
                printer.write((command + "\n").encode())
                printer.flush()

                response = read_marlin_response(printer)

                for response_line in response:
                    print(f"Printer <- {response_line}")
                    arduino.write(
                        ("PRINTER_RESPONSE:" + response_line + "\n").encode()
                    )

                if response and response[-1] == "ok":
                    arduino.write(b"PRINTER_OK\n")
                else:
                    arduino.write(b"PRINTER_TIMEOUT_OR_ERROR\n")


if __name__ == "__main__":
    raise SystemExit(main())
