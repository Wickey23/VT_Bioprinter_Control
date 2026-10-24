#!/usr/bin/env python3
"""Offline sanity checks for VT Bioprinter calibration and G-code logic."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from webapp import calibration
from webapp import print_plan
from webapp import quality
from webapp import vision


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


def test_syringe_stl_slicer() -> None:
    # 10 x 10 x 1 mm ASCII STL box, sufficient to test layer intersection,
    # contour generation, infill, and syringe E conversion offline.
    stl = b"""solid box
facet normal 0 0 -1
 outer loop
  vertex 0 0 0
  vertex 10 10 0
  vertex 10 0 0
 endloop
endfacet
facet normal 0 0 -1
 outer loop
  vertex 0 0 0
  vertex 0 10 0
  vertex 10 10 0
 endloop
endfacet
facet normal 0 0 1
 outer loop
  vertex 0 0 1
  vertex 10 0 1
  vertex 10 10 1
 endloop
endfacet
facet normal 0 0 1
 outer loop
  vertex 0 0 1
  vertex 10 10 1
  vertex 0 10 1
 endloop
endfacet
facet normal 0 -1 0
 outer loop
  vertex 0 0 0
  vertex 10 0 0
  vertex 10 0 1
 endloop
endfacet
facet normal 0 -1 0
 outer loop
  vertex 0 0 0
  vertex 10 0 1
  vertex 0 0 1
 endloop
endfacet
facet normal 1 0 0
 outer loop
  vertex 10 0 0
  vertex 10 10 0
  vertex 10 10 1
 endloop
endfacet
facet normal 1 0 0
 outer loop
  vertex 10 0 0
  vertex 10 10 1
  vertex 10 0 1
 endloop
endfacet
facet normal 0 1 0
 outer loop
  vertex 10 10 0
  vertex 0 10 0
  vertex 0 10 1
 endloop
endfacet
facet normal 0 1 0
 outer loop
  vertex 10 10 0
  vertex 0 10 1
  vertex 10 10 1
 endloop
endfacet
facet normal -1 0 0
 outer loop
  vertex 0 10 0
  vertex 0 0 0
  vertex 0 0 1
 endloop
endfacet
facet normal -1 0 0
 outer loop
  vertex 0 10 0
  vertex 0 0 1
  vertex 0 10 1
 endloop
endfacet
endsolid box
"""
    with tempfile.TemporaryDirectory() as tmp:
        original = print_plan.ACTIVE_PLAN
        try:
            print_plan.ACTIVE_PLAN = Path(tmp) / "active.json"
            result = print_plan.slice_stl_to_syringe_gcode(
                stl,
                filename="box.stl",
                layer_height_mm=0.5,
                bead_width_mm=0.8,
                infill_percent=20.0,
                syringe_diameter_mm=14.5,
            )
        finally:
            print_plan.ACTIVE_PLAN = original

    summary = result["summary"]
    if int(summary["generated_layers"]) < 1:
        raise AssertionError("Expected at least one generated slicer layer")
    if float(summary["estimated_plunger_travel_mm"]) <= 0:
        raise AssertionError("Expected positive syringe plunger travel")
    if " E" not in result["gcode"]:
        raise AssertionError("Expected syringe E moves in generated G-code")


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


def test_quality_engine() -> None:
    plan = {
        "segments": [
            {
                "start": [0.0, 0.0, 1.0],
                "end": [10.0, 0.0, 1.0],
                "extruding": True,
            }
        ]
    }
    surface = {
        "baseline_compatible": True,
        "deposition": {"mean_delta_z_mm": 1.0},
        "samples": [
            {
                "u": 10.0,
                "v": 10.0,
                "x_mm": 5.0,
                "y_mm": 0.1,
                "z_mm": 1.0,
                "delta_z_mm": 1.0,
            }
        ],
    }
    result = quality.analyze_final_surface_quality(
        surface,
        plan,
        path_radius_mm=1.0,
        min_deposition_height_mm=0.1,
        height_tolerance_mm=0.2,
    )
    if result["advisory_status"] != "NORMAL":
        raise AssertionError("Expected NORMAL synthetic quality advisory")
    assert_close(float(result["coverage_percent"]), 100.0, 1e-9, "quality coverage")


def test_vision_tracker() -> None:
    frame = np.zeros((100, 120, 3), dtype=np.uint8)
    # Build a small asymmetric high-contrast pattern around (70, 45).
    frame[40:51, 65:76, :] = 40
    frame[42:49, 67:73, 0] = 230
    frame[43:48, 69:75, 1] = 180
    frame[45:50, 66:70, 2] = 120

    gray = (
        0.299 * frame[40:51, 65:76, 0]
        + 0.587 * frame[40:51, 65:76, 1]
        + 0.114 * frame[40:51, 65:76, 2]
    ).astype(np.uint8)

    template = {
        "size": 11,
        "u": 70.0,
        "v": 45.0,
        "pixels": gray.reshape(-1).astype(int).tolist(),
    }
    result = vision.track_template(
        frame,
        template,
        predicted_pixel=[68.0, 44.0],
        local_radius=20,
        coarse_stride=4,
    )
    assert_close(float(result["u"]), 70.0, 1.0, "vision tracker u")
    assert_close(float(result["v"]), 45.0, 1.0, "vision tracker v")


def main() -> int:
    tests = [
        ("rigid transform", test_rigid_transform),
        ("G-code parser", test_gcode_parser),
        ("syringe STL slicer", test_syringe_stl_slicer),
        ("projection math", test_projection_math),
        ("quality engine", test_quality_engine),
        ("vision tracker", test_vision_tracker),
    ]
    for name, test in tests:
        test()
        print(f"PASS: {name}")
    print("All offline controller self-tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
