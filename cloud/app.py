from __future__ import annotations

import os
import secrets
import time
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response

app = FastAPI(title="VT Bioprinter Cloud", version="0.2.0")

DEVICE_URL = os.environ.get("BIOPRINTER_DEVICE_URL", "").rstrip("/")
DEVICE_TOKEN = os.environ.get("BIOPRINTER_DEVICE_TOKEN", "")
CLOUD_ACCESS_KEY = os.environ.get("BIOPRINTER_CLOUD_ACCESS_KEY", "")

# Only these Raspberry Pi API routes can be reached through the public cloud
# dashboard. Wi-Fi/network mutation routes are deliberately excluded.
GET_ROUTES = {
    "/api/status",
    "/api/printer/status",
    "/api/commissioning",
    "/api/camera/status",
    "/api/camera/live/status",
    "/api/camera/measure",
    "/api/plan",
    "/api/plan/projected",
    "/api/experiment",
    "/api/calibration",
    "/api/network/remote",
    "/api/monitor/printer-position",
    "/api/monitor/nozzle-track",
}
POST_ROUTES = {
    "/api/printer/command",
    "/api/printer/jog",
    "/api/printer/home-center",
    "/api/printer/emergency-stop",
    "/api/commissioning",
    "/api/camera/live/start",
    "/api/camera/live/stop",
    "/api/camera/pixel",
    "/api/calibration/solve",
    "/api/calibration/nozzle",
    "/api/calibration/surface",
    "/api/calibration/baseline",
    "/api/plan",
    "/api/slicer/stl",
    "/api/experiment/start",
    "/api/experiment/snapshot",
    "/api/experiment/stop",
    "/api/quality/final-surface",
}
DELETE_ROUTES = {
    "/api/plan",
    "/api/calibration",
}
BINARY_GET_PREFIXES = (
    "/api/camera/",
)


def device_configured() -> bool:
    return bool(DEVICE_URL and DEVICE_TOKEN)


def require_cloud_key(x_cloud_access_key: str | None) -> None:
    # Read-only status remains usable before a cloud key is configured, but
    # hardware-changing requests are blocked.
    if not CLOUD_ACCESS_KEY:
        raise HTTPException(
            status_code=503,
            detail="Remote control is locked until BIOPRINTER_CLOUD_ACCESS_KEY is configured.",
        )
    if not x_cloud_access_key or not secrets.compare_digest(x_cloud_access_key, CLOUD_ACCESS_KEY):
        raise HTTPException(status_code=401, detail="Invalid cloud access key.")


async def device_request(method: str, path: str, body: bytes | None = None) -> httpx.Response:
    if not device_configured():
        raise HTTPException(status_code=503, detail="Raspberry Pi is not paired with this cloud project.")

    headers = {"X-Bioprinter-Token": DEVICE_TOKEN}
    if body:
        headers["Content-Type"] = "application/json"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=6.0), follow_redirects=False) as client:
            response = await client.request(method, f"{DEVICE_URL}{path}", headers=headers, content=body)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Raspberry Pi is offline or unreachable: {exc.__class__.__name__}") from exc

    return response


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "vt-bioprinter-cloud",
        "version": "0.2.0",
        "time_unix": int(time.time()),
        "device_configured": device_configured(),
        "remote_control_locked": not bool(CLOUD_ACCESS_KEY),
    }


@app.get("/api/auth/check")
def auth_check(x_cloud_access_key: str | None = Header(default=None)) -> dict[str, bool]:
    require_cloud_key(x_cloud_access_key)
    return {"ok": True}


@app.get("/api/device/status")
async def device_status() -> dict[str, Any]:
    if not device_configured():
        return {
            "paired": False,
            "online": False,
            "device_id": None,
            "hostname": None,
            "printer_connected": False,
            "camera_connected": False,
            "message": "Cloud dashboard is online. Raspberry Pi device URL/token are not configured yet.",
        }

    try:
        response = await device_request("GET", "/api/status")
        if response.status_code != 200:
            return {
                "paired": True,
                "online": False,
                "device_id": "vt-bioprinter-01",
                "hostname": None,
                "printer_connected": False,
                "camera_connected": False,
                "message": f"Raspberry Pi endpoint responded with HTTP {response.status_code}.",
            }
        data = response.json()
    except (HTTPException, ValueError) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else "Raspberry Pi returned invalid status data."
        return {
            "paired": True,
            "online": False,
            "device_id": "vt-bioprinter-01",
            "hostname": None,
            "printer_connected": False,
            "camera_connected": False,
            "message": str(message),
        }

    return {
        "paired": True,
        "online": True,
        "device_id": "vt-bioprinter-01",
        "hostname": data.get("hostname"),
        "printer_connected": bool((data.get("printer") or {}).get("connected")),
        "camera_connected": bool((data.get("camera") or {}).get("usb_detected")),
        "network": data.get("network"),
        "research": data.get("research"),
        "message": "Raspberry Pi device is online through the secure cloud bridge.",
    }


@app.api_route("/api/device/proxy/{route:path}", methods=["GET", "POST", "DELETE"])
async def device_proxy(
    route: str,
    request: Request,
    x_cloud_access_key: str | None = Header(default=None),
) -> Response:
    path = "/" + route
    method = request.method.upper()

    allowed = (
        (method == "GET" and (path in GET_ROUTES or path.startswith(BINARY_GET_PREFIXES)))
        or (method == "POST" and path in POST_ROUTES)
        or (method == "DELETE" and path in DELETE_ROUTES)
    )
    if not allowed:
        raise HTTPException(status_code=403, detail="This Raspberry Pi route is not available through cloud control.")

    # Any request capable of changing printer/device state requires a separate
    # cloud access key. GET endpoints remain read-only.
    if method != "GET":
        require_cloud_key(x_cloud_access_key)

    body = await request.body() if method in {"POST", "DELETE"} else None
    upstream = await device_request(method, path, body)

    blocked_headers = {
        "content-length",
        "transfer-encoding",
        "connection",
        "content-encoding",
    }
    headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in blocked_headers
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=headers,
        media_type=upstream.headers.get("content-type"),
    )
