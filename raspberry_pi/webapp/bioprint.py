from __future__ import annotations

import math
from typing import Any

DEFAULT_ALGINATE_PROFILE: dict[str, Any] = {
    "name": "Sodium alginate - research baseline",
    "material": "sodium_alginate",
    "alginate_percent_wv": 3.0,
    "crosslinker": "calcium_chloride",
    "calcium_chloride_mM": 80.0,
    "crosslink_mode": "post_print",
    "syringe_inner_diameter_mm": 14.5,
    "needle_inner_diameter_mm": 0.60,
    "layer_height_mm": 0.30,
    "bead_width_mm": 0.80,
    "print_speed_mm_s": 4.0,
    "travel_speed_mm_s": 20.0,
    "infill_percent": 20.0,
    "perimeter_count": 1,
    "extrusion_multiplier": 1.0,
    "travel_lift_mm": 1.0,
    "temperature_mode": "ambient",
    "bed_temperature_c": 0.0,
    "hotend_temperature_c": 0.0,
    "support_strategy": "self_supporting",
}

SUPPORT_STRATEGIES = {
    "self_supporting",
    "support_bath",
    "manual_scaffold",
}


def syringe_area_mm2(inner_diameter_mm: float) -> float:
    if inner_diameter_mm <= 0:
        raise ValueError("Syringe inner diameter must be positive.")
    return math.pi * (inner_diameter_mm / 2.0) ** 2


def e_per_path_mm(
    *,
    bead_width_mm: float,
    layer_height_mm: float,
    syringe_inner_diameter_mm: float,
    extrusion_multiplier: float = 1.0,
) -> float:
    if bead_width_mm <= 0 or layer_height_mm <= 0:
        raise ValueError("Bead width and layer height must be positive.")
    if extrusion_multiplier <= 0:
        raise ValueError("Extrusion multiplier must be positive.")
    bead_area = bead_width_mm * layer_height_mm
    return bead_area / syringe_area_mm2(syringe_inner_diameter_mm) * extrusion_multiplier


def process_advisories(profile: dict[str, Any]) -> list[dict[str, str]]:
    advisories: list[dict[str, str]] = []

    alginate = float(profile.get("alginate_percent_wv", 0.0) or 0.0)
    layer = float(profile.get("layer_height_mm", 0.0) or 0.0)
    bead = float(profile.get("bead_width_mm", 0.0) or 0.0)
    needle = float(profile.get("needle_inner_diameter_mm", 0.0) or 0.0)
    speed = float(profile.get("print_speed_mm_s", 0.0) or 0.0)
    support = str(profile.get("support_strategy", "self_supporting"))
    crosslink = str(profile.get("crosslink_mode", "post_print"))
    temperature_mode = str(profile.get("temperature_mode", "ambient"))
    bed_temperature_c = float(profile.get("bed_temperature_c", 0.0) or 0.0)
    hotend_temperature_c = float(profile.get("hotend_temperature_c", 0.0) or 0.0)

    if not (0.5 <= alginate <= 8.0):
        advisories.append({
            "level": "warning",
            "code": "alginate_concentration",
            "message": "Alginate concentration is outside the broad research range expected by this profile. Validate rheology and printability experimentally.",
        })
    if needle > 0 and bead < needle * 0.75:
        advisories.append({
            "level": "warning",
            "code": "bead_vs_needle",
            "message": "Requested bead width is substantially smaller than the needle ID and may not be physically achievable.",
        })
    if layer > bead:
        advisories.append({
            "level": "warning",
            "code": "layer_vs_bead",
            "message": "Layer height exceeds bead width. Inter-layer contact may be poor.",
        })
    if speed > 12:
        advisories.append({
            "level": "warning",
            "code": "high_print_speed",
            "message": "Print speed is high for a research hydrogel baseline. Verify strand continuity before using this value.",
        })
    if support not in SUPPORT_STRATEGIES:
        advisories.append({
            "level": "error",
            "code": "support_strategy",
            "message": "Unknown support strategy.",
        })
    if crosslink not in {"post_print", "support_bath", "manual"}:
        advisories.append({
            "level": "error",
            "code": "crosslink_mode",
            "message": "Unknown crosslinking mode.",
        })
    if temperature_mode not in {"ambient", "heated_bed"}:
        advisories.append({
            "level": "error",
            "code": "temperature_mode",
            "message": "Unknown temperature mode.",
        })
    if hotend_temperature_c > 0:
        advisories.append({
            "level": "error",
            "code": "hotend_heating_disabled",
            "message": "Stock hotend heating is disabled for the syringe workflow. Use dedicated, validated syringe/nozzle temperature hardware before enabling material heating.",
        })
    if temperature_mode == "heated_bed" and not (15.0 <= bed_temperature_c <= 60.0):
        advisories.append({
            "level": "warning",
            "code": "bed_temperature",
            "message": "Requested bed temperature is outside the conservative 15–60 °C research planning range.",
        })

    return advisories


def build_preflight(
    *,
    model_size_mm: list[float],
    bounds_mm: dict[str, list[float]],
    estimated_volume_ml: float,
    syringe_capacity_ml: float,
    unsupported_ratio: float,
    support_strategy: str,
    e_steps_calibrated: bool,
    motor_direction_verified: bool,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str, *, blocking: bool = True) -> None:
        checks.append({
            "name": name,
            "ok": bool(ok),
            "blocking": bool(blocking),
            "message": message,
        })

    maxs = bounds_mm.get("max", [0, 0, 0])
    mins = bounds_mm.get("min", [0, 0, 0])
    inside = (
        len(maxs) >= 3 and len(mins) >= 3
        and mins[0] >= 0 and mins[1] >= 0 and mins[2] >= 0
        and maxs[0] <= 220 and maxs[1] <= 220 and maxs[2] <= 250
    )
    add("Workspace", inside, "Toolpath stays inside the configured X/Y/Z envelope." if inside else "Toolpath exceeds the configured printer workspace.")

    volume_ok = estimated_volume_ml <= max(0.0, syringe_capacity_ml * 0.90)
    add(
        "Syringe capacity",
        volume_ok,
        f"Estimated material {estimated_volume_ml:.3f} mL; usable planning limit {syringe_capacity_ml * 0.90:.3f} mL.",
    )

    supports_ok = unsupported_ratio <= 0.02 or support_strategy in {"support_bath", "manual_scaffold"}
    add(
        "Unsupported geometry",
        supports_ok,
        (
            f"Unsupported-path estimate {unsupported_ratio * 100:.1f}%. "
            + ("Selected support strategy accounts for this risk." if supports_ok else "Choose a support strategy or redesign the geometry.")
        ),
    )

    add(
        "E-steps calibration",
        e_steps_calibrated,
        "Experimental syringe E-steps calibration confirmed." if e_steps_calibrated else "Calibrate syringe E-steps before physical extrusion.",
    )
    add(
        "Extruder direction",
        motor_direction_verified,
        "Syringe motor direction verified." if motor_direction_verified else "Verify syringe motor direction before physical extrusion.",
    )

    ready = all(item["ok"] or not item["blocking"] for item in checks)
    return {
        "ready_for_physical_print": ready,
        "checks": checks,
        "model_size_mm": model_size_mm,
    }
