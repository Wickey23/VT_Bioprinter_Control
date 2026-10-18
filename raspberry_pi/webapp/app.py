#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

import serial
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from serial.tools import list_ports

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
CONFIG_DIR = Path(os.environ.get("VT_BIOPRINTER_CONFIG_DIR", Path.home() / ".config" / "vt-bioprinter"))
TOKEN_FILE = CONFIG_DIR / "token"
NETWORK_HELPER = Path(os.environ.get("VT_BIOPRINTER_NETWORK_HELPER", "/usr/local/sbin/vt-bioprinter-network"))
BAUD = 115200
SAFE_COMMANDS = {"M105", "M114", "M115", "M119", "M503"}

app = FastAPI(title="VT Bioprinter Controller", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class WifiConnectRequest(BaseModel):
    ssid: str = Field(min_length=1, max_length=128)
    password: str = Field(default="", max_length=256)


class WifiForgetRequest(BaseModel):
    connection: str = Field(min_length=1, max_length=256)


class SafeCommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=64)


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


def network_status() -> dict[str, Any]:
    ssid = None
    signal = None
    security = None
    try:
        for line in nmcli_lines("ACTIVE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", "ifname", "wlan0"):
            parts = split_nmcli(line, 3)
            if len(parts) >= 4 and parts[0] == "yes":
                ssid, signal, security = parts[1], parts[2], parts[3]
                break
    except Exception:
        pass

    ip_address = None
    proc = run_command(["hostname", "-I"], timeout=3)
    if proc.returncode == 0:
        addrs = [x for x in proc.stdout.strip().split() if "." in x]
        if addrs:
            ip_address = addrs[0]

    return {
        "connected": bool(ssid),
        "ssid": ssid,
        "signal": int(signal) if signal and signal.isdigit() else None,
        "security": security,
        "ip_address": ip_address,
    }


def scan_networks() -> list[dict[str, Any]]:
    try:
        lines = nmcli_lines("SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list", "--rescan", "yes", "ifname", "wlan0")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Wi-Fi scan failed: {exc}")

    seen: dict[str, dict[str, Any]] = {}
    for line in lines:
        parts = split_nmcli(line, 3)
        if len(parts) < 4:
            continue
        ssid, signal, security, in_use = parts
        if not ssid:
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
        with serial.Serial(target["device"], BAUD, timeout=0.25) as port:
            time.sleep(1.0)
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
            "commissioning_locked": True,
        },
    }


@app.get("/api/network/status", dependencies=[Depends(require_token)])
def api_network_status() -> dict[str, Any]:
    return network_status()


@app.get("/api/network/scan", dependencies=[Depends(require_token)])
def api_network_scan() -> dict[str, Any]:
    return {"networks": scan_networks()}


@app.post("/api/network/connect", dependencies=[Depends(require_token)])
def api_network_connect(payload: WifiConnectRequest) -> JSONResponse:
    if not NETWORK_HELPER.exists():
        raise HTTPException(status_code=503, detail="Network helper is not installed.")
    proc = run_command(
        ["sudo", "-n", str(NETWORK_HELPER), "connect", payload.ssid],
        timeout=45,
        input_text=payload.password + "\n",
    )
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
    proc = run_command(["nmcli", "-t", "--escape", "yes", "-f", "NAME,TYPE", "connection", "show"], timeout=10)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or "Unable to list saved connections.")
    saved = []
    for line in proc.stdout.splitlines():
        parts = split_nmcli(line, 1)
        if len(parts) == 2 and parts[1] == "802-11-wireless":
            saved.append(parts[0])
    return {"connections": saved}


@app.post("/api/network/forget", dependencies=[Depends(require_token)])
def api_network_forget(payload: WifiForgetRequest) -> dict[str, Any]:
    if not NETWORK_HELPER.exists():
        raise HTTPException(status_code=503, detail="Network helper is not installed.")
    proc = run_command(["sudo", "-n", str(NETWORK_HELPER), "forget", payload.connection], timeout=15)
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=proc.stderr.strip() or proc.stdout.strip() or "Unable to forget network.")
    return {"ok": True, "output": proc.stdout.strip()}


@app.get("/api/printer/status", dependencies=[Depends(require_token)])
def api_printer_status() -> dict[str, Any]:
    ports = printer_candidates()
    selected = chosen_printer()
    return {
        "connected": selected is not None,
        "selected": selected,
        "candidates": ports,
        "commissioning_locked": True,
        "allowed_commands": sorted(SAFE_COMMANDS),
    }


@app.post("/api/printer/command", dependencies=[Depends(require_token)])
def api_printer_command(payload: SafeCommandRequest) -> dict[str, Any]:
    return send_safe_command(payload.command)


@app.exception_handler(subprocess.TimeoutExpired)
def subprocess_timeout_handler(request: Request, exc: subprocess.TimeoutExpired) -> JSONResponse:
    return JSONResponse(status_code=504, content={"detail": "System command timed out."})
