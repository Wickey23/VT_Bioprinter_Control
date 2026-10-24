from __future__ import annotations

import copy
import threading
import time
from typing import Any, Callable

import serial


ALLOWED_PRINT_COMMANDS = {
    "G0", "G00", "G1", "G01", "G28", "G90", "G91", "G92",
    "M82", "M83", "M104", "M109", "M140", "M190", "M302",
    "M400", "M114", "M105",
}


class PrintRunner:
    """Single-printer Marlin G-code streamer with explicit preflight gating.

    It intentionally sends only a small allowlist of motion/thermal/state
    commands used by the VT bioprinter slicer. Firmware-writing, EEPROM, SD
    card, and arbitrary M-code commands are not accepted by this runner.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pause = threading.Event()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._port: serial.Serial | None = None
        self._state: dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "state": "IDLE",
            "running": False,
            "paused": False,
            "filename": None,
            "started_at_unix": None,
            "finished_at_unix": None,
            "current_command": None,
            "current_source_line": 0,
            "current_layer": None,
            "completed_commands": 0,
            "total_commands": 0,
            "progress_percent": 0.0,
            "last_response": [],
            "error": None,
            "stop_requested": False,
            "monitoring": {
                "enabled": False,
                "available": False,
                "status": "NOT_STARTED",
                "failure_type": None,
                "message": "Camera monitoring has not started.",
                "last_checked_layer": None,
                "last_check_unix": None,
                "metrics": None,
            },
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def start(
        self,
        *,
        filename: str,
        gcode: str,
        device: str,
        baud: int,
        serial_lock: threading.Lock,
        monitor_callback: Callable[[int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        commands = self._count_commands(gcode)
        if commands <= 0:
            raise ValueError("The loaded plan contains no executable G-code commands.")

        with self._lock:
            if self._state["running"]:
                raise RuntimeError("A print is already running.")
            self._pause.clear()
            self._cancel.clear()
            self._state = self._idle_state()
            self._state.update(
                {
                    "state": "STARTING",
                    "running": True,
                    "filename": filename,
                    "started_at_unix": int(time.time()),
                    "total_commands": commands,
                    "monitoring": {
                        **self._state["monitoring"],
                        "enabled": monitor_callback is not None,
                        "status": "WAITING_FOR_LAYER" if monitor_callback else "DISABLED",
                        "message": (
                            "D405 checks will run at completed layer boundaries."
                            if monitor_callback
                            else "D405 monitoring is unavailable until camera calibration and a clean surface baseline are saved."
                        ),
                    },
                }
            )

        self._thread = threading.Thread(
            target=self._worker,
            kwargs={
                "gcode": gcode,
                "device": device,
                "baud": baud,
                "serial_lock": serial_lock,
                "monitor_callback": monitor_callback,
            },
            name="vt-bioprinter-print-runner",
            daemon=True,
        )
        self._thread.start()
        return self.status()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            if not self._state["running"]:
                raise RuntimeError("No print is running.")
            self._pause.set()
            self._state["paused"] = True
            self._state["state"] = "PAUSED"
        return self.status()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            if not self._state["running"]:
                raise RuntimeError("No print is running.")
            self._pause.clear()
            self._state["paused"] = False
            self._state["state"] = "PRINTING"
        return self.status()

    def request_stop(self) -> dict[str, Any]:
        with self._lock:
            if not self._state["running"]:
                raise RuntimeError("No print is running.")
            self._cancel.set()
            self._pause.clear()
            self._state["stop_requested"] = True
            self._state["state"] = "STOPPING"
            self._state["paused"] = False
        return self.status()

    def emergency_stop(self) -> bool:
        """Send Marlin M112 through the already-open print serial session."""
        with self._lock:
            port = self._port
            running = bool(self._state["running"])
        if not running or port is None:
            return False
        try:
            port.write(b"M112\n")
            port.flush()
        finally:
            self._cancel.set()
            self._pause.clear()
            with self._lock:
                self._state["state"] = "EMERGENCY_STOP"
                self._state["stop_requested"] = True
                self._state["paused"] = False
        return True

    @staticmethod
    def _command_code(raw: str) -> str | None:
        code = raw.split(";", 1)[0].strip()
        if not code:
            return None
        return code.split()[0].upper()

    def _count_commands(self, gcode: str) -> int:
        count = 0
        for raw in gcode.splitlines():
            command = self._command_code(raw)
            if command is None:
                continue
            if command not in ALLOWED_PRINT_COMMANDS:
                raise ValueError(f"Print plan contains blocked command {command}.")
            count += 1
        return count

    @staticmethod
    def _timeout_for(command: str) -> float:
        code = command.split()[0].upper()
        if code == "G28":
            return 90.0
        if code in {"M109", "M190"}:
            return 180.0
        if code == "M400":
            return 90.0
        return 20.0

    @staticmethod
    def _send_and_wait(port: serial.Serial, command: str, timeout: float) -> list[str]:
        port.write((command + "\n").encode("ascii"))
        port.flush()
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
            lower = line.lower()
            if lower == "ok":
                return lines
            if lower.startswith("error:") or lower.startswith("!!"):
                raise RuntimeError(f"Marlin rejected {command}: {line}")
        raise TimeoutError(f"Timed out waiting for Marlin response to {command}.")

    def _update_monitor(self, result: dict[str, Any], layer: int) -> None:
        with self._lock:
            self._state["monitoring"] = {
                "enabled": True,
                "available": bool(result.get("available")),
                "status": result.get("status", "UNKNOWN"),
                "failure_type": result.get("failure_type"),
                "message": result.get("message", ""),
                "last_checked_layer": layer,
                "last_check_unix": int(time.time()),
                "metrics": result.get("metrics"),
            }

    def _run_monitor(
        self,
        callback: Callable[[int], dict[str, Any]] | None,
        layer: int | None,
    ) -> None:
        if callback is None or layer is None or layer < 0:
            return
        try:
            result = callback(layer)
        except Exception as exc:
            result = {
                "available": False,
                "status": "MONITOR_ERROR",
                "failure_type": None,
                "message": str(exc),
                "metrics": None,
            }
        self._update_monitor(result, layer)

    def _worker(
        self,
        *,
        gcode: str,
        device: str,
        baud: int,
        serial_lock: threading.Lock,
        monitor_callback: Callable[[int], dict[str, Any]] | None,
    ) -> None:
        current_layer: int | None = None
        try:
            with serial_lock:
                with serial.Serial(device, baud, timeout=0.25, exclusive=True) as port:
                    with self._lock:
                        self._port = port
                    time.sleep(1.0)
                    port.reset_input_buffer()
                    port.write(b"\n")
                    port.flush()
                    time.sleep(0.35)
                    port.reset_input_buffer()

                    with self._lock:
                        self._state["state"] = "PRINTING"

                    for source_line, raw in enumerate(gcode.splitlines(), start=1):
                        stripped = raw.strip()

                        if stripped.upper().startswith(";LAYER:"):
                            try:
                                next_layer = int(stripped.split(":", 1)[1].strip())
                            except ValueError:
                                next_layer = current_layer
                            if current_layer is not None and next_layer != current_layer:
                                self._send_and_wait(port, "M400", 90.0)
                                self._run_monitor(monitor_callback, current_layer)
                            current_layer = next_layer
                            with self._lock:
                                self._state["current_layer"] = current_layer
                            continue

                        command = stripped.split(";", 1)[0].strip()
                        if not command:
                            continue

                        code = command.split()[0].upper()
                        if code not in ALLOWED_PRINT_COMMANDS:
                            raise RuntimeError(f"Blocked G-code command encountered during print: {code}")

                        while self._pause.is_set() and not self._cancel.is_set():
                            time.sleep(0.1)

                        if self._cancel.is_set():
                            break

                        with self._lock:
                            self._state["current_command"] = command
                            self._state["current_source_line"] = source_line

                        response = self._send_and_wait(port, command, self._timeout_for(command))

                        with self._lock:
                            self._state["last_response"] = response[-8:]
                            self._state["completed_commands"] += 1
                            total = max(1, int(self._state["total_commands"]))
                            self._state["progress_percent"] = round(
                                self._state["completed_commands"] / total * 100.0, 2
                            )

                    if self._cancel.is_set():
                        # Do not silently issue M112 here. Stop means stop sending
                        # new commands; use the dedicated emergency-stop control
                        # for an immediate firmware kill.
                        with self._lock:
                            self._state["state"] = "STOPPED"
                    else:
                        self._send_and_wait(port, "M400", 90.0)
                        self._run_monitor(monitor_callback, current_layer)
                        with self._lock:
                            self._state["state"] = "COMPLETE"
                            self._state["progress_percent"] = 100.0

        except Exception as exc:
            with self._lock:
                if self._state.get("state") != "EMERGENCY_STOP":
                    self._state["state"] = "ERROR"
                    self._state["error"] = str(exc)
        finally:
            with self._lock:
                self._port = None
                self._state["running"] = False
                self._state["paused"] = False
                self._state["current_command"] = None
                self._state["finished_at_unix"] = int(time.time())
