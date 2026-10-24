from __future__ import annotations

import json
import math
import os
import struct
import time
from pathlib import Path
from typing import Any

import numpy as np

from webapp.bioprint import build_preflight, e_per_path_mm as syringe_e_per_path_mm, process_advisories

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
    has_explicit_layers = any(
        line.strip().upper().startswith(";LAYER:") for line in text.splitlines()
    )

    x = y = z = e = 0.0
    feed = 0.0
    layer = 0
    last_z = z

    segments: list[dict[str, Any]] = []
    total_motion = 0.0
    total_extruding_motion = 0.0
    extrusion_delta_total = 0.0
    estimated_time_seconds = 0.0

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

        if not has_explicit_layers and abs(z - last_z) > 1e-6:
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
        if length > 1e-9 and feed > 1e-9:
            estimated_time_seconds += length / feed * 60.0
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
        "estimated_time_seconds": round(estimated_time_seconds, 2),
        "bounds_mm": {
            "min": [round(float(v), 4) for v in mins],
            "max": [round(float(v), 4) for v in maxs],
        },
        "segments": segments,
        "source_gcode": text,
    }
    return save_plan(plan)



def _parse_stl_triangles(data: bytes) -> np.ndarray:
    """Parse binary or ASCII STL bytes into an (N, 3, 3) float array."""
    if len(data) < 15:
        raise ValueError("STL file is too small.")

    # Binary STL has an 80-byte header, uint32 triangle count, then 50 bytes/triangle.
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        expected = 84 + count * 50
        if count > 0 and expected == len(data):
            triangles = np.empty((count, 3, 3), dtype=float)
            offset = 84
            for i in range(count):
                values = struct.unpack_from("<12fH", data, offset)
                triangles[i] = np.asarray(values[3:12], dtype=float).reshape(3, 3)
                offset += 50
            return triangles

    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("STL is neither valid binary STL nor UTF-8 ASCII STL.") from exc

    vertices: list[list[float]] = []
    for raw in text.splitlines():
        parts = raw.strip().split()
        if len(parts) == 4 and parts[0].lower() == "vertex":
            try:
                vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
            except ValueError:
                continue
    if len(vertices) < 3 or len(vertices) % 3:
        raise ValueError("ASCII STL did not contain complete triangle vertices.")
    return np.asarray(vertices, dtype=float).reshape(-1, 3, 3)


def _triangle_plane_segment(triangle: np.ndarray, z: float, eps: float = 1e-7) -> tuple[np.ndarray, np.ndarray] | None:
    points: list[np.ndarray] = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a = triangle[i]
        b = triangle[j]
        da = float(a[2] - z)
        db = float(b[2] - z)

        if abs(da) <= eps and abs(db) <= eps:
            # Coplanar edges are ignored; neighboring triangles provide the
            # contour at ordinary layer planes.
            continue
        if abs(da) <= eps:
            points.append(a[:2].copy())
            continue
        if abs(db) <= eps:
            points.append(b[:2].copy())
            continue
        if da * db < 0:
            t = da / (da - db)
            points.append((a[:2] + t * (b[:2] - a[:2])).copy())

    unique: list[np.ndarray] = []
    for point in points:
        if not any(float(np.linalg.norm(point - old)) < 1e-6 for old in unique):
            unique.append(point)
    if len(unique) != 2:
        return None
    if float(np.linalg.norm(unique[1] - unique[0])) < 1e-6:
        return None
    return unique[0], unique[1]


def _stitch_segments(
    segments: list[tuple[np.ndarray, np.ndarray]],
    *,
    tolerance_mm: float = 0.08,
) -> list[list[np.ndarray]]:
    remaining = [(a.copy(), b.copy()) for a, b in segments]
    paths: list[list[np.ndarray]] = []

    while remaining:
        a, b = remaining.pop()
        path = [a, b]
        changed = True
        while changed and remaining:
            changed = False
            end = path[-1]
            start = path[0]
            for idx, (p, q) in enumerate(remaining):
                if float(np.linalg.norm(end - p)) <= tolerance_mm:
                    path.append(q)
                elif float(np.linalg.norm(end - q)) <= tolerance_mm:
                    path.append(p)
                elif float(np.linalg.norm(start - q)) <= tolerance_mm:
                    path.insert(0, p)
                elif float(np.linalg.norm(start - p)) <= tolerance_mm:
                    path.insert(0, q)
                else:
                    continue
                remaining.pop(idx)
                changed = True
                break

        if len(path) >= 3 and float(np.linalg.norm(path[-1] - path[0])) <= tolerance_mm:
            path[-1] = path[0].copy()
        paths.append(path)

    return paths


def _hatch_segments(
    paths: list[list[np.ndarray]],
    *,
    horizontal: bool,
    spacing_mm: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    edges: list[tuple[np.ndarray, np.ndarray]] = []
    for path in paths:
        if len(path) < 3:
            continue
        closed = path
        if float(np.linalg.norm(path[-1] - path[0])) > 0.1:
            closed = path + [path[0]]
        edges.extend((closed[i], closed[i + 1]) for i in range(len(closed) - 1))

    if not edges:
        return []

    coords = [float(point[1] if horizontal else point[0]) for edge in edges for point in edge]
    lo, hi = min(coords), max(coords)
    if hi - lo < spacing_mm:
        return []

    result: list[tuple[np.ndarray, np.ndarray]] = []
    cursor = lo + spacing_mm
    while cursor < hi - 1e-6:
        crossings: list[float] = []
        for a, b in edges:
            primary_a = float(a[1] if horizontal else a[0])
            primary_b = float(b[1] if horizontal else b[0])
            if abs(primary_b - primary_a) < 1e-9:
                continue
            # Half-open crossing rule avoids double-counting polygon vertices.
            if not ((primary_a <= cursor < primary_b) or (primary_b <= cursor < primary_a)):
                continue
            t = (cursor - primary_a) / (primary_b - primary_a)
            secondary_a = float(a[0] if horizontal else a[1])
            secondary_b = float(b[0] if horizontal else b[1])
            crossings.append(secondary_a + t * (secondary_b - secondary_a))

        crossings.sort()
        for i in range(0, len(crossings) - 1, 2):
            p0, p1 = crossings[i], crossings[i + 1]
            if p1 - p0 < 0.05:
                continue
            if horizontal:
                result.append((np.asarray([p0, cursor]), np.asarray([p1, cursor])))
            else:
                result.append((np.asarray([cursor, p0]), np.asarray([cursor, p1])))
        cursor += spacing_mm
    return result



def _point_in_closed_path(point: np.ndarray, path: list[np.ndarray]) -> bool:
    if len(path) < 3:
        return False
    x, y = float(point[0]), float(point[1])
    inside = False
    pts = path if float(np.linalg.norm(path[-1] - path[0])) <= 0.1 else path + [path[0]]
    for i in range(len(pts) - 1):
        x1, y1 = float(pts[i][0]), float(pts[i][1])
        x2, y2 = float(pts[i + 1][0]), float(pts[i + 1][1])
        if (y1 > y) == (y2 > y):
            continue
        denom = y2 - y1
        if abs(denom) < 1e-12:
            continue
        x_cross = x1 + (y - y1) * (x2 - x1) / denom
        if x < x_cross:
            inside = not inside
    return inside


def _distance_point_to_segment(point: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    vector = b - a
    length_sq = float(np.dot(vector, vector))
    if length_sq <= 1e-12:
        return float(np.linalg.norm(point - a))
    t = float(np.dot(point - a, vector) / length_sq)
    t = max(0.0, min(1.0, t))
    closest = a + t * vector
    return float(np.linalg.norm(point - closest))


def _point_in_paths(
    point: np.ndarray,
    paths: list[list[np.ndarray]],
    *,
    boundary_tolerance_mm: float = 0.65,
) -> bool:
    # A contour deposited directly above the previous contour is supported even
    # though a mathematical point-in-polygon test may classify a boundary point
    # as outside. Treat points close to the previous layer's path as supported,
    # then use even/odd fill for interior support.
    for path in paths:
        if len(path) < 2:
            continue
        closed = path if float(np.linalg.norm(path[-1] - path[0])) <= 0.1 else path + [path[0]]
        for a, b in zip(closed[:-1], closed[1:]):
            if _distance_point_to_segment(point, a, b) <= boundary_tolerance_mm:
                return True
    return sum(1 for path in paths if _point_in_closed_path(point, path)) % 2 == 1


def _estimate_unsupported_ratio(
    previous_paths: list[list[np.ndarray]],
    current_paths: list[list[np.ndarray]],
) -> float:
    if not current_paths:
        return 0.0
    if not previous_paths:
        return 0.0

    total = 0
    unsupported = 0
    for path in current_paths:
        if len(path) < 2:
            continue
        for a, b in zip(path[:-1], path[1:]):
            length = float(np.linalg.norm(b - a))
            samples = max(1, min(8, int(math.ceil(length / 2.0))))
            for j in range(samples):
                t = (j + 0.5) / samples
                p = a + t * (b - a)
                total += 1
                if not _point_in_paths(p, previous_paths):
                    unsupported += 1
    return unsupported / total if total else 0.0


def slice_stl_to_syringe_gcode(
    stl_data: bytes,
    *,
    filename: str,
    layer_height_mm: float = 0.5,
    bead_width_mm: float = 0.8,
    infill_percent: float = 20.0,
    syringe_diameter_mm: float = 14.5,
    needle_inner_diameter_mm: float = 0.60,
    alginate_percent_wv: float = 3.0,
    calcium_chloride_mM: float = 80.0,
    crosslink_mode: str = "post_print",
    support_strategy: str = "self_supporting",
    temperature_mode: str = "ambient",
    bed_temperature_c: float = 0.0,
    syringe_capacity_ml: float = 10.0,
    extrusion_multiplier: float = 1.0,
    travel_lift_mm: float = 1.0,
    print_feed_mm_min: int = 240,
    travel_feed_mm_min: int = 1200,
    bed_center_x_mm: float = 110.0,
    bed_center_y_mm: float = 110.0,
    e_steps_calibrated: bool = False,
    motor_direction_verified: bool = False,
) -> dict[str, Any]:
    if not (0.05 <= layer_height_mm <= 5.0):
        raise ValueError("Layer height must be between 0.05 and 5 mm.")
    if not (0.05 <= bead_width_mm <= 10.0):
        raise ValueError("Bead width must be between 0.05 and 10 mm.")
    if not (0.0 <= infill_percent <= 100.0):
        raise ValueError("Infill must be between 0 and 100%.")
    if not (1.0 <= syringe_diameter_mm <= 50.0):
        raise ValueError("Syringe inner diameter must be between 1 and 50 mm.")
    if not (0.05 <= needle_inner_diameter_mm <= 5.0):
        raise ValueError("Needle inner diameter must be between 0.05 and 5 mm.")
    if not (0.1 <= syringe_capacity_ml <= 100.0):
        raise ValueError("Syringe capacity must be between 0.1 and 100 mL.")
    if not (0.1 <= extrusion_multiplier <= 5.0):
        raise ValueError("Extrusion multiplier must be between 0.1 and 5.")
    if not (0.0 <= travel_lift_mm <= 10.0):
        raise ValueError("Travel lift must be between 0 and 10 mm.")
    if support_strategy not in {"self_supporting", "support_bath", "manual_scaffold"}:
        raise ValueError("Unsupported support strategy.")
    if crosslink_mode not in {"post_print", "support_bath", "manual"}:
        raise ValueError("Unsupported crosslinking mode.")
    if temperature_mode not in {"ambient", "heated_bed"}:
        raise ValueError("Unsupported temperature mode.")
    if not (0.0 <= bed_temperature_c <= 60.0):
        raise ValueError("Bed temperature must be between 0 and 60 °C.")

    triangles = _parse_stl_triangles(stl_data)
    if triangles.shape[0] > 300_000:
        raise ValueError("STL has too many triangles for the Raspberry Pi slicer.")

    points = triangles.reshape(-1, 3)
    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    size = maxs - mins
    if float(size[0]) > 180 or float(size[1]) > 180:
        raise ValueError("Model exceeds the conservative 180 × 180 mm slicer workspace.")
    if float(size[2]) <= 0 or float(size[2]) > 230:
        raise ValueError("Model Z height must be greater than 0 and at most 230 mm.")

    offset = np.asarray(
        [
            bed_center_x_mm - float((mins[0] + maxs[0]) / 2.0),
            bed_center_y_mm - float((mins[1] + maxs[1]) / 2.0),
            -float(mins[2]),
        ]
    )
    triangles = triangles + offset

    max_z = float(size[2])
    layer_count = max(1, int(math.ceil(max_z / layer_height_mm)))
    if layer_count > 600:
        raise ValueError("Too many layers; increase layer height.")

    profile = {
        "material": "sodium_alginate",
        "alginate_percent_wv": float(alginate_percent_wv),
        "crosslinker": "calcium_chloride",
        "calcium_chloride_mM": float(calcium_chloride_mM),
        "crosslink_mode": crosslink_mode,
        "support_strategy": support_strategy,
        "syringe_inner_diameter_mm": float(syringe_diameter_mm),
        "syringe_capacity_ml": float(syringe_capacity_ml),
        "needle_inner_diameter_mm": float(needle_inner_diameter_mm),
        "layer_height_mm": float(layer_height_mm),
        "bead_width_mm": float(bead_width_mm),
        "infill_percent": float(infill_percent),
        "print_speed_mm_s": float(print_feed_mm_min) / 60.0,
        "travel_speed_mm_s": float(travel_feed_mm_min) / 60.0,
        "extrusion_multiplier": float(extrusion_multiplier),
        "travel_lift_mm": float(travel_lift_mm),
        "temperature_mode": temperature_mode,
        "bed_temperature_c": float(bed_temperature_c),
        "hotend_temperature_c": 0.0,
    }
    advisories = process_advisories(profile)

    syringe_area_mm2 = math.pi * (syringe_diameter_mm / 2.0) ** 2
    e_per_path_mm = syringe_e_per_path_mm(
        bead_width_mm=bead_width_mm,
        layer_height_mm=layer_height_mm,
        syringe_inner_diameter_mm=syringe_diameter_mm,
        extrusion_multiplier=extrusion_multiplier,
    )

    infill_spacing = None
    if infill_percent > 0:
        infill_spacing = bead_width_mm / max(infill_percent / 100.0, 0.01)
        infill_spacing = max(bead_width_mm, infill_spacing)

    lines = [
        "; VT Bioprinter alginate syringe slicer output",
        f"; Source: {filename}",
        "; E is syringe plunger travel in mm, NOT filament length.",
        "; Physical execution requires verified motor direction and experimentally calibrated E-steps.",
        f"; material=sodium_alginate",
        f"; alginate_percent_wv={alginate_percent_wv:.3f}",
        f"; crosslinker=calcium_chloride",
        f"; calcium_chloride_mM={calcium_chloride_mM:.3f}",
        f"; crosslink_mode={crosslink_mode}",
        f"; support_strategy={support_strategy}",
        f"; temperature_mode={temperature_mode}",
        f"; bed_temperature_c={bed_temperature_c:.1f}",
        f"; hotend_temperature_c=0.0",
        f"; needle_inner_diameter_mm={needle_inner_diameter_mm:.4f}",
        f"; layer_height_mm={layer_height_mm:.4f}",
        f"; bead_width_mm={bead_width_mm:.4f}",
        f"; infill_percent={infill_percent:.2f}",
        f"; syringe_inner_diameter_mm={syringe_diameter_mm:.4f}",
        f"; syringe_capacity_ml={syringe_capacity_ml:.4f}",
        f"; extrusion_multiplier={extrusion_multiplier:.4f}",
        f"; e_per_xy_mm={e_per_path_mm:.9f}",
        "G90",
        "M83",
        "M104 S0",
        ("M140 S0" if temperature_mode == "ambient" else f"M140 S{bed_temperature_c:.1f}"),
        ("M140 S0" if temperature_mode == "ambient" else f"M190 S{bed_temperature_c:.1f}"),
        "M302 S0",
        "G28",
        "M400",
        "G0 Z10 F300",
    ]

    total_path_mm = 0.0
    total_e_mm = 0.0
    generated_layers = 0
    contour_count = 0
    infill_count = 0
    layer_summaries: list[dict[str, Any]] = []
    previous_paths: list[list[np.ndarray]] = []
    unsupported_weighted = 0.0
    unsupported_samples_weight = 0.0

    for layer_index in range(layer_count):
        z_model = min(max_z - 1e-5, (layer_index + 1) * layer_height_mm)
        z = max(layer_height_mm, z_model)
        raw_segments: list[tuple[np.ndarray, np.ndarray]] = []
        for triangle in triangles:
            segment = _triangle_plane_segment(triangle, z)
            if segment is not None:
                raw_segments.append(segment)
        if not raw_segments:
            continue

        paths = _stitch_segments(raw_segments)
        usable_paths = [path for path in paths if len(path) >= 2]
        if not usable_paths:
            continue

        unsupported_ratio = _estimate_unsupported_ratio(previous_paths, usable_paths) if generated_layers else 0.0
        layer_length_estimate = sum(
            float(np.linalg.norm(b - a))
            for path in usable_paths
            for a, b in zip(path[:-1], path[1:])
        )
        unsupported_weighted += unsupported_ratio * max(layer_length_estimate, 1.0)
        unsupported_samples_weight += max(layer_length_estimate, 1.0)

        lines.append(f";LAYER:{generated_layers}")
        lines.append(f"; unsupported_ratio={unsupported_ratio:.5f}")
        lines.append(f"G0 Z{z:.4f} F300")
        generated_layers += 1
        layer_contours = 0
        layer_infill = 0
        layer_path = 0.0
        layer_e = 0.0

        def travel_to(point: np.ndarray) -> None:
            # Keep travel Z-lift explicit in the generated plan. For soft
            # hydrogels, a modest lift reduces dragging across deposited strands.
            if travel_lift_mm > 0:
                lines.append(f"G0 Z{z + travel_lift_mm:.4f} F300")
            lines.append(f"G0 X{float(point[0]):.4f} Y{float(point[1]):.4f} F{travel_feed_mm_min}")
            if travel_lift_mm > 0:
                lines.append(f"G0 Z{z:.4f} F300")

        def emit_path(path: list[np.ndarray]) -> None:
            nonlocal total_path_mm, total_e_mm, contour_count, layer_contours, layer_path, layer_e
            start = path[0]
            travel_to(start)
            for point in path[1:]:
                prev = start
                length = float(np.linalg.norm(point - prev))
                if length <= 1e-6:
                    start = point
                    continue
                e = length * e_per_path_mm
                lines.append(
                    f"G1 X{float(point[0]):.4f} Y{float(point[1]):.4f} "
                    f"E{e:.7f} F{print_feed_mm_min}"
                )
                total_path_mm += length
                total_e_mm += e
                layer_path += length
                layer_e += e
                contour_count += 1
                layer_contours += 1
                start = point

        for path in usable_paths:
            emit_path(path)

        if infill_spacing is not None:
            hatch = _hatch_segments(
                usable_paths,
                horizontal=(generated_layers % 2 == 1),
                spacing_mm=infill_spacing,
            )
            for a, b in hatch:
                length = float(np.linalg.norm(b - a))
                if length <= 1e-6:
                    continue
                e = length * e_per_path_mm
                travel_to(a)
                lines.append(
                    f"G1 X{float(b[0]):.4f} Y{float(b[1]):.4f} "
                    f"E{e:.7f} F{print_feed_mm_min}"
                )
                total_path_mm += length
                total_e_mm += e
                layer_path += length
                layer_e += e
                infill_count += 1
                layer_infill += 1

        layer_summaries.append({
            "layer": generated_layers - 1,
            "z_mm": round(z, 5),
            "unsupported_ratio": round(unsupported_ratio, 5),
            "contour_segments": layer_contours,
            "infill_segments": layer_infill,
            "deposition_path_mm": round(layer_path, 4),
            "plunger_travel_mm": round(layer_e, 6),
        })
        previous_paths = usable_paths

    if generated_layers == 0:
        raise ValueError("No printable STL cross-sections were generated.")

    lines.extend(
        [
            "M400",
            "G0 Z10 F300",
            f"G0 X{bed_center_x_mm:.3f} Y{bed_center_y_mm:.3f} F{travel_feed_mm_min}",
            "M400",
            "M114",
            "; End alginate syringe-sliced plan",
        ]
    )
    gcode = "\n".join(lines) + "\n"
    output_name = Path(filename).stem + "_alginate_syringe.gcode"
    plan = parse_gcode(gcode, output_name)

    estimated_volume_ml = total_e_mm * syringe_area_mm2 / 1000.0
    unsupported_ratio = unsupported_weighted / unsupported_samples_weight if unsupported_samples_weight else 0.0
    preflight = build_preflight(
        model_size_mm=[round(float(v), 4) for v in size],
        bounds_mm=plan["bounds_mm"],
        estimated_volume_ml=estimated_volume_ml,
        syringe_capacity_ml=syringe_capacity_ml,
        unsupported_ratio=unsupported_ratio,
        support_strategy=support_strategy,
        e_steps_calibrated=e_steps_calibrated,
        motor_direction_verified=motor_direction_verified,
    )

    plan["slicer"] = {
        "engine": "VT Bioprinter research slicer",
        "source_filename": filename,
        "triangle_count": int(triangles.shape[0]),
        "model_size_mm": [round(float(v), 4) for v in size],
        "material_profile": profile,
        "process_advisories": advisories,
        "layer_height_mm": round(layer_height_mm, 5),
        "bead_width_mm": round(bead_width_mm, 5),
        "infill_percent": round(infill_percent, 3),
        "syringe_diameter_mm": round(syringe_diameter_mm, 5),
        "needle_inner_diameter_mm": round(needle_inner_diameter_mm, 5),
        "e_per_xy_mm": round(e_per_path_mm, 9),
        "generated_layers": generated_layers,
        "contour_segments": contour_count,
        "infill_segments": infill_count,
        "estimated_plunger_travel_mm": round(total_e_mm, 6),
        "estimated_volume_ml": round(estimated_volume_ml, 6),
        "unsupported_path_ratio": round(unsupported_ratio, 6),
        "support_strategy": support_strategy,
        "crosslink_mode": crosslink_mode,
        "temperature_mode": temperature_mode,
        "bed_temperature_c": round(float(bed_temperature_c), 2),
        "hotend_temperature_c": 0.0,
        "layer_summaries": layer_summaries,
        "preflight": preflight,
    }
    save_plan(plan)
    return {
        "filename": output_name,
        "gcode": gcode,
        "plan": plan,
        "summary": plan["slicer"],
        "preflight": preflight,
        "advisories": advisories,
    }


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
