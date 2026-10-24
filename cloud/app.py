from __future__ import annotations

import time

from fastapi import FastAPI

app = FastAPI(title="VT Bioprinter Cloud", version="0.1.1")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "vt-bioprinter-cloud",
        "version": "0.1.1",
        "time_unix": int(time.time()),
    }


@app.get("/api/device/status")
def device_status() -> dict:
    # The Vercel function is intentionally hardware-independent. The
    # Raspberry Pi device agent will publish live state to the cloud relay.
    return {
        "paired": False,
        "online": False,
        "device_id": None,
        "hostname": None,
        "printer_connected": False,
        "camera_connected": False,
        "message": "Cloud dashboard is online. Raspberry Pi device relay is not paired yet.",
    }
