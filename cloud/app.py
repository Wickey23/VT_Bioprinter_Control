from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"

app = FastAPI(title="VT Bioprinter Cloud", version="0.1.0")
app.mount("/assets", StaticFiles(directory=PUBLIC_DIR), name="assets")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "vt-bioprinter-cloud",
        "version": "0.1.0",
        "time_unix": int(time.time()),
    }


@app.get("/api/device/status")
def device_status() -> dict:
    # Cloud deployment is intentionally hardware-independent. The Raspberry Pi
    # relay/device session will populate this endpoint in the next integration
    # step instead of Vercel trying to access USB hardware directly.
    return {
        "paired": False,
        "online": False,
        "device_id": None,
        "hostname": None,
        "printer_connected": False,
        "camera_connected": False,
        "message": "Cloud dashboard is online. Raspberry Pi device relay is not paired yet.",
    }


@app.get("/")
def root() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/{path:path}")
def spa_fallback(path: str) -> FileResponse:
    candidate = PUBLIC_DIR / path
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(PUBLIC_DIR / "index.html")
