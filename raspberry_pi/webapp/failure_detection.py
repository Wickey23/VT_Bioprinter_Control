from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from webapp.quality import analyze_final_surface_quality

DATA_DIR = Path(
    os.environ.get(
        "VT_BIOPRINTER_DATA_DIR",
        Path.home() / ".local" / "share" / "vt-bioprinter",
    )
) / "failure-detection"
OBSERVATIONS = DATA_DIR / "observations.jsonl"


def classify_quality(result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("advisory_status") or "INSUFFICIENT_DATA")
    missing = int(result.get("missing_path_samples") or 0)
    excess = int(result.get("excess_off_path_samples") or 0)
    mean_error = result.get("mean_height_error_mm")
    coverage = result.get("coverage_percent")
    tolerance = result.get("within_tolerance_percent")

    failure_type = None
    message = "Observed deposition is consistent with the sampled expected path."

    if status == "FAULT":
        if missing > 0 and missing >= excess:
            failure_type = "MISSING_OR_UNDER_EXTRUSION"
            message = "Expected-path samples are missing deposited material."
        elif excess > 0:
            failure_type = "OOZE_OR_OFF_PATH_DEPOSITION"
            message = "Material was detected away from the expected toolpath."
        else:
            failure_type = "GEOMETRY_MISMATCH"
            message = "Observed geometry differs from the expected print path."
    elif status == "WARNING":
        if isinstance(mean_error, (int, float)) and mean_error < 0:
            failure_type = "LOW_BEAD_OR_LAYER"
            message = "Observed deposition is lower than the expected layer height."
        elif isinstance(mean_error, (int, float)) and mean_error > 0:
            failure_type = "HIGH_BEAD_OR_BLOB"
            message = "Observed deposition is higher than the expected layer height."
        else:
            failure_type = "HEIGHT_VARIATION"
            message = "Some expected-path samples exceed the configured height tolerance."
    elif status == "INSUFFICIENT_DATA":
        message = "The camera did not obtain enough expected-path samples for a print-health decision."

    return {
        "available": status != "INSUFFICIENT_DATA",
        "status": status,
        "failure_type": failure_type,
        "message": message,
        "metrics": {
            "coverage_percent": coverage,
            "within_tolerance_percent": tolerance,
            "missing_path_samples": missing,
            "excess_off_path_samples": excess,
            "mean_height_error_mm": mean_error,
            "rms_height_error_mm": result.get("rms_height_error_mm"),
        },
    }


def evaluate_layer(
    *,
    surface: dict[str, Any],
    plan: dict[str, Any],
    current_layer: int,
    path_radius_mm: float = 2.0,
    min_deposition_height_mm: float = 0.10,
    height_tolerance_mm: float = 0.50,
) -> tuple[dict[str, Any], dict[str, Any]]:
    partial_plan = {
        **plan,
        "segments": [
            segment
            for segment in plan.get("segments", [])
            if bool(segment.get("extruding"))
            and int(segment.get("layer", 0)) <= int(current_layer)
        ],
    }
    if not partial_plan["segments"]:
        raise ValueError("No expected extrusion segments are available for the completed layer.")

    quality = analyze_final_surface_quality(
        surface,
        partial_plan,
        path_radius_mm=path_radius_mm,
        min_deposition_height_mm=min_deposition_height_mm,
        height_tolerance_mm=height_tolerance_mm,
    )
    assessment = classify_quality(quality)
    assessment["layer"] = int(current_layer)
    return assessment, quality


def save_training_frames(layer: int, rgb_jpeg: bytes, depth_jpeg: bytes) -> tuple[str, str]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time() * 1000)
    rgb_path = DATA_DIR / f"layer-{int(layer):04d}-{stamp}-rgb.jpg"
    depth_path = DATA_DIR / f"layer-{int(layer):04d}-{stamp}-depth.jpg"
    rgb_path.write_bytes(rgb_jpeg)
    depth_path.write_bytes(depth_jpeg)
    return str(rgb_path), str(depth_path)


def save_observation(
    *,
    layer: int,
    assessment: dict[str, Any],
    quality: dict[str, Any],
    rgb_path: str | None = None,
    depth_path: str | None = None,
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp_unix": int(time.time()),
        "layer": int(layer),
        "assessment": assessment,
        "quality": {key: value for key, value in quality.items() if key != "points"},
        "rgb_path": rgb_path,
        "depth_path": depth_path,
        "label_source": "heuristic_observer",
        "human_label": None,
    }
    with OBSERVATIONS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
