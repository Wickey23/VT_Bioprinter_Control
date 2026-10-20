#!/usr/bin/env python3
"""Offline sanity checks for VT Bioprinter calibration and G-code logic."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from webapp import calibration
from webapp import print_plan


def assert_close(actual: float, expected: float, tol: float, label: str) -> None:
    if abs(actual - expected) > tol:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def test_rigid_transform() -> None:
    source = np.asarray(
        [
            [0.0, 0.0, 500.0],
            [220.0, 0.0, 500.0],
            [220.0, 220.0, 500.0],
            [0.0, 220.0, 500.0],
        ]
    )
    target = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [220.0, 0.0, 0.0],
            [220.0, 220.0, 0.0],
            [0.0, 220.0, 0.0],
        ]
    )
    rotation, translation = calibration._rigid_transform(source, target)
    predicted = (rotation @ source.T).T + translation
    error = np.sqrt(np.mean(np.sum((predicted - target) ** 2, axis=1)))
    assert_close(float(error), 0.0, 1e-8, "rigid transform RMS")


def test_gcode_parser() -> None:
    sample = """G90
M82
G92 E0
G0 X0 Y0 Z0.2 F1200
G1 X10 Y0 E1 F300
G1 X10 Y10 E2
G1 X0 Y10 E3
G1 X0 Y0 E4
"""
    with tempfile.TemporaryDirectory() as tmp:
        original = print_plan.ACTIVE_PLAN
        try:
            print_plan.ACTIVE_PLAN = Path(tmp) / "active.json"
            plan = print_plan.parse_gcode(sample, "self-test.gcode")
        finally:
            print_plan.ACTIVE_PLAN = original

    if plan["extruding_segment_count"] != 4:
        raise AssertionError("Expected 4 extruding segments")
    assert_close(float(plan["extruding_motion_mm"]), 40.0, 1e-5, "extruding path")


def test_projection_math() -> None:
    profile = {
        "camera": {
            "frame_width": 640,
            "frame_height": 480,
            "intrinsics": {
                "width": 640,
                "height": 480,
                "fx": 600.0,
                "fy": 600.0,
                "ppx": 320.0,
                "ppy": 240.0,
            },
        },
        "camera_to_printer": {
            "rotation": np.eye(3).tolist(),
            "translation_mm": [0.0, 0.0, -500.0],
        },
    }
    camera = print_plan.printer_to_camera(profile, [0.0, 0.0, 0.0])
    assert_close(camera[2], 0.5, 1e-9, "printer-to-camera Z")
    pixel = print_plan.project_camera_point(profile, camera)
    if pixel is None:
        raise AssertionError("Expected projected center pixel")
    assert_close(pixel[0], 320.0, 1e-9, "projected u")
    assert_close(pixel[1], 240.0, 1e-9, "projected v")


def main() -> int:
    tests = [
        ("rigid transform", test_rigid_transform),
        ("G-code parser", test_gcode_parser),
        ("projection math", test_projection_math),
    ]
    for name, test in tests:
        test()
        print(f"PASS: {name}")
    print("All offline controller self-tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
