from __future__ import annotations

from typing import Any

import numpy as np


def _grayscale(frame_rgb: np.ndarray) -> np.ndarray:
    if frame_rgb.ndim != 3 or frame_rgb.shape[2] < 3:
        raise ValueError("Expected an RGB camera frame.")
    return (
        0.299 * frame_rgb[:, :, 0]
        + 0.587 * frame_rgb[:, :, 1]
        + 0.114 * frame_rgb[:, :, 2]
    ).astype(np.float32)


def _template_array(template: dict[str, Any]) -> np.ndarray:
    size = int(template.get("size", 0))
    pixels = template.get("pixels")
    if size < 9 or size % 2 == 0 or not isinstance(pixels, list):
        raise ValueError("Saved nozzle template is invalid.")
    if len(pixels) != size * size:
        raise ValueError("Saved nozzle template pixel count does not match its size.")
    return np.asarray(pixels, dtype=np.float32).reshape((size, size))


def _correlation(patch: np.ndarray, template_centered: np.ndarray, template_norm: float) -> float:
    candidate = patch.astype(np.float32)
    candidate -= float(candidate.mean())
    norm = float(np.linalg.norm(candidate))
    if norm <= 1e-9 or template_norm <= 1e-9:
        return -1.0
    return float(np.sum(candidate * template_centered) / (norm * template_norm))


def _search(
    gray: np.ndarray,
    template: np.ndarray,
    *,
    center: tuple[float, float] | None,
    radius: int | None,
    stride: int,
) -> tuple[int, int, float]:
    height, width = gray.shape
    size = template.shape[0]
    half = size // 2

    centered = template - float(template.mean())
    template_norm = float(np.linalg.norm(centered))

    if center is None or radius is None:
        min_x, max_x = half, width - half - 1
        min_y, max_y = half, height - half - 1
    else:
        cx, cy = center
        min_x = max(half, int(round(cx - radius)))
        max_x = min(width - half - 1, int(round(cx + radius)))
        min_y = max(half, int(round(cy - radius)))
        max_y = min(height - half - 1, int(round(cy + radius)))

    if min_x > max_x or min_y > max_y:
        raise ValueError("No valid search area remains after applying the nozzle template bounds.")

    best_x = min_x
    best_y = min_y
    best_corr = -1.0

    for y in range(min_y, max_y + 1, stride):
        y0, y1 = y - half, y + half + 1
        for x in range(min_x, max_x + 1, stride):
            x0, x1 = x - half, x + half + 1
            corr = _correlation(gray[y0:y1, x0:x1], centered, template_norm)
            if corr > best_corr:
                best_x, best_y, best_corr = x, y, corr

    # Refine around the best coarse candidate at single-pixel resolution.
    refine_radius = max(2, stride + 1)
    rx0 = max(half, best_x - refine_radius)
    rx1 = min(width - half - 1, best_x + refine_radius)
    ry0 = max(half, best_y - refine_radius)
    ry1 = min(height - half - 1, best_y + refine_radius)

    for y in range(ry0, ry1 + 1):
        y0, y1 = y - half, y + half + 1
        for x in range(rx0, rx1 + 1):
            x0, x1 = x - half, x + half + 1
            corr = _correlation(gray[y0:y1, x0:x1], centered, template_norm)
            if corr > best_corr:
                best_x, best_y, best_corr = x, y, corr

    return best_x, best_y, best_corr


def track_template(
    frame_rgb: np.ndarray,
    template: dict[str, Any],
    *,
    predicted_pixel: list[float] | tuple[float, float] | None = None,
    local_radius: int = 120,
    coarse_stride: int = 6,
) -> dict[str, Any]:
    gray = _grayscale(frame_rgb)
    reference = _template_array(template)

    center = None
    if predicted_pixel and len(predicted_pixel) >= 2:
        center = (float(predicted_pixel[0]), float(predicted_pixel[1]))
    elif "u" in template and "v" in template:
        center = (float(template["u"]), float(template["v"]))

    x, y, corr = _search(
        gray,
        reference,
        center=center,
        radius=local_radius if center else None,
        stride=coarse_stride,
    )

    # If the local match is weak, attempt a lower-resolution whole-frame recovery.
    recovered_full_frame = False
    if corr < 0.35:
        fx, fy, fcorr = _search(
            gray,
            reference,
            center=None,
            radius=None,
            stride=max(8, coarse_stride),
        )
        if fcorr > corr:
            x, y, corr = fx, fy, fcorr
            recovered_full_frame = True

    # Normalized cross correlation is [-1, 1]. Convert to a convenient [0, 1]
    # display confidence without implying statistical calibration.
    confidence = max(0.0, min(1.0, (corr + 1.0) / 2.0))

    return {
        "u": float(x),
        "v": float(y),
        "correlation": round(float(corr), 5),
        "confidence": round(float(confidence), 5),
        "recovered_full_frame": recovered_full_frame,
        "method": "normalized template correlation",
        "note": (
            "Experimental visual tracker. Confidence is a template-similarity score, "
            "not a validated probability and is never used for autonomous motion."
        ),
    }
