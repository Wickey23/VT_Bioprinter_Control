from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

CONFIG_DIR = Path(
    os.environ.get(
        "VT_BIOPRINTER_CONFIG_DIR",
        Path.home() / ".config" / "vt-bioprinter",
    )
)
PLAN_DIR = CONFIG_DIR / "print-plan"
ACTIVE_PLAN = PLAN_DIR / "active.json"


def load_plan() -> dict[str, Any] | None:
    try:
        data = json.loads(ACTIVE_PLAN.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_plan(plan: dict[str, Any]) -> dict[str, Any]:
    PLAN_DIR.mkdir(parents=True, exist_ok=True)
    ACTIVE_PLAN.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return plan


def clear_plan() -> None:
    try:
        ACTIVE_PLAN.unlink()
    except FileNotFoundError:
        pass


def _tokens(line: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for token in line.split()[1:]:
        if len(token) < 2:
            continue
        key = token[0].upper()
        if key not in {"X", "Y", "Z", "E", "F"}:
            continue
        try:
            result[key] = float(token[1:])
        except ValueError:
            continue
    return result


def parse_gcode(text: str, filename: str = "print.gcode") -> dict[str, Any]:
    absolute_xyz = True
    absolute_e = True

    x = y = z = e = 0.0
    feed = 0.0
    layer = 0
    last_z = z

    segments: list[dict[str, Any]] = []
    total_motion = 0.0
    total_extruding_motion = 0.0
    extrusion_delta_total = 0.0

    for line_number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue

        upper = stripped.upper()
        if upper.startswith(";LAYER:"):
            try:
                layer = int(upper.split(":", 1)[1].strip())
            except ValueError:
                pass

        code = stripped.split(";", 1)[0].strip()
        if not code:
            continue

        command = code.split()[0].upper()

        if command == "G90":
            absolute_xyz = True
            continue
        if command == "G91":
            absolute_xyz = False
            continue
        if command == "M82":
            absolute_e = True
            continue
        if command == "M83":
            absolute_e = False
            continue

        params = _tokens(code)

        if command == "G92":
            if "X" in params:
                x = params["X"]
            if "Y" in params:
                y = params["Y"]
            if "Z" in params:
                z = params["Z"]
            if "E" in params:
                e = params["E"]
            continue

        if command not in {"G0", "G00", "G1", "G01"}:
            continue

        start = (x, y, z)
        start_e = e

        nx = params.get("X", x if absolute_xyz else 0.0)
        ny = params.get("Y", y if absolute_xyz else 0.0)
        nz = params.get("Z", z if absolute_xyz else 0.0)

        if absolute_xyz:
            if "X" in params:
                x = nx
            if "Y" in params:
                y = ny
            if "Z" in params:
                z = nz
        else:
            if "X" in params:
                x += nx
            if "Y" in params:
                y += ny
            if "Z" in params:
                z += nz

        if "E" in params:
            if absolute_e:
                e = params["E"]
            else:
                e += params["E"]

        if "F" in params:
            feed = params["F"]

        if abs(z - last_z) > 1e-6 and not upper.startswith(";LAYER:"):
            if z > last_z + 1e-5:
                layer += 1
            last_z = z

        end = (x, y, z)
        dx, dy, dz = x - start[0], y - start[1], z - start[2]
        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        e_delta = e - start_e
        extruding = e_delta > 1e-7 and length > 1e-7

        if length <= 1e-9 and abs(e_delta) <= 1e-9:
            continue

        total_motion += length
        if extruding:
            total_extruding_motion += length
            extrusion_delta_total += e_delta

        segments.append(
            {
                "line": line_number,
                "layer": layer,
                "start": [round(v, 5) for v in start],
                "end": [round(v, 5) for v in end],
                "feed_mm_min": round(feed, 3),
                "e_delta": round(e_delta, 6),
                "extruding": extruding,
                "length_mm": round(length, 5),
            }
        )

    if not segments:
        raise ValueError("No G0/G1 motion segments were found in this G-code.")

    all_points = [segment["start"] for segment in segments] + [segment["end"] for segment in segments]
    coords = np.asarray(all_points, dtype=float)
    mins = coords.min(axis=0)
    maxs = coords.max(axis=0)

    plan = {
        "version": 1,
        "filename": filename,
        "loaded_at_unix": int(time.time()),
        "segment_count": len(segments),
        "extruding_segment_count": sum(1 for s in segments if s["extruding"]),
        "layer_count_estimate": max((int(s["layer"]) for s in segments), default=0) + 1,
        "total_motion_mm": round(total_motion, 3),
        "extruding_motion_mm": round(total_extruding_motion, 3),
        "extrusion_delta_total": round(extrusion_delta_total, 5),
        "bounds_mm": {
            "min": [round(float(v), 4) for v in mins],
            "max": [round(float(v), 4) for v in maxs],
        },
        "segments": segments,
    }
    return save_plan(plan)


def printer_to_camera(profile: dict[str, Any], printer_xyz_mm: list[float]) -> list[float]:
    transform = profile.get("camera_to_printer")
    if not transform:
        raise ValueError("Calibration transform is missing.")

    rotation = np.asarray(transform["rotation"], dtype=float)
    translation = np.asarray(transform["translation_mm"], dtype=float)
    printer = np.asarray(printer_xyz_mm, dtype=float)
    camera_mm = rotation.T @ (printer - translation)
    return [float(v) / 1000.0 for v in camera_mm]


def project_camera_point(profile: dict[str, Any], camera_xyz_m: list[float]) -> list[float] | None:
    intrinsics = profile.get("camera", {}).get("intrinsics")
    if not intrinsics:
        return None

    x, y, z = (float(v) for v in camera_xyz_m)
    if z <= 1e-6:
        return None

    fx = float(intrinsics["fx"])
    fy = float(intrinsics["fy"])
    ppx = float(intrinsics["ppx"])
    ppy = float(intrinsics["ppy"])

    u = fx * x / z + ppx
    v = fy * y / z + ppy

    width = int(intrinsics.get("width") or profile.get("camera", {}).get("frame_width") or 0)
    height = int(intrinsics.get("height") or profile.get("camera", {}).get("frame_height") or 0)

    if width and height and (u < -50 or v < -50 or u > width + 50 or v > height + 50):
        return None

    return [round(float(u), 3), round(float(v), 3)]


def project_plan(
    profile: dict[str, Any],
    plan: dict[str, Any],
    *,
    max_segments: int = 1800,
    extruding_only: bool = True,
) -> dict[str, Any]:
    segments = plan.get("segments", [])
    if extruding_only:
        segments = [segment for segment in segments if segment.get("extruding")]

    if not segments:
        return {"segments": [], "source_count": 0, "returned_count": 0}

    stride = max(1, math.ceil(len(segments) / max_segments))
    projected: list[dict[str, Any]] = []

    for segment in segments[::stride]:
        c0 = printer_to_camera(profile, segment["start"])
        c1 = printer_to_camera(profile, segment["end"])
        p0 = project_camera_point(profile, c0)
        p1 = project_camera_point(profile, c1)
        if p0 is None or p1 is None:
            continue

        projected.append(
            {
                "start": p0,
                "end": p1,
                "layer": segment.get("layer", 0),
                "extruding": bool(segment.get("extruding")),
                "z_mm": segment["end"][2],
            }
        )

    return {
        "filename": plan.get("filename"),
        "source_count": len(segments),
        "returned_count": len(projected),
        "stride": stride,
        "segments": projected,
    }
