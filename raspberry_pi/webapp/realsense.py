from __future__ import annotations

import io
import subprocess
import threading
import time
from typing import Any


def _run(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def _encode_jpeg(image_array, quality: int = 82) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.fromarray(image_array).save(out, format="JPEG", quality=quality)
    return out.getvalue()


def _depth_measurement(depth, profile) -> dict[str, Any]:
    import numpy as np

    arr = np.asanyarray(depth.get_data())
    h, w = arr.shape[:2]
    cx, cy = w // 2, h // 2
    radius = 10
    roi = arr[
        max(0, cy - radius):min(h, cy + radius + 1),
        max(0, cx - radius):min(w, cx + radius + 1),
    ]
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


class RealSenseLiveManager:
    """Own one D405 pipeline and share its latest RGB/depth frames safely."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._running = False
        self._error: str | None = None
        self._latest_color_jpeg: bytes | None = None
        self._latest_depth_jpeg: bytes | None = None
        self._latest_measurement: dict[str, Any] | None = None
        self._last_frame_at: float | None = None
        self._fps: float = 0.0

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "error": self._error,
                "color_ready": self._latest_color_jpeg is not None,
                "depth_ready": self._latest_depth_jpeg is not None,
                "last_frame_at": self._last_frame_at,
                "fps": round(self._fps, 1),
                "stream": "RGB + depth",
                "color_resolution": "640x480",
                "depth_resolution": "848x480",
                "target_fps": 15,
            }

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return self.status_unlocked()
            self._stop.clear()
            self._error = None
            self._latest_color_jpeg = None
            self._latest_depth_jpeg = None
            self._latest_measurement = None
            self._last_frame_at = None
            self._thread = threading.Thread(
                target=self._run,
                name="realsense-d405-live",
                daemon=True,
            )
            self._thread.start()

        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            current = self.status()
            if current["color_ready"] or current["error"]:
                return current
            time.sleep(0.1)
        return self.status()

    def status_unlocked(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "error": self._error,
            "color_ready": self._latest_color_jpeg is not None,
            "depth_ready": self._latest_depth_jpeg is not None,
            "last_frame_at": self._last_frame_at,
            "fps": round(self._fps, 1),
            "stream": "RGB + depth",
            "color_resolution": "640x480",
            "depth_resolution": "848x480",
            "target_fps": 15,
        }

    def stop(self) -> dict[str, Any]:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=4.0)
        return self.status()

    def color_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_color_jpeg

    def depth_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_depth_jpeg

    def measurement(self) -> dict[str, Any] | None:
        with self._lock:
            return dict(self._latest_measurement) if self._latest_measurement else None

    def _run(self) -> None:
        pipeline = None
        started = False
        try:
            import numpy as np
            import pyrealsense2 as rs  # type: ignore

            pipeline = rs.pipeline()
            config = rs.config()
            config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 15)
            # D405 provides color from the left global-shutter imager through its ISP.
            # 640x480 @ 15 FPS keeps browser streaming light on Raspberry Pi 4.
            config.enable_stream(rs.stream.color, 640, 480, rs.format.bgr8, 15)

            profile = pipeline.start(config)
            started = True
            colorizer = rs.colorizer()

            with self._lock:
                self._running = True
                self._error = None

            frame_count = 0
            fps_window_start = time.monotonic()

            # Let auto exposure settle before publishing the first frame.
            warmup = 6
            while not self._stop.is_set():
                frames = pipeline.wait_for_frames(3000)
                depth = frames.get_depth_frame()
                color = frames.get_color_frame()
                if not depth or not color:
                    continue

                if warmup:
                    warmup -= 1
                    continue

                color_arr = np.asanyarray(color.get_data())
                # RealSense bgr8 -> Pillow RGB.
                color_rgb = color_arr[:, :, ::-1]
                color_jpeg = _encode_jpeg(color_rgb, quality=82)

                depth_color = colorizer.colorize(depth)
                depth_arr = np.asanyarray(depth_color.get_data())
                depth_rgb = depth_arr[:, :, ::-1]
                depth_jpeg = _encode_jpeg(depth_rgb, quality=82)

                measurement = _depth_measurement(depth, profile)
                now = time.time()

                frame_count += 1
                elapsed = time.monotonic() - fps_window_start
                if elapsed >= 1.0:
                    fps = frame_count / elapsed
                    frame_count = 0
                    fps_window_start = time.monotonic()
                else:
                    with self._lock:
                        fps = self._fps

                with self._lock:
                    self._latest_color_jpeg = color_jpeg
                    self._latest_depth_jpeg = depth_jpeg
                    self._latest_measurement = measurement
                    self._last_frame_at = now
                    self._fps = fps

        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            if started and pipeline is not None:
                try:
                    pipeline.stop()
                except Exception:
                    pass
            with self._lock:
                self._running = False


LIVE_CAMERA = RealSenseLiveManager()


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
        "live": LIVE_CAMERA.status(),
    }


def start_live_camera() -> dict[str, Any]:
    return LIVE_CAMERA.start()


def stop_live_camera() -> dict[str, Any]:
    return LIVE_CAMERA.stop()


def live_camera_status() -> dict[str, Any]:
    return LIVE_CAMERA.status()


def capture_color_jpeg() -> bytes:
    if not LIVE_CAMERA.status()["running"]:
        LIVE_CAMERA.start()

    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        frame = LIVE_CAMERA.color_jpeg()
        if frame:
            return frame
        status = LIVE_CAMERA.status()
        if status["error"]:
            raise RuntimeError(status["error"])
        time.sleep(0.05)
    raise RuntimeError("No D405 RGB frame is available yet.")


def capture_depth_sample() -> dict[str, Any]:
    live = LIVE_CAMERA.measurement()
    if live is not None and LIVE_CAMERA.status()["running"]:
        return live

    try:
        import pyrealsense2 as rs  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "RealSense SDK/Python bindings are not installed. Run install_realsense.sh first."
        ) from exc

    pipeline = rs.pipeline()
    config = rs.config()
    config.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, 15)

    started = False
    try:
        profile = pipeline.start(config)
        started = True
        frames = None
        for _ in range(8):
            frames = pipeline.wait_for_frames(3000)

        if frames is None:
            raise RuntimeError("No RealSense frames received.")

        depth = frames.get_depth_frame()
        if not depth:
            raise RuntimeError("No depth frame received.")

        return _depth_measurement(depth, profile)
    finally:
        if started:
            pipeline.stop()


def capture_depth_jpeg() -> bytes:
    live = LIVE_CAMERA.depth_jpeg()
    if live is not None and LIVE_CAMERA.status()["running"]:
        return live

    try:
        import numpy as np
        import pyrealsense2 as rs  # type: ignore
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
        image = np.asanyarray(colorized.get_data())[:, :, ::-1]
        return _encode_jpeg(image, quality=88)
    finally:
        if started:
            pipeline.stop()
