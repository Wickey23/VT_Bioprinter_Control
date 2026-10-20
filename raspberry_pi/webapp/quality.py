from __future__ import annotations

import math
from typing import Any

import numpy as np


def _segment_arrays(plan: dict[str, Any]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    extruding = [s for s in plan.get("segments", []) if s.get("extruding")]
    if not extruding:
        raise ValueError("The active G-code plan has no extruding motion segments.")

    starts = np.asarray([[s["start"][0], s["start"][1]] for s in extruding], dtype=float)
    ends = np.asarray([[s["end"][0], s["end"][1]] for s in extruding], dtype=float)
    z = np.asarray([float(s["end"][2]) for s in extruding], dtype=float)
    return starts, ends, z


def _distances_to_segments(
    point_xy: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
) -> np.ndarray:
    vectors = ends - starts
    lengths_sq = np.sum(vectors * vectors, axis=1)
    safe = np.where(lengths_sq > 1e-12, lengths_sq, 1.0)
    t = np.sum((point_xy - starts) * vectors, axis=1) / safe
    t = np.clip(t, 0.0, 1.0)
    closest = starts + vectors * t[:, None]
    delta = closest - point_xy
    return np.sqrt(np.sum(delta * delta, axis=1))


def analyze_final_surface_quality(
    surface: dict[str, Any],
    plan: dict[str, Any],
    *,
    path_radius_mm: float = 2.0,
    min_deposition_height_mm: float = 0.10,
    height_tolerance_mm: float = 0.50,
) -> dict[str, Any]:
    if path_radius_mm <= 0:
        raise ValueError("Path radius must be positive.")
    if min_deposition_height_mm < 0:
        raise ValueError("Minimum deposition height cannot be negative.")
    if height_tolerance_mm <= 0:
        raise ValueError("Height tolerance must be positive.")

    if not surface.get("baseline_compatible") or not surface.get("deposition"):
        raise ValueError(
            "A compatible saved reference surface is required before final quality analysis."
        )

    starts, ends, segment_z = _segment_arrays(plan)

    classified: list[dict[str, Any]] = []
    expected_count = 0
    covered_count = 0
    missing_count = 0
    excess_count = 0
    background_count = 0
    height_errors: list[float] = []

    for sample in surface.get("samples", []):
        x = float(sample["x_mm"])
        y = float(sample["y_mm"])
        observed = float(sample.get("delta_z_mm", 0.0))

        distances = _distances_to_segments(np.asarray([x, y], dtype=float), starts, ends)
        within = distances <= path_radius_mm
        expected = bool(np.any(within))

        expected_z = None
        nearest_distance = float(distances.min()) if distances.size else float("inf")
        if expected:
            expected_count += 1
            expected_z = float(np.max(segment_z[within]))

        deposited = observed >= min_deposition_height_mm

        if expected and deposited:
            covered_count += 1
            height_error = observed - float(expected_z)
            height_errors.append(height_error)
            classification = (
                "within_tolerance"
                if abs(height_error) <= height_tolerance_mm
                else ("too_high" if height_error > 0 else "too_low")
            )
        elif expected and not deposited:
            missing_count += 1
            height_error = observed - float(expected_z)
            height_errors.append(height_error)
            classification = "missing"
        elif (not expected) and deposited:
            excess_count += 1
            height_error = None
            classification = "excess"
        else:
            background_count += 1
            height_error = None
            classification = "background"

        classified.append(
            {
                **sample,
                "expected_path": expected,
                "nearest_path_distance_mm": round(nearest_distance, 4),
                "expected_z_mm": round(expected_z, 4) if expected_z is not None else None,
                "observed_delta_z_mm": round(observed, 4),
                "height_error_mm": (
                    round(float(height_error), 4) if height_error is not None else None
                ),
                "classification": classification,
            }
        )

    coverage = (covered_count / expected_count * 100.0) if expected_count else None

    errors = np.asarray(height_errors, dtype=float) if height_errors else np.asarray([], dtype=float)
    mean_error = float(errors.mean()) if errors.size else None
    mean_abs_error = float(np.abs(errors).mean()) if errors.size else None
    rms_error = (
        float(math.sqrt(float(np.mean(errors**2)))) if errors.size else None
    )

    within_count = sum(1 for p in classified if p["classification"] == "within_tolerance")
    tolerance_rate = (
        within_count / expected_count * 100.0 if expected_count else None
    )

    advisory_reasons: list[str] = []
    if expected_count == 0:
        advisory_status = "INSUFFICIENT_DATA"
        advisory_reasons.append("No sampled points intersected the expected G-code path.")
    elif missing_count > 0 or excess_count > 0:
        advisory_status = "FAULT"
        if missing_count > 0:
            advisory_reasons.append(f"{missing_count} expected-path samples had no detected deposition.")
        if excess_count > 0:
            advisory_reasons.append(f"{excess_count} off-path samples showed deposition above threshold.")
    elif within_count < expected_count:
        advisory_status = "WARNING"
        advisory_reasons.append(
            f"{expected_count - within_count} expected-path samples exceeded the user-selected height tolerance."
        )
    else:
        advisory_status = "NORMAL"
        advisory_reasons.append("All sampled expected-path points were within the selected tolerance.")

    return {
        "mode": "FINAL_SURFACE_OBSERVE",
        "advisory_status": advisory_status,
        "advisory_reasons": advisory_reasons,
        "settings": {
            "path_radius_mm": float(path_radius_mm),
            "min_deposition_height_mm": float(min_deposition_height_mm),
            "height_tolerance_mm": float(height_tolerance_mm),
        },
        "sample_count": len(classified),
        "expected_path_samples": expected_count,
        "covered_path_samples": covered_count,
        "missing_path_samples": missing_count,
        "excess_off_path_samples": excess_count,
        "background_samples": background_count,
        "within_tolerance_samples": within_count,
        "coverage_percent": round(coverage, 2) if coverage is not None else None,
        "within_tolerance_percent": (
            round(tolerance_rate, 2) if tolerance_rate is not None else None
        ),
        "mean_height_error_mm": (
            round(mean_error, 4) if mean_error is not None else None
        ),
        "mean_abs_height_error_mm": (
            round(mean_abs_error, 4) if mean_abs_error is not None else None
        ),
        "rms_height_error_mm": (
            round(rms_error, 4) if rms_error is not None else None
        ),
        "points": classified,
        "note": (
            "Observe-only coarse final-surface comparison. G-code Z is used as an "
            "expected height proxy and must be validated for the specific bioink, "
            "layer model, camera geometry, and nozzle process before decisions are automated. "
            "The advisory status is informational only and never commands the printer."
        ),
    }
