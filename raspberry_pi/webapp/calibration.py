from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

CONFIG_DIR = Path(
    os.environ.get(
        "VT_BIOPRINTER_CONFIG_DIR",
        Path.home() / ".config" / "vt-bioprinter",
    )
)
CALIBRATION_DIR = CONFIG_DIR / "calibration"
ACTIVE_PROFILE = CALIBRATION_DIR / "active.json"


def _json_ready(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    return value


def load_profile() -> dict[str, Any] | None:
    try:
        data = json.loads(ACTIVE_PROFILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_profile(profile: dict[str, Any]) -> dict[str, Any]:
    CALIBRATION_DIR.mkdir(parents=True, exist_ok=True)
    profile = json.loads(json.dumps(profile, default=_json_ready))
    ACTIVE_PROFILE.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    return profile


def clear_profile() -> None:
    try:
        ACTIVE_PROFILE.unlink()
    except FileNotFoundError:
        pass


def _rigid_transform(source_mm: np.ndarray, target_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if source_mm.shape != target_mm.shape or source_mm.shape[1] != 3:
        raise ValueError("Calibration source/target arrays must both be Nx3.")

    source_center = source_mm.mean(axis=0)
    target_center = target_mm.mean(axis=0)
    src = source_mm - source_center
    dst = target_mm - target_center

    h = src.T @ dst
    u, _, vt = np.linalg.svd(h)
    rotation = vt.T @ u.T

    if np.linalg.det(rotation) < 0:
        vt[-1, :] *= -1
        rotation = vt.T @ u.T

    translation = target_center - rotation @ source_center
    return rotation, translation


def transform_camera_point(
    profile: dict[str, Any],
    camera_xyz_m: list[float] | tuple[float, float, float],
) -> list[float]:
    transform = profile.get("camera_to_printer")
    if not transform:
        raise ValueError("Calibration profile does not contain a camera-to-printer transform.")

    rotation = np.asarray(transform["rotation"], dtype=float)
    translation = np.asarray(transform["translation_mm"], dtype=float)
    camera_mm = np.asarray(camera_xyz_m, dtype=float) * 1000.0
    printer = rotation @ camera_mm + translation
    return [round(float(x), 4) for x in printer]


def solve_bed_calibration(
    points: list[dict[str, Any]],
    *,
    origin_x_mm: float,
    origin_y_mm: float,
    width_mm: float,
    depth_mm: float,
    camera_serial: str | None,
    camera_model: str | None,
    frame_width: int,
    frame_height: int,
    intrinsics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if len(points) != 4:
        raise ValueError("Exactly four bed-corner points are required.")

    if width_mm <= 0 or depth_mm <= 0:
        raise ValueError("Bed width and depth must be positive.")

    source = []
    for index, point in enumerate(points):
        xyz = point.get("camera_xyz_m")
        if not isinstance(xyz, list) or len(xyz) != 3:
            raise ValueError(f"Corner {index + 1} does not have a valid 3D camera point.")
        source.append([float(v) * 1000.0 for v in xyz])

    source_mm = np.asarray(source, dtype=float)
    target_mm = np.asarray(
        [
            [origin_x_mm, origin_y_mm, 0.0],
            [origin_x_mm + width_mm, origin_y_mm, 0.0],
            [origin_x_mm + width_mm, origin_y_mm + depth_mm, 0.0],
            [origin_x_mm, origin_y_mm + depth_mm, 0.0],
        ],
        dtype=float,
    )

    rotation, translation = _rigid_transform(source_mm, target_mm)
    predicted = (rotation @ source_mm.T).T + translation
    errors = np.linalg.norm(predicted - target_mm, axis=1)
    rms = float(math.sqrt(float(np.mean(errors**2))))

    profile: dict[str, Any] = {
        "version": 1,
        "created_at_unix": int(time.time()),
        "camera": {
            "serial": camera_serial,
            "model": camera_model,
            "frame_width": int(frame_width),
            "frame_height": int(frame_height),
            "intrinsics": intrinsics,
        },
        "bed": {
            "origin_x_mm": float(origin_x_mm),
            "origin_y_mm": float(origin_y_mm),
            "width_mm": float(width_mm),
            "depth_mm": float(depth_mm),
            "corner_order": [
                "front_left",
                "front_right",
                "rear_right",
                "rear_left",
            ],
            "corners": points,
        },
        "camera_to_printer": {
            "rotation": rotation.tolist(),
            "translation_mm": translation.tolist(),
            "method": "four-point rigid Kabsch fit",
            "rms_corner_error_mm": round(rms, 4),
            "corner_errors_mm": [round(float(v), 4) for v in errors],
        },
        "nozzle_reference": None,
        "status": "valid",
    }
    return save_profile(profile)


def save_nozzle_reference(
    profile: dict[str, Any],
    *,
    pixel_u: float,
    pixel_v: float,
    camera_xyz_m: list[float],
) -> dict[str, Any]:
    printer_xyz = transform_camera_point(profile, camera_xyz_m)
    profile["nozzle_reference"] = {
        "pixel": [round(float(pixel_u), 3), round(float(pixel_v), 3)],
        "camera_xyz_m": [round(float(v), 6) for v in camera_xyz_m],
        "printer_xyz_mm": printer_xyz,
        "captured_at_unix": int(time.time()),
    }
    return save_profile(profile)


def save_surface_baseline(
    profile: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    baseline = {
        "captured_at_unix": int(time.time()),
        "grid": result.get("grid"),
        "sample_count": result.get("sample_count"),
        "mean_z_mm": result.get("mean_z_mm"),
        "rms_z_mm": result.get("rms_z_mm"),
        "min_z_mm": result.get("min_z_mm"),
        "max_z_mm": result.get("max_z_mm"),
        "peak_to_peak_mm": result.get("peak_to_peak_mm"),
        "samples": [
            {
                "u": sample.get("u"),
                "v": sample.get("v"),
                "x_mm": sample.get("x_mm"),
                "y_mm": sample.get("y_mm"),
                "z_mm": sample.get("z_mm"),
            }
            for sample in result.get("samples", [])
        ],
    }
    profile["surface_baseline"] = baseline
    return save_profile(profile)


def compare_surface_to_baseline(
    profile: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    baseline = profile.get("surface_baseline")
    if not baseline:
        result["baseline_available"] = False
        return result

    if baseline.get("grid") != result.get("grid"):
        result["baseline_available"] = True
        result["baseline_compatible"] = False
        return result

    baseline_samples = baseline.get("samples", [])
    current_samples = result.get("samples", [])
    if len(baseline_samples) != len(current_samples):
        result["baseline_available"] = True
        result["baseline_compatible"] = False
        return result

    deltas: list[float] = []
    for current, base in zip(current_samples, baseline_samples):
        delta = float(current["z_mm"]) - float(base["z_mm"])
        current["baseline_z_mm"] = round(float(base["z_mm"]), 4)
        current["delta_z_mm"] = round(delta, 4)
        deltas.append(delta)

    if not deltas:
        result["baseline_available"] = True
        result["baseline_compatible"] = False
        return result

    arr = np.asarray(deltas, dtype=float)
    positive = arr[arr > 0]
    result["baseline_available"] = True
    result["baseline_compatible"] = True
    result["deposition"] = {
        "mean_delta_z_mm": round(float(arr.mean()), 4),
        "rms_delta_z_mm": round(float(math.sqrt(float(np.mean(arr**2)))), 4),
        "min_delta_z_mm": round(float(arr.min()), 4),
        "max_delta_z_mm": round(float(arr.max()), 4),
        "positive_sample_count": int((arr > 0).sum()),
        "mean_positive_height_mm": (
            round(float(positive.mean()), 4) if positive.size else 0.0
        ),
    }
    return result


def analyze_surface(
    profile: dict[str, Any],
    sample_pixels: Callable[[list[tuple[float, float]]], list[dict[str, Any]]],
    *,
    columns: int = 12,
    rows: int = 9,
) -> dict[str, Any]:
    corners = profile.get("bed", {}).get("corners", [])
    if len(corners) != 4:
        raise ValueError("Bed-corner calibration is missing.")

    uv = np.asarray([[float(p["u"]), float(p["v"])] for p in corners], dtype=float)
    p00, p10, p11, p01 = uv

    requested_pixels: list[tuple[float, float]] = []
    for row in range(rows):
        ty = (row + 0.5) / rows
        left = (1.0 - ty) * p00 + ty * p01
        right = (1.0 - ty) * p10 + ty * p11

        for col in range(columns):
            tx = (col + 0.5) / columns
            pixel = (1.0 - tx) * left + tx * right
            requested_pixels.append((float(pixel[0]), float(pixel[1])))

    sensor_points = sample_pixels(requested_pixels)
    samples: list[dict[str, Any]] = []
    for sensor in sensor_points:
        if not sensor.get("valid", True):
            continue

        xyz = sensor.get("camera_xyz_m")
        if not xyz:
            continue

        printer_xyz = transform_camera_point(profile, xyz)
        samples.append(
            {
                "u": round(float(sensor["u"]), 2),
                "v": round(float(sensor["v"]), 2),
                "x_mm": printer_xyz[0],
                "y_mm": printer_xyz[1],
                "z_mm": printer_xyz[2],
                "depth_m": sensor.get("depth_m"),
            }
        )

    if not samples:
        raise ValueError("No valid depth samples were available inside the calibrated bed region.")

    z = np.asarray([float(s["z_mm"]) for s in samples], dtype=float)
    mean = float(z.mean())
    rms = float(math.sqrt(float(np.mean(z**2))))

    result = {
        "sample_count": len(samples),
        "grid": {"columns": columns, "rows": rows},
        "mean_z_mm": round(mean, 4),
        "rms_z_mm": round(rms, 4),
        "min_z_mm": round(float(z.min()), 4),
        "max_z_mm": round(float(z.max()), 4),
        "peak_to_peak_mm": round(float(z.max() - z.min()), 4),
        "samples": samples,
    }
    return compare_surface_to_baseline(profile, result)
