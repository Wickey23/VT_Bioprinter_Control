#!/usr/bin/env python3
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import serial
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from serial.tools import list_ports

from webapp.calibration import (
    analyze_surface,
    clear_profile,
    load_profile,
    save_nozzle_reference,
    save_surface_baseline,
    solve_bed_calibration,
    transform_camera_point,
)
from webapp.experiments import (
    active_experiment,
    list_experiments,
    log_event,
    save_snapshot,
    start_experiment,
    stop_experiment,
)
from webapp.print_plan import (
    clear_plan,
    load_plan,
    parse_gcode,
    printer_to_camera,
    project_camera_point,
    project_plan,
    slice_stl_to_syringe_gcode,
)
from webapp.quality import analyze_final_surface_quality
from webapp.failure_detection import evaluate_layer, save_observation, save_training_frames
from webapp.print_runner import PrintRunner
from webapp.realsense import (
    capture_color_jpeg,
    capture_depth_jpeg,
    capture_live_template,
    capture_depth_sample,
    latest_live_rgb,
    live_camera_status,
    sample_live_pixel,
    sample_live_pixels,
    start_live_camera,
    stop_live_camera,
    usb_camera_status,
)
from webapp.vision import track_template

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CONFIG_DIR = Path(os.environ.get("VT_BIOPRINTER_CONFIG_DIR", Path.home() / ".config" / "vt-bioprinter"))
TOKEN_FILE = CONFIG_DIR / "token"
COMMISSION_FILE = CONFIG_DIR / "commissioning.json"
NETWORK_HELPER = Path(os.environ.get("VT_BIOPRINTER_NETWORK_HELPER", "/usr/local/sbin/vt-bioprinter-network"))
REMOTE_URL_FILE = Path(os.environ.get("VT_BIOPRINTER_REMOTE_URL_FILE", "/etc/vt-bioprinter/remote-url"))

BAUD = 115200
SAFE_COMMANDS = {"M105", "M114", "M115", "M119", "M503"}
SERIAL_LOCK = threading.Lock()
PRINT_RUNNER = PrintRunner()

# Conservative Ender-3 V2 motion envelope. Large jogs are only enabled after
# this controller has completed a successful home sequence in the current
# service session, so M114 coordinates have a known reference.
AXIS_LIMITS_MM = {"X": (0.0, 220.0), "Y": (0.0, 220.0), "Z": (0.0, 250.0)}
LARGE_JOG_STEPS_MM = {5.0, 10.0, 25.0}
COMMISSIONING_JOG_STEPS_MM = {0.1, 1.0}
MOTION_REFERENCE = {"homed": False, "centered": False}

HOTSPOT_NAME = "VT-Bioprinter-Setup"
HOTSPOT_PASSWORD = "bioprinter"
HOTSPOT_IP = "10.42.0.1"
HOTSPOT_URL = f"http://{HOTSPOT_IP}:8080"

app = FastAPI(title="VT Bioprinter Controller", version="0.4.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class WifiConnectRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=256)


class WifiForgetRequest(BaseModel):
    connection: str = Field(min_length=1, max_length=256)


class WifiPriorityRequest(BaseModel):
    connection: str = Field(min_length=1, max_length=256)
    priority: int = Field(ge=-999, le=999)


class WifiActivateRequest(BaseModel):
    connection: str = Field(min_length=1, max_length=256)


class SafeCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=64)


class CommissioningRequest(BaseModel):
    motors_connected: bool
    endstops_verified: bool
    workspace_clear: bool
    main_power_ready: bool
    physical_stop_ready: bool


class JogRequest(BaseModel):
    axis: str = Field(pattern="^[XYZ]$")
    distance_mm: float
    feed_mm_min: int = Field(default=300, ge=60, le=1200)


class CalibrationCorner(BaseModel):
    u: float
    v: float
    depth_m: float
    camera_xyz_m: list[float]


class CalibrationSolveRequest(BaseModel):
    points: list[CalibrationCorner]
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0
    width_mm: float = Field(gt=0, le=1000)
    depth_mm: float = Field(gt=0, le=1000)
    frame_width: int = Field(gt=0, le=4096)
    frame_height: int = Field(gt=0, le=4096)


class PixelPointRequest(BaseModel):
    u: float
    v: float


class SurfaceAnalysisRequest(BaseModel):
    columns: int = Field(default=12, ge=4, le=30)
    rows: int = Field(default=9, ge=4, le=30)


class PlanLoadRequest(BaseModel):
    filename: str = Field(default="print.gcode", min_length=1, max_length=256)
    text: str = Field(min_length=1)


class SlicerRequest(BaseModel):
    filename: str = Field(default="model.stl", min_length=1, max_length=256)
    stl_base64: str = Field(min_length=4, max_length=20_000_000)
    layer_height_mm: float = Field(default=0.30, ge=0.05, le=5.0)
    bead_width_mm: float = Field(default=0.80, ge=0.05, le=10.0)
    infill_percent: float = Field(default=20.0, ge=0.0, le=100.0)
    syringe_diameter_mm: float = Field(default=14.5, ge=1.0, le=50.0)
    syringe_capacity_ml: float = Field(default=10.0, ge=0.1, le=100.0)
    needle_inner_diameter_mm: float = Field(default=0.60, ge=0.05, le=5.0)
    alginate_percent_wv: float = Field(default=3.0, ge=0.1, le=20.0)
    calcium_chloride_mM: float = Field(default=80.0, ge=0.0, le=2000.0)
    crosslink_mode: str = Field(default="post_print", pattern="^(post_print|support_bath|manual)$")
    support_strategy: str = Field(default="self_supporting", pattern="^(self_supporting|support_bath|manual_scaffold)$")
    temperature_mode: str = Field(default="ambient", pattern="^(ambient|heated_bed)$")
    bed_temperature_c: float = Field(default=0.0, ge=0.0, le=60.0)
    extrusion_multiplier: float = Field(default=1.0, ge=0.1, le=5.0)
    travel_lift_mm: float = Field(default=1.0, ge=0.0, le=10.0)
    print_feed_mm_min: int = Field(default=240, ge=30, le=3000)
    travel_feed_mm_min: int = Field(default=1200, ge=60, le=6000)
    e_steps_calibrated: bool = False
    motor_direction_verified: bool = False


class ExperimentStartRequest(BaseModel):
    name: str = Field(default="Bioprinter experiment", min_length=1, max_length=128)


class QualityAnalysisRequest(BaseModel):
    columns: int = Field(default=14, ge=6, le=30)
    rows: int = Field(default=10, ge=6, le=30)
    path_radius_mm: float = Field(default=2.0, gt=0, le=20)
    min_deposition_height_mm: float = Field(default=0.10, ge=0, le=20)
    height_tolerance_mm: float = Field(default=0.50, gt=0, le=20)


class PrintStartRequest(BaseModel):
    confirm_physical_stop_available: bool = False


def load_token() -> str:
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""


def require_token(x_bioprinter_token: str | None = Header(default=None)) -> None:
    expected = load_token()
    if not expected:
        raise HTTPException(status_code=503, detail="Controller access token is not configured.")
    if not x_bioprinter_token or not secrets.compare_digest(x_bioprinter_token, expected):
        raise HTTPException(status_code=401, detail="Invalid controller access key.")


def run_command(args: list[str], timeout: float = 10.0, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def nmcli_lines(fields: str, *args: str) -> list[str]:
    proc = run_command(["nmcli", "-t", "--escape", "yes", "-f", fields, *args], timeout=15)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "nmcli failed")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def split_nmcli(line: str, maxsplit: int = -1) -> list[str]:
    out: list[str] = []
    buf: list[str] = []
    escaped = False
    splits = 0
    for ch in line:
        if escaped:
            buf.append(ch)
            escaped = False
            continue
        if ch == "\\":
            escaped = True
            continue
        if ch == ":" and (maxsplit < 0 or splits < maxsplit):
            out.append("".join(buf))
            buf = []
            splits += 1
        else:
            buf.append(ch)
    if escaped:
        buf.append("\\")
    out.append("".join(buf))
    return out


def active_wifi_connection() -> str | None:
    try:
        for line in nmcli_lines("NAME,TYPE", "connection", "show", "--active"):
            parts = split_nmcli(line, 1)
            if len(parts) == 2 and parts[1] == "802-11-wireless":
                return parts[0]
    except Exception:
        pass
    return None


def wlan_ipv4() -> str | None:
    proc = run_command(["nmcli", "-g", "IP4.ADDRESS", "device", "show", "wlan0"], timeout=5)
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        value = line.strip()
        if "." in value:
            return value.split("/", 1)[0]
    return None


def network_status() -> dict[str, Any]:
    connection_name = active_wifi_connection()
    hotspot_active = connection_name == HOTSPOT_NAME

    ssid = HOTSPOT_NAME if hotspot_active else None
    signal = None
    security = "WPA2" if hotspot_active else None

    if not hotspot_active:
        try:
            for line in nmcli_lines("ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", "wlan0"):
                parts = split_nmcli(line, 3)
                if len(parts) >= 4 and parts[0] == "yes":
                    ssid, signal, security = parts[1], parts[2], parts[3]
                    break
        except Exception:
            pass

    ip_address = wlan_ipv4()
    if hotspot_active:
        ip_address = HOTSPOT_IP

    return {
        "connected": bool(connection_name),
        "ssid": ssid or connection_name,
        "connection_name": connection_name,
        "signal": int(signal) if signal and signal.isdigit() else None,
        "security": security,
        "ip_address": ip_address,
        "hotspot_active": hotspot_active,
        "mode": "hotspot" if hotspot_active else ("wifi" if connection_name else "offline"),
    }


def scan_networks() -> list[dict[str, Any]]:
    try:
        lines = nmcli_lines("SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list", "--rescan", "yes", "ifname", "wlan0")
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Wi-Fi scan failed: {exc}. If the setup hotspot is active, you can still enter an SSID manually.",
        )

    seen: dict[str, dict[str, Any]] = {}
    for line in lines:
        parts = split_nmcli(line, 3)
        if len(parts) < 4:
            continue
        ssid, signal, security, in_use = parts
        if not ssid or ssid == HOTSPOT_NAME:
            continue
        item = {
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else 0,
            "security": security or "Open",
            "in_use": in_use == "*",
        }
        old = seen.get(ssid)
        if old is None or item["signal"] > old["signal"]:
            seen[ssid] = item
    return sorted(seen.values(), key=lambda x: (not x["in_use"], -x["signal"], x["ssid"].lower()))


def run_network_helper(action: str, argument: str | None = None, input_text: str | None = None, timeout: float = 45.0) -> subprocess.CompletedProcess[str]:
    if not NETWORK_HELPER.exists():
        raise HTTPException(status_code=503, detail="Network helper is not installed.")
    args = ["sudo", "-n", str(NETWORK_HELPER), action]
    if argument is not None:
        args.append(argument)
    return run_command(args, timeout=timeout, input_text=input_text)


def printer_candidates() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for p in list_ports.comports():
        text = " ".join(str(x or "") for x in (p.description, p.manufacturer, p.product, p.hwid)).lower()
        score = 0
        if p.vid == 0x1A86:
            score += 100
        if p.pid == 0x7523:
            score += 50
        if "ch340" in text or "ch341" in text:
            score += 50
        if "usb" in text or "serial" in text:
            score += 5
        results.append(
            {
                "device": p.device,
                "description": p.description or "",
                "vid": f"{p.vid:04X}" if p.vid is not None else None,
                "pid": f"{p.pid:04X}" if p.pid is not None else None,
                "score": score,
            }
        )
    return sorted(results, key=lambda x: (-x["score"], x["device"]))


def chosen_printer() -> dict[str, Any] | None:
    ports = printer_candidates()
    if not ports or ports[0]["score"] < 50:
        return None
    return ports[0]


def send_safe_command(command: str) -> dict[str, Any]:
    normalized = command.strip().upper()
    if normalized not in SAFE_COMMANDS:
        raise HTTPException(status_code=423, detail="Command blocked while the printer is in commissioning lock mode.")

    target = chosen_printer()
    if not target:
        raise HTTPException(status_code=409, detail="No high-confidence Creality/CH340 serial interface is connected.")

    lines: list[str] = []
    try:
        with SERIAL_LOCK:
            with serial.Serial(target["device"], BAUD, timeout=0.25, exclusive=True) as port:
                # Synchronize to a clean Marlin command boundary. CH340-connected
                # Creality boards can occasionally have a partial garbage line in
                # the firmware RX buffer immediately after the port is opened.
                time.sleep(1.0)
                port.reset_input_buffer()
                port.write(b"\n")
                port.flush()
                time.sleep(0.35)
                port.reset_input_buffer()
                port.write((normalized + "\n").encode("ascii"))
                port.flush()
                deadline = time.monotonic() + 4.0
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
    except (serial.SerialException, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Serial error: {exc}")

    return {"command": normalized, "device": target["device"], "response": lines}



def parse_m114_response(lines: list[str]) -> dict[str, float]:
    text = " ".join(lines)
    result: dict[str, float] = {}
    for axis in ("X", "Y", "Z", "E"):
        match = re.search(rf"(?:^|\\s){axis}:\\s*(-?\\d+(?:\\.\\d+)?)", text)
        if match:
            result[axis.lower()] = float(match.group(1))
    if not all(axis in result for axis in ("x", "y", "z")):
        raise ValueError("Could not parse X/Y/Z from Marlin M114 response.")
    return result


def read_commissioning() -> dict[str, Any]:
    default = {
        "motors_connected": False,
        "endstops_verified": False,
        "workspace_clear": False,
        "main_power_ready": False,
        "physical_stop_ready": False,
        "unlocked": False,
    }
    try:
        data = json.loads(COMMISSION_FILE.read_text(encoding="utf-8"))
        default.update({k: bool(data.get(k, False)) for k in default})
    except Exception:
        pass
    default["unlocked"] = all(
        default[key]
        for key in (
            "motors_connected",
            "endstops_verified",
            "workspace_clear",
            "main_power_ready",
            "physical_stop_ready",
        )
    )
    return default


def save_commissioning(payload: CommissioningRequest) -> dict[str, Any]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = payload.model_dump()
    data["unlocked"] = all(data.values())
    if not data["unlocked"]:
        MOTION_REFERENCE["homed"] = False
        MOTION_REFERENCE["centered"] = False
    COMMISSION_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def _read_until_ok(port: serial.Serial, command: str, timeout_s: float = 5.0) -> list[str]:
    port.write((command + "\n").encode("ascii"))
    port.flush()
    lines: list[str] = []
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        raw = port.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        lines.append(line)
        if line == "ok" or line.startswith("Error:"):
            return lines
    raise HTTPException(status_code=504, detail=f"Timed out waiting for Marlin response to {command}.")


def _parse_endstops(lines: list[str]) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in lines:
        match = re.match(r"^(x_min|y_min|z_min):\s*(open|TRIGGERED)$", line, re.IGNORECASE)
        if match:
            states[match.group(1).lower()] = match.group(2).upper()
    return states


def home_and_center() -> dict[str, Any]:
    state = read_commissioning()
    if not state["unlocked"]:
        raise HTTPException(status_code=423, detail="Motion is locked until the commissioning checklist is complete.")

    target = chosen_printer()
    if not target:
        raise HTTPException(status_code=409, detail="No high-confidence Creality/CH340 serial interface is connected.")

    responses: list[str] = []
    try:
        with SERIAL_LOCK:
            with serial.Serial(target["device"], BAUD, timeout=0.25, exclusive=True) as port:
                time.sleep(1.0)
                port.reset_input_buffer()
                port.write(b"\n")
                port.flush()
                time.sleep(0.35)
                port.reset_input_buffer()

                # Home against the verified X/Y/Z minimum endstops, wait for the
                # planner, then lift away from Z=0 before moving to bed center.
                sequence = [
                    ("G28", 60.0),
                    ("M400", 15.0),
                    ("G90", 5.0),
                    ("G0 Z10 F300", 15.0),
                    ("M400", 15.0),
                    ("G0 X110 Y110 F1200", 30.0),
                    ("M400", 30.0),
                    ("M114", 5.0),
                ]
                last_lines: list[str] = []
                for command, timeout_s in sequence:
                    lines = _read_until_ok(port, command, timeout_s)
                    responses.extend(f"{command}: {line}" for line in lines)
                    last_lines = lines
                    if any(line.startswith("Error:") for line in lines):
                        raise HTTPException(status_code=409, detail=f"Marlin reported an error during {command}.")

                try:
                    position = parse_m114_response(last_lines)
                except Exception:
                    position = {"x": 110.0, "y": 110.0, "z": 10.0}

    except HTTPException:
        MOTION_REFERENCE["homed"] = False
        MOTION_REFERENCE["centered"] = False
        raise
    except (serial.SerialException, OSError) as exc:
        MOTION_REFERENCE["homed"] = False
        MOTION_REFERENCE["centered"] = False
        raise HTTPException(status_code=500, detail=f"Serial error: {exc}")

    MOTION_REFERENCE["homed"] = True
    MOTION_REFERENCE["centered"] = True
    return {
        "ok": True,
        "homed": True,
        "centered": True,
        "position_mm": position,
        "limits_mm": AXIS_LIMITS_MM,
        "response": responses,
    }


def serial_motion(axis: str, distance_mm: float, feed_mm_min: int) -> dict[str, Any]:
    state = read_commissioning()
    if not state["unlocked"]:
        raise HTTPException(status_code=423, detail="Motion is locked until the commissioning checklist is complete.")

    step = abs(float(distance_mm))
    allowed_steps = COMMISSIONING_JOG_STEPS_MM | LARGE_JOG_STEPS_MM
    if step not in allowed_steps:
        raise HTTPException(status_code=400, detail="Jog step must be 0.1, 1, 5, 10, or 25 mm.")
    if step in LARGE_JOG_STEPS_MM and not MOTION_REFERENCE["homed"]:
        raise HTTPException(
            status_code=409,
            detail="Large jogs require Home + Center first so software travel limits have a known coordinate reference.",
        )

    target = chosen_printer()
    if not target:
        raise HTTPException(status_code=409, detail="No high-confidence Creality/CH340 serial interface is connected.")

    responses: list[str] = []
    endstops: dict[str, str] = {}
    position_before: dict[str, float] | None = None
    position_after: dict[str, float] | None = None

    try:
        with SERIAL_LOCK:
            with serial.Serial(target["device"], BAUD, timeout=0.25, exclusive=True) as port:
                time.sleep(1.0)
                port.reset_input_buffer()
                port.write(b"\n")
                port.flush()
                time.sleep(0.35)
                port.reset_input_buffer()

                # Always inspect physical minimum endstops immediately before
                # motion. If a minimum switch is already active, never command
                # farther into that switch.
                m119 = _read_until_ok(port, "M119", 5.0)
                responses.extend(f"M119: {line}" for line in m119)
                endstops = _parse_endstops(m119)
                if distance_mm < 0 and endstops.get(f"{axis.lower()}_min") == "TRIGGERED":
                    raise HTTPException(
                        status_code=409,
                        detail=f"{axis} minimum endstop is TRIGGERED; blocked motion farther toward the minimum.",
                    )

                # Once this service has homed the machine, use the firmware's
                # reported position as a second layer of travel-limit protection.
                if MOTION_REFERENCE["homed"]:
                    m114 = _read_until_ok(port, "M114", 5.0)
                    responses.extend(f"M114: {line}" for line in m114)
                    position_before = parse_m114_response(m114)
                    current = position_before[axis.lower()]
                    target_position = current + distance_mm
                    low, high = AXIS_LIMITS_MM[axis]
                    if target_position < low - 1e-6 or target_position > high + 1e-6:
                        raise HTTPException(
                            status_code=409,
                            detail=(
                                f"Blocked {axis} jog: target {target_position:.2f} mm is outside "
                                f"the software limit {low:.0f}–{high:.0f} mm."
                            ),
                        )

                commands = [
                    "G91",
                    f"G0 {axis}{distance_mm:g} F{feed_mm_min}",
                    "M400",
                    "G90",
                    "M400",
                ]
                for command in commands:
                    lines = _read_until_ok(port, command, 15.0)
                    responses.extend(f"{command}: {line}" for line in lines)
                    if any(line.startswith("Error:") for line in lines):
                        raise HTTPException(status_code=409, detail=f"Marlin reported an error during {command}.")

                if MOTION_REFERENCE["homed"]:
                    m114_after = _read_until_ok(port, "M114", 5.0)
                    responses.extend(f"M114: {line}" for line in m114_after)
                    position_after = parse_m114_response(m114_after)

    except HTTPException:
        raise
    except (serial.SerialException, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Serial error: {exc}")

    return {
        "ok": True,
        "axis": axis,
        "distance_mm": distance_mm,
        "feed_mm_min": feed_mm_min,
        "waited_for_motion": True,
        "homed_reference": MOTION_REFERENCE["homed"],
        "endstops": endstops,
        "position_before_mm": position_before,
        "position_after_mm": position_after,
        "response": responses,
    }


def emergency_stop() -> dict[str, Any]:
    target = chosen_printer()
    if not target:
        raise HTTPException(status_code=409, detail="Printer serial interface is not connected.")
    try:
        with SERIAL_LOCK:
            with serial.Serial(target["device"], BAUD, timeout=0.25, exclusive=True) as port:
                time.sleep(0.2)
                port.write(b"M112\n")
                port.flush()
    except (serial.SerialException, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Serial error: {exc}")
    return {"ok": True, "message": "Marlin emergency-stop command sent. Use the physical power stop for a hardware emergency."}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"ok": True, "hostname": socket.gethostname(), "time": int(time.time())}


@app.get("/api/status", dependencies=[Depends(require_token)])
def status() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    uptime_seconds = None
    try:
        uptime_seconds = float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        pass

    temp_c = None
    thermal = Path("/sys/class/thermal/thermal_zone0/temp")
    try:
        temp_c = round(int(thermal.read_text().strip()) / 1000.0, 1)
    except Exception:
        pass

    printer = chosen_printer()
    calibration_profile = load_profile()
    active_plan = load_plan()
    experiment = active_experiment()
    return {
        "hostname": socket.gethostname(),
        "uptime_seconds": uptime_seconds,
        "cpu_temp_c": temp_c,
        "disk": {
            "total_gb": round(disk.total / (1024**3), 1),
            "used_gb": round(disk.used / (1024**3), 1),
            "free_gb": round(disk.free / (1024**3), 1),
        },
        "network": network_status(),
        "printer": {
            "connected": printer is not None,
            "device": printer["device"] if printer else None,
            "description": printer["description"] if printer else None,
            "commissioning_locked": not read_commissioning()["unlocked"],
        },
        "camera": usb_camera_status(),
        "research": {
            "mode": "OBSERVE",
            "calibrated": calibration_profile is not None,
            "surface_baseline": bool(calibration_profile and calibration_profile.get("surface_baseline")),
            "plan_loaded": active_plan is not None,
            "plan_filename": active_plan.get("filename") if active_plan else None,
            "experiment_active": experiment is not None,
            "experiment_name": experiment.get("name") if experiment else None,
        },
    }


@app.get("/api/network/status", dependencies=[Depends(require_token)])
def api_network_status() -> dict[str, Any]:
    return network_status()


@app.get("/api/network/remote", dependencies=[Depends(require_token)])
def api_remote_access_status() -> dict[str, Any]:
    proc = run_command(["systemctl", "is-active", "cloudflared.service"], timeout=5)
    active = proc.returncode == 0 and proc.stdout.strip() == "active"
    public_url = None
    try:
        value = REMOTE_URL_FILE.read_text(encoding="utf-8").strip()
        if value:
            public_url = value
    except OSError:
        pass
    return {
        "configured": public_url is not None,
        "active": active,
        "public_url": public_url,
        "service": "cloudflared.service",
        "note": (
            "Remote access uses an outbound Cloudflare Tunnel to this controller; "
            "port 8080 should remain closed to the public Internet."
        ),
    }


@app.get("/api/network/scan", dependencies=[Depends(require_token)])
def api_network_scan() -> dict[str, Any]:
    return {"networks": scan_networks()}


@app.post("/api/network/connect", dependencies=[Depends(require_token)])
def api_network_connect(payload: WifiConnectRequest) -> JSONResponse:
    proc = run_network_helper("connect", payload.ssid, payload.password + "\n", timeout=50)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or proc.stdout.strip() or "Unable to connect.")
    return JSONResponse(
        {
            "ok": True,
            "message": "Wi-Fi change requested. This page may disconnect while the Pi joins the selected network.",
            "output": proc.stdout.strip(),
        }
    )


@app.get("/api/network/saved", dependencies=[Depends(require_token)])
def api_network_saved() -> dict[str, Any]:
    proc = run_command(
        [
            "nmcli", "-t", "--escape", "yes",
            "-f", "NAME,TYPE,AUTOCONNECT,AUTOCONNECT-PRIORITY",
            "connection", "show",
        ],
        timeout=10,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Unable to list saved connections.")

    active = active_wifi_connection()
    saved: list[dict[str, Any]] = []
    for line in proc.stdout.splitlines():
        parts = split_nmcli(line, 3)
        if len(parts) != 4:
            continue
        name, kind, autoconnect, priority = parts
        if kind != "802-11-wireless" or name == HOTSPOT_NAME:
            continue
        try:
            priority_value = int(priority or "0")
        except ValueError:
            priority_value = 0
        saved.append(
            {
                "name": name,
                "active": name == active,
                "autoconnect": str(autoconnect).lower() in {"yes", "true", "1"},
                "priority": priority_value,
            }
        )

    saved.sort(key=lambda item: (-int(item["priority"]), not bool(item["active"]), str(item["name"]).lower()))
    return {"connections": saved}


@app.post("/api/network/priority", dependencies=[Depends(require_token)])
def api_network_priority(payload: WifiPriorityRequest) -> dict[str, Any]:
    if not NETWORK_HELPER.exists():
        raise HTTPException(status_code=503, detail="Network helper is not installed.")
    proc = run_command(
        [
            "sudo", "-n", str(NETWORK_HELPER),
            "set-priority", payload.connection, str(payload.priority),
        ],
        timeout=15,
    )
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or proc.stdout.strip() or "Unable to set Wi-Fi priority.")
    return {"ok": True, "connection": payload.connection, "priority": payload.priority}


@app.post("/api/network/activate", dependencies=[Depends(require_token)])
def api_network_activate(payload: WifiActivateRequest) -> dict[str, Any]:
    proc = run_network_helper("activate", payload.connection, timeout=40)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or proc.stdout.strip() or "Unable to activate saved Wi-Fi.")
    return {
        "ok": True,
        "message": "Saved Wi-Fi activation requested. This page may disconnect while the Pi changes networks.",
    }


@app.post("/api/network/forget", dependencies=[Depends(require_token)])
def api_network_forget(payload: WifiForgetRequest) -> dict[str, Any]:
    proc = run_network_helper("forget", payload.connection, timeout=15)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or proc.stdout.strip() or "Unable to forget network.")
    return {"ok": True, "output": proc.stdout.strip()}


@app.get("/api/network/hotspot", dependencies=[Depends(require_token)])
def api_hotspot_status() -> dict[str, Any]:
    status = network_status()
    return {
        "active": status["hotspot_active"],
        "ssid": HOTSPOT_NAME,
        "password": HOTSPOT_PASSWORD,
        "ip_address": HOTSPOT_IP,
        "url": HOTSPOT_URL,
        "fallback_enabled": True,
    }


@app.post("/api/network/hotspot/enable", dependencies=[Depends(require_token)])
def api_hotspot_enable() -> dict[str, Any]:
    proc = run_network_helper("hotspot-on", timeout=25)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or proc.stdout.strip() or "Unable to start hotspot.")
    return {
        "ok": True,
        "message": f"Setup hotspot requested. Connect to {HOTSPOT_NAME} and open {HOTSPOT_URL}.",
    }


@app.post("/api/network/hotspot/disable", dependencies=[Depends(require_token)])
def api_hotspot_disable() -> dict[str, Any]:
    proc = run_network_helper("hotspot-off", timeout=20)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or proc.stdout.strip() or "Unable to stop hotspot.")
    return {"ok": True, "message": "Setup hotspot disabled."}


@app.get("/api/printer/status", dependencies=[Depends(require_token)])
def api_printer_status() -> dict[str, Any]:
    ports = printer_candidates()
    selected = chosen_printer()
    return {
        "connected": selected is not None,
        "selected": selected,
        "candidates": ports,
        "commissioning_locked": not read_commissioning()["unlocked"],
        "motion_reference": dict(MOTION_REFERENCE),
        "limits_mm": AXIS_LIMITS_MM,
        "allowed_commands": sorted(SAFE_COMMANDS),
    }


@app.post("/api/printer/command", dependencies=[Depends(require_token)])
def api_printer_command(payload: SafeCommandRequest) -> dict[str, Any]:
    return send_safe_command(payload.command)


@app.get("/api/monitor/printer-position", dependencies=[Depends(require_token)])
def api_monitor_printer_position() -> dict[str, Any]:
    result = send_safe_command("M114")
    try:
        position = parse_m114_response(result["response"])
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    projected = None
    profile = load_profile()
    if profile:
        try:
            camera_xyz = printer_to_camera(
                profile,
                [position["x"], position["y"], position["z"]],
            )
            projected = project_camera_point(profile, camera_xyz)
        except Exception:
            projected = None

    return {
        "position_mm": position,
        "projected_pixel": projected,
        "device": result.get("device"),
        "raw": result.get("response"),
        "note": "Firmware-reported position is only meaningful after the printer coordinate system has a known reference.",
    }


@app.get("/api/monitor/nozzle-track", dependencies=[Depends(require_token)])
def api_monitor_nozzle_track() -> dict[str, Any]:
    profile = load_profile()
    if not profile or not profile.get("nozzle_reference"):
        raise HTTPException(status_code=409, detail="Mark a nozzle/syringe-tip reference in Calibration first.")

    reference = profile["nozzle_reference"]
    template = reference.get("vision_template")
    if not template:
        raise HTTPException(
            status_code=409,
            detail="The saved nozzle reference predates vision tracking. Re-mark the nozzle tip once.",
        )

    predicted = None
    reported_position = None
    if chosen_printer():
        try:
            marlin = send_safe_command("M114")
            reported_position = parse_m114_response(marlin["response"])
            camera_xyz = printer_to_camera(
                profile,
                [
                    reported_position["x"],
                    reported_position["y"],
                    reported_position["z"],
                ],
            )
            predicted = project_camera_point(profile, camera_xyz)
        except Exception:
            predicted = None

    if predicted is None:
        predicted = reference.get("pixel")

    try:
        frame = latest_live_rgb()
        tracked = track_template(
            frame,
            template,
            predicted_pixel=predicted,
        )
        depth_sample = sample_live_pixel(tracked["u"], tracked["v"])
        tracked["depth_m"] = depth_sample.get("depth_m")
        tracked["camera_xyz_m"] = depth_sample.get("camera_xyz_m")
        tracked["printer_xyz_mm"] = transform_camera_point(
            profile,
            depth_sample["camera_xyz_m"],
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    result = {
        "tracked": tracked,
        "predicted_pixel": predicted,
        "marlin_position_mm": reported_position,
        "reference_pixel": reference.get("pixel"),
        "mode": "OBSERVE",
    }
    log_event(
        "nozzle_track",
        {
            "u": tracked.get("u"),
            "v": tracked.get("v"),
            "confidence": tracked.get("confidence"),
            "printer_xyz_mm": tracked.get("printer_xyz_mm"),
        },
    )
    return result


@app.get("/api/commissioning", dependencies=[Depends(require_token)])
def api_commissioning_status() -> dict[str, Any]:
    return read_commissioning()


@app.post("/api/commissioning", dependencies=[Depends(require_token)])
def api_commissioning_update(payload: CommissioningRequest) -> dict[str, Any]:
    return save_commissioning(payload)


@app.post("/api/printer/jog", dependencies=[Depends(require_token)])
def api_printer_jog(payload: JogRequest) -> dict[str, Any]:
    return serial_motion(payload.axis, payload.distance_mm, payload.feed_mm_min)


@app.post("/api/printer/home-center", dependencies=[Depends(require_token)])
def api_printer_home_center() -> dict[str, Any]:
    return home_and_center()


@app.post("/api/printer/emergency-stop", dependencies=[Depends(require_token)])
def api_printer_emergency_stop() -> dict[str, Any]:
    return emergency_stop()


@app.get("/api/printer/port-owner", dependencies=[Depends(require_token)])
def api_printer_port_owner() -> dict[str, Any]:
    target = chosen_printer()
    if not target:
        return {"connected": False, "device": None, "owners": ""}
    proc = run_command(["fuser", "-v", target["device"]], timeout=5)
    return {
        "connected": True,
        "device": target["device"],
        "owners": (proc.stdout + proc.stderr).strip(),
        "returncode": proc.returncode,
    }


@app.get("/api/camera/status", dependencies=[Depends(require_token)])
def api_camera_status() -> dict[str, Any]:
    return usb_camera_status()


@app.get("/api/camera/live/status", dependencies=[Depends(require_token)])
def api_camera_live_status() -> dict[str, Any]:
    return live_camera_status()


@app.post("/api/camera/live/start", dependencies=[Depends(require_token)])
def api_camera_live_start() -> dict[str, Any]:
    status = start_live_camera()
    if status.get("error"):
        raise HTTPException(status_code=503, detail=status["error"])
    return status


@app.post("/api/camera/live/stop", dependencies=[Depends(require_token)])
def api_camera_live_stop() -> dict[str, Any]:
    return stop_live_camera()


@app.get("/api/camera/color.jpg", dependencies=[Depends(require_token)])
def api_camera_color_image() -> Response:
    try:
        data = capture_color_jpeg()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/camera/measure", dependencies=[Depends(require_token)])
def api_camera_measure() -> dict[str, Any]:
    try:
        return capture_depth_sample()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.post("/api/camera/pixel", dependencies=[Depends(require_token)])
def api_camera_pixel(payload: PixelPointRequest) -> dict[str, Any]:
    try:
        sample = sample_live_pixel(payload.u, payload.v)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    profile = load_profile()
    if profile:
        try:
            sample["printer_xyz_mm"] = transform_camera_point(profile, sample["camera_xyz_m"])
        except Exception:
            pass
    log_event("coordinate_probe", sample)
    return sample


@app.get("/api/calibration", dependencies=[Depends(require_token)])
def api_calibration_status() -> dict[str, Any]:
    return {
        "profile": load_profile(),
        "camera": usb_camera_status(),
        "live": live_camera_status(),
    }


@app.delete("/api/calibration", dependencies=[Depends(require_token)])
def api_calibration_clear() -> dict[str, Any]:
    clear_profile()
    return {"ok": True, "profile": None}


@app.post("/api/calibration/solve", dependencies=[Depends(require_token)])
def api_calibration_solve(payload: CalibrationSolveRequest) -> dict[str, Any]:
    if len(payload.points) != 4:
        raise HTTPException(status_code=400, detail="Exactly four corner points are required.")

    camera = usb_camera_status()
    try:
        profile = solve_bed_calibration(
            [point.model_dump() for point in payload.points],
            origin_x_mm=payload.origin_x_mm,
            origin_y_mm=payload.origin_y_mm,
            width_mm=payload.width_mm,
            depth_mm=payload.depth_mm,
            camera_serial=camera.get("serial_number"),
            camera_model=camera.get("model"),
            frame_width=payload.frame_width,
            frame_height=payload.frame_height,
            intrinsics=live_camera_status().get("intrinsics"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"ok": True, "profile": profile}


@app.post("/api/calibration/nozzle", dependencies=[Depends(require_token)])
def api_calibration_nozzle(payload: PixelPointRequest) -> dict[str, Any]:
    profile = load_profile()
    if not profile:
        raise HTTPException(status_code=409, detail="Complete bed calibration before marking the nozzle tip.")

    try:
        sample = sample_live_pixel(payload.u, payload.v)
        template = capture_live_template(sample["u"], sample["v"], size=31)
        profile = save_nozzle_reference(
            profile,
            pixel_u=sample["u"],
            pixel_v=sample["v"],
            camera_xyz_m=sample["camera_xyz_m"],
            template=template,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "ok": True,
        "sample": sample,
        "profile": profile,
    }


@app.post("/api/calibration/surface", dependencies=[Depends(require_token)])
def api_calibration_surface(payload: SurfaceAnalysisRequest) -> dict[str, Any]:
    profile = load_profile()
    if not profile:
        raise HTTPException(status_code=409, detail="Complete bed calibration before analyzing the surface.")

    try:
        result = analyze_surface(
            profile,
            sample_live_pixels,
            columns=payload.columns,
            rows=payload.rows,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    log_event("surface_scan", {key: value for key, value in result.items() if key != "samples"})
    return result


@app.post("/api/calibration/baseline", dependencies=[Depends(require_token)])
def api_calibration_baseline(payload: SurfaceAnalysisRequest) -> dict[str, Any]:
    profile = load_profile()
    if not profile:
        raise HTTPException(status_code=409, detail="Complete bed calibration before saving a reference surface.")

    try:
        result = analyze_surface(
            profile,
            sample_live_pixels,
            columns=payload.columns,
            rows=payload.rows,
        )
        profile = save_surface_baseline(profile, result)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    log_event(
        "surface_baseline_saved",
        {
            "sample_count": result.get("sample_count"),
            "grid": result.get("grid"),
            "rms_z_mm": result.get("rms_z_mm"),
            "peak_to_peak_mm": result.get("peak_to_peak_mm"),
        },
    )
    return {"ok": True, "profile": profile, "surface": result}


@app.get("/api/experiment", dependencies=[Depends(require_token)])
def api_experiment_status() -> dict[str, Any]:
    return {
        "active": active_experiment(),
        "recent": list_experiments(limit=12),
    }


@app.post("/api/experiment/start", dependencies=[Depends(require_token)])
def api_experiment_start(payload: ExperimentStartRequest) -> dict[str, Any]:
    try:
        metadata = start_experiment(
            payload.name,
            calibration=load_profile(),
            plan=load_plan(),
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "experiment": metadata}


@app.post("/api/experiment/snapshot", dependencies=[Depends(require_token)])
def api_experiment_snapshot() -> dict[str, Any]:
    if not active_experiment():
        raise HTTPException(status_code=409, detail="Start an experiment before recording a snapshot.")
    try:
        rgb = capture_color_jpeg()
        depth = capture_depth_jpeg()
        measurement = capture_depth_sample()
        record = save_snapshot(
            rgb_jpeg=rgb,
            depth_jpeg=depth,
            measurement=measurement,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"ok": True, "snapshot": record}


@app.post("/api/experiment/stop", dependencies=[Depends(require_token)])
def api_experiment_stop() -> dict[str, Any]:
    try:
        metadata = stop_experiment()
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "experiment": metadata}


@app.post("/api/quality/final-surface", dependencies=[Depends(require_token)])
def api_quality_final_surface(payload: QualityAnalysisRequest) -> dict[str, Any]:
    profile = load_profile()
    plan = load_plan()
    if not profile:
        raise HTTPException(status_code=409, detail="Camera-to-printer calibration is required.")
    if not profile.get("surface_baseline"):
        raise HTTPException(status_code=409, detail="Save a clean reference surface before quality analysis.")
    if not plan:
        raise HTTPException(status_code=409, detail="Load the G-code print plan before quality analysis.")

    try:
        surface = analyze_surface(
            profile,
            sample_live_pixels,
            columns=payload.columns,
            rows=payload.rows,
        )
        result = analyze_final_surface_quality(
            surface,
            plan,
            path_radius_mm=payload.path_radius_mm,
            min_deposition_height_mm=payload.min_deposition_height_mm,
            height_tolerance_mm=payload.height_tolerance_mm,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    log_event(
        "final_surface_quality",
        {key: value for key, value in result.items() if key != "points"},
    )
    return result


def _print_monitor_callback(layer: int) -> dict[str, Any]:
    profile = load_profile()
    plan = load_plan()
    if not profile or not profile.get("surface_baseline"):
        return {
            "available": False,
            "status": "CALIBRATION_REQUIRED",
            "failure_type": None,
            "message": "Save camera-to-printer calibration and a clean surface baseline to enable automatic print-health checks.",
            "metrics": None,
        }
    if not plan:
        return {
            "available": False,
            "status": "NO_PLAN",
            "failure_type": None,
            "message": "No active print plan is available for camera comparison.",
            "metrics": None,
        }

    live = live_camera_status()
    if not live.get("running"):
        start_live_camera()

    surface = analyze_surface(
        profile,
        sample_live_pixels,
        columns=14,
        rows=10,
    )
    assessment, quality = evaluate_layer(
        surface=surface,
        plan=plan,
        current_layer=layer,
        path_radius_mm=2.0,
        min_deposition_height_mm=0.10,
        height_tolerance_mm=0.50,
    )

    rgb_path = depth_path = None
    try:
        rgb_path, depth_path = save_training_frames(
            layer,
            capture_color_jpeg(),
            capture_depth_jpeg(),
        )
    except Exception:
        pass

    save_observation(
        layer=layer,
        assessment=assessment,
        quality=quality,
        rgb_path=rgb_path,
        depth_path=depth_path,
    )
    log_event(
        "print_layer_quality",
        {
            "layer": layer,
            "status": assessment.get("status"),
            "failure_type": assessment.get("failure_type"),
            "metrics": assessment.get("metrics"),
        },
    )
    return assessment


@app.get("/api/print/status", dependencies=[Depends(require_token)])
def api_print_status() -> dict[str, Any]:
    return PRINT_RUNNER.status()


@app.post("/api/print/start", dependencies=[Depends(require_token)])
def api_print_start(payload: PrintStartRequest) -> dict[str, Any]:
    if not payload.confirm_physical_stop_available:
        raise HTTPException(
            status_code=409,
            detail="Confirm that the physical power cutoff is immediately available before starting a print.",
        )

    commissioning = read_commissioning()
    if not commissioning.get("unlocked"):
        raise HTTPException(status_code=423, detail="Commissioning lock is active.")

    plan = load_plan()
    if not plan:
        raise HTTPException(status_code=409, detail="No G-code print plan is loaded.")

    slicer = plan.get("slicer")
    if not isinstance(slicer, dict):
        raise HTTPException(
            status_code=409,
            detail="Physical printing is enabled only for plans generated by the VT bioprinter slicer.",
        )

    preflight = slicer.get("preflight") or {}
    if not preflight.get("ready_for_physical_print"):
        blocking = [
            check.get("name", "check")
            for check in preflight.get("checks", [])
            if not check.get("ok")
        ]
        detail = "Physical print preflight is blocked"
        if blocking:
            detail += ": " + ", ".join(blocking)
        raise HTTPException(status_code=409, detail=detail + ".")

    gcode = plan.get("source_gcode")
    if not isinstance(gcode, str) or not gcode.strip():
        raise HTTPException(
            status_code=409,
            detail="The loaded plan does not contain executable source G-code. Re-slice or reload the plan.",
        )

    target = chosen_printer()
    if not target:
        raise HTTPException(status_code=409, detail="No high-confidence Creality/CH340 serial interface is connected.")

    monitor_callback = _print_monitor_callback if load_profile() and load_profile().get("surface_baseline") else None
    try:
        state = PRINT_RUNNER.start(
            filename=str(plan.get("filename") or "print.gcode"),
            gcode=gcode,
            device=target["device"],
            baud=BAUD,
            serial_lock=SERIAL_LOCK,
            monitor_callback=monitor_callback,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    log_event("print_started", {"filename": plan.get("filename")})
    return state


@app.post("/api/print/pause", dependencies=[Depends(require_token)])
def api_print_pause() -> dict[str, Any]:
    try:
        return PRINT_RUNNER.pause()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/print/resume", dependencies=[Depends(require_token)])
def api_print_resume() -> dict[str, Any]:
    try:
        return PRINT_RUNNER.resume()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/print/stop", dependencies=[Depends(require_token)])
def api_print_stop() -> dict[str, Any]:
    try:
        state = PRINT_RUNNER.request_stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_event("print_stop_requested", {"filename": state.get("filename")})
    return state


@app.get("/api/plan", dependencies=[Depends(require_token)])
def api_plan_status() -> dict[str, Any]:
    plan = load_plan()
    if not plan:
        return {"loaded": False, "plan": None}
    summary = {key: value for key, value in plan.items() if key not in {"segments", "source_gcode"}}
    return {"loaded": True, "plan": summary}


@app.post("/api/plan", dependencies=[Depends(require_token)])
def api_plan_load(payload: PlanLoadRequest) -> dict[str, Any]:
    try:
        plan = parse_gcode(payload.text, payload.filename)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    summary = {key: value for key, value in plan.items() if key != "segments"}
    return {"ok": True, "plan": summary}


@app.delete("/api/plan", dependencies=[Depends(require_token)])
def api_plan_clear() -> dict[str, Any]:
    clear_plan()
    return {"ok": True}


@app.post("/api/slicer/stl", dependencies=[Depends(require_token)])
def api_slice_stl(payload: SlicerRequest) -> dict[str, Any]:
    try:
        stl_data = base64.b64decode(payload.stl_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid STL upload encoding.") from exc

    if len(stl_data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="STL is larger than the 12 MB Raspberry Pi slicer limit.")

    try:
        return slice_stl_to_syringe_gcode(
            stl_data,
            filename=payload.filename,
            layer_height_mm=payload.layer_height_mm,
            bead_width_mm=payload.bead_width_mm,
            infill_percent=payload.infill_percent,
            syringe_diameter_mm=payload.syringe_diameter_mm,
            syringe_capacity_ml=payload.syringe_capacity_ml,
            needle_inner_diameter_mm=payload.needle_inner_diameter_mm,
            alginate_percent_wv=payload.alginate_percent_wv,
            calcium_chloride_mM=payload.calcium_chloride_mM,
            crosslink_mode=payload.crosslink_mode,
            support_strategy=payload.support_strategy,
            temperature_mode=payload.temperature_mode,
            bed_temperature_c=payload.bed_temperature_c,
            extrusion_multiplier=payload.extrusion_multiplier,
            travel_lift_mm=payload.travel_lift_mm,
            print_feed_mm_min=payload.print_feed_mm_min,
            travel_feed_mm_min=payload.travel_feed_mm_min,
            e_steps_calibrated=payload.e_steps_calibrated,
            motor_direction_verified=payload.motor_direction_verified,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/plan/projected", dependencies=[Depends(require_token)])
def api_plan_projected() -> dict[str, Any]:
    profile = load_profile()
    plan = load_plan()
    if not profile:
        raise HTTPException(status_code=409, detail="Camera-to-printer calibration is required before projecting G-code.")
    if not plan:
        raise HTTPException(status_code=409, detail="No G-code print plan is loaded.")

    try:
        return project_plan(profile, plan)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/camera/depth.jpg", dependencies=[Depends(require_token)])
def api_camera_depth_image() -> Response:
    try:
        data = capture_depth_jpeg()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.exception_handler(subprocess.TimeoutExpired)
def subprocess_timeout_handler(request: Request, exc: subprocess.TimeoutExpired) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": "System command timed out."})
