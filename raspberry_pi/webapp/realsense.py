from __future__ import annotations

import io
import subprocess
from typing import Any


def _run(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def usb_camera_status() -> dict[str, Any]:
    proc = _run(["lsusb"], timeout=5)
    lines = proc.stdout.splitlines() if proc.returncode == 0 else []
    matches = [
        line.strip()
        for line in lines
        if "realsense" in line.lower() or "8086:" in line.lower()
    ]

    sdk_available = False
    sdk_error = None
    model = None
    serial_number = None
    firmware = None

    try:
        import pyrealsense2 as rs  # type: ignore

        sdk_available = True
        ctx = rs.context()
        devices = list(ctx.query_devices())
        if devices:
            dev = devices[0]
            try:
                model = dev.get_info(rs.camera_info.name)
            except Exception:
                pass
            try:
                serial_number = dev.get_info(rs.camera_info.serial_number)
            except Exception:
                pass
            try:
                firmware = dev.get_info(rs.camera_info.firmware_version)
            except Exception:
                pass
    except Exception as exc:
        sdk_error = str(exc)

    return {
        "usb_detected": bool(matches) or model is not None,
        "usb_lines": matches,
        "sdk_available": sdk_available,
        "sdk_error": sdk_error,
        "model": model,
        "serial_number": serial_number,
        "firmware": firmware,
    }


def capture_depth_sample() -> dict[str, Any]:
    try:
        import numpy as np
        import pyrealsense2 as rs  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "RealSense SDK/Python bindings are not installed. Run install_realsense.sh first."
        ) from exc

    pipeline = rs.pipeline()
    config = rs.config()

    # 848x480 is the D405's preferred depth resolution. 15 FPS keeps USB/CPU load
    # modest on Raspberry Pi 4 while commissioning the sensing stack.
    config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 15)

    started = False
    try:
        profile = pipeline.start(config)
        started = True

        # Let exposure/depth settle.
        frames = None
        for _ in range(8):
            frames = pipeline.wait_for_frames(3000)

        if frames is None:
            raise RuntimeError("No RealSense frames received.")

        depth = frames.get_depth_frame()
        if not depth:
            raise RuntimeError("No depth frame received.")

        arr = np.asanyarray(depth.get_data())
        h, w = arr.shape[:2]
        cx, cy = w // 2, h // 2

        # Use a small center ROI to reduce single-pixel noise.
        radius = 10
        roi = arr[max(0, cy-radius):min(h, cy+radius+1), max(0, cx-radius):min(w, cx+radius+1)]
        valid = roi[roi > 0]

        scale = profile.get_device().first_depth_sensor().get_depth_scale()
        center_m = depth.get_distance(cx, cy)
        median_m = float(np.median(valid) * scale) if valid.size else None
        min_m = float(np.min(valid) * scale) if valid.size else None
        max_m = float(np.max(valid) * scale) if valid.size else None

        return {
            "width": int(w),
            "height": int(h),
            "center_distance_m": round(float(center_m), 5) if center_m > 0 else None,
            "roi_median_m": round(median_m, 5) if median_m is not None else None,
            "roi_min_m": round(min_m, 5) if min_m is not None else None,
            "roi_max_m": round(max_m, 5) if max_m is not None else None,
            "depth_scale_m": float(scale),
        }
    finally:
        if started:
            pipeline.stop()


def capture_depth_jpeg() -> bytes:
    try:
        import numpy as np
        import pyrealsense2 as rs  # type: ignore
        from PIL import Image
    except Exception as exc:
        raise RuntimeError(
            "RealSense SDK/Python bindings are not installed. Run install_realsense.sh first."
        ) from exc

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 15)

    started = False
    try:
        pipeline.start(config)
        started = True

        frames = None
        for _ in range(8):
            frames = pipeline.wait_for_frames(3000)

        if frames is None:
            raise RuntimeError("No RealSense frames received.")

        depth = frames.get_depth_frame()
        if not depth:
            raise RuntimeError("No depth frame received.")

        colorizer = rs.colorizer()
        colorized = colorizer.colorize(depth)
        image = np.asanyarray(colorized.get_data())

        out = io.BytesIO()
        Image.fromarray(image).save(out, format="JPEG", quality=88)
        return out.getvalue()
    finally:
        if started:
            pipeline.stop()
