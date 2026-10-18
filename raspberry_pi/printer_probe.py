#!/usr/bin/env python3
"""
Safe Creality/Marlin probe for the VT bioprinter Raspberry Pi host.

- Auto-discovers likely serial ports, preferring CH340/CH341 (VID 1A86).
- Sends only read-only diagnostic commands.
- Does NOT home or move any axis.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass

import serial
from serial.tools import list_ports

BAUD = 115200
SAFE_COMMANDS = ("M115", "M119", "M503")


@dataclass
class Candidate:
    device: str
    description: str
    vid: int | None
    pid: int | None
    score: int


def candidates() -> list[Candidate]:
    found: list[Candidate] = []
    for p in list_ports.comports():
        text = " ".join(
            str(x or "") for x in (p.description, p.manufacturer, p.product, p.hwid)
        ).lower()
        score = 0
        if p.vid == 0x1A86:
            score += 100
        if p.pid == 0x7523:
            score += 50
        if "ch340" in text or "ch341" in text:
            score += 50
        if "usb" in text or "serial" in text:
            score += 5
        found.append(
            Candidate(
                device=p.device,
                description=p.description or "",
                vid=p.vid,
                pid=p.pid,
                score=score,
            )
        )
    return sorted(found, key=lambda c: (-c.score, c.device))


def read_response(port: serial.Serial, timeout: float = 4.0) -> list[str]:
    lines: list[str] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = port.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        lines.append(line)
        if line == "ok" or line.startswith("Error:"):
            break
    return lines


def main() -> int:
    ports = candidates()
    if not ports:
        print("No serial devices found.")
        print("Connect the Creality controller to a Pi USB port and rerun.")
        return 2

    print("Serial candidates:")
    for c in ports:
        vidpid = (
            f"{c.vid:04X}:{c.pid:04X}"
            if c.vid is not None and c.pid is not None
            else "unknown"
        )
        print(f"  {c.device:16} score={c.score:3} VID:PID={vidpid} {c.description}")

    target = ports[0]
    if target.score < 50:
        print()
        print("No high-confidence CH340 Creality serial adapter was found.")
        print("Refusing to guess which device is the printer.")
        return 3

    print()
    print(f"Using {target.device} at {BAUD} baud.")
    print("SAFE MODE: M115, M119, and M503 only. No motion/homing.")

    try:
        with serial.Serial(target.device, BAUD, timeout=0.25) as port:
            time.sleep(1.5)
            port.reset_input_buffer()

            for cmd in SAFE_COMMANDS:
                print(f"\n>>> {cmd}")
                port.write((cmd + "\n").encode("ascii"))
                port.flush()
                response = read_response(port)
                if not response:
                    print("(no response)")
                    continue
                for line in response:
                    print(line)
    except (serial.SerialException, OSError) as exc:
        print(f"Serial error: {exc}")
        return 4

    print("\nProbe complete. No motion commands were sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
