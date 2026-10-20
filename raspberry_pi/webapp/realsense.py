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
        self._view_mode: str = "RGB"
        self._color_resolution: str = "640x480"
        self._depth_resolution: str = "640x480"
        self._target_fps: int = 15
        self._latest_depth_raw = None
        self._depth_intrinsics = None
        self._depth_scale: float | None = None
        self._intrinsics_info: dict[str, Any] | None = None
        self._frame_width: int = 0
        self._frame_height: int = 0

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "running": self._running,
                "error": self._error,
                "color_ready": self._latest_color_jpeg is not None,
                "depth_ready": self._latest_depth_jpeg is not None,
                "sample_ready": self._latest_depth_raw is not None and self._depth_intrinsics is not None,
                "last_frame_at": self._last_frame_at,
                "fps": round(self._fps, 1),
                "stream": f"{self._view_mode} + depth",
                "color_resolution": self._color_resolution,
                "depth_resolution": self._depth_resolution,
                "frame_width": self._frame_width,
                "frame_height": self._frame_height,
                "intrinsics": self._intrinsics_info,
                "target_fps": self._target_fps,
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
            self._latest_depth_raw = None
            self._depth_intrinsics = None
            self._depth_scale = None
            self._intrinsics_info = None
            self._frame_width = 0
            self._frame_height = 0
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
            "sample_ready": self._latest_depth_raw is not None and self._depth_intrinsics is not None,
            "last_frame_at": self._last_frame_at,
            "fps": round(self._fps, 1),
            "stream": f"{self._view_mode} + depth",
            "color_resolution": self._color_resolution,
            "depth_resolution": self._depth_resolution,
            "frame_width": self._frame_width,
            "frame_height": self._frame_height,
            "intrinsics": self._intrinsics_info,
            "target_fps": self._target_fps,
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


    def sample_pixel(self, u: float, v: float, radius: int = 2) -> dict[str, Any]:
        try:
            import numpy as np
            import pyrealsense2 as rs  # type: ignore
        except Exception as exc:
            raise RuntimeError("RealSense Python bindings are unavailable.") from exc

        with self._lock:
            if self._latest_depth_raw is None or self._depth_intrinsics is None or self._depth_scale is None:
                raise RuntimeError("No aligned live depth frame is available. Start the live camera first.")
            depth_raw = self._latest_depth_raw.copy()
            intrinsics = self._depth_intrinsics
            scale = float(self._depth_scale)
            width = int(self._frame_width)
            height = int(self._frame_height)

        if width <= 0 or height <= 0:
            raise RuntimeError("Live camera frame geometry is unavailable.")

        x = int(round(max(0, min(width - 1, float(u)))))
        y = int(round(max(0, min(height - 1, float(v)))))
        x0, x1 = max(0, x - radius), min(width, x + radius + 1)
        y0, y1 = max(0, y - radius), min(height, y + radius + 1)
        roi = depth_raw[y0:y1, x0:x1]
        valid = roi[roi > 0]
        if valid.size == 0:
            raise RuntimeError("No valid depth return at the selected pixel.")

        depth_m = float(np.median(valid) * scale)
        point = rs.rs2_deproject_pixel_to_point(intrinsics, [float(x), float(y)], depth_m)
        return {
            "u": float(x),
            "v": float(y),
            "depth_m": round(depth_m, 6),
            "camera_xyz_m": [round(float(value), 6) for value in point],
            "frame_width": width,
            "frame_height": height,
        }

    def sample_pixels(self, pixels: list[tuple[float, float]], radius: int = 2) -> list[dict[str, Any]]:
        try:
            import numpy as np
            import pyrealsense2 as rs  # type: ignore
        except Exception as exc:
            raise RuntimeError("RealSense Python bindings are unavailable.") from exc

        with self._lock:
            if self._latest_depth_raw is None or self._depth_intrinsics is None or self._depth_scale is None:
                raise RuntimeError("No aligned live depth frame is available. Start the live camera first.")
            depth_raw = self._latest_depth_raw.copy()
            intrinsics = self._depth_intrinsics
            scale = float(self._depth_scale)
            width = int(self._frame_width)
            height = int(self._frame_height)

        results: list[dict[str, Any]] = []
        for u, v in pixels:
            x = int(round(max(0, min(width - 1, float(u)))))
            y = int(round(max(0, min(height - 1, float(v)))))
            x0, x1 = max(0, x - radius), min(width, x + radius + 1)
            y0, y1 = max(0, y - radius), min(height, y + radius + 1)
            roi = depth_raw[y0:y1, x0:x1]
            valid = roi[roi > 0]

            if valid.size == 0:
                results.append({"u": float(x), "v": float(y), "valid": False})
                continue

            depth_m = float(np.median(valid) * scale)
            point = rs.rs2_deproject_pixel_to_point(intrinsics, [float(x), float(y)], depth_m)
            results.append(
                {
                    "u": float(x),
                    "v": float(y),
                    "valid": True,
                    "depth_m": round(depth_m, 6),
                    "camera_xyz_m": [round(float(value), 6) for value in point],
                    "frame_width": width,
                    "frame_height": height,
                }
            )
        return results

    def _run(self) -> None:
        pipeline = None
        started = False
        try:
            import numpy as np
            import pyrealsense2 as rs  # type: ignore

            # The D405 exposes its left imager as a color-capable stream, but
            # supported combinations can vary with firmware / USB negotiation.
            # Try conservative matched 640x480 profiles first, then fall back
            # to a monochrome left-imager stream if color cannot be resolved.
            candidates = [
                {
                    "mode": "RGB",
                    "depth": (640, 480, rs.format.z16, 15),
                    "view": ("color", 640, 480, rs.format.rgb8, 15),
                },
                {
                    "mode": "RGB",
                    "depth": (640, 480, rs.format.z16, 15),
                    "view": ("color", 640, 480, rs.format.bgr8, 15),
                },
                {
                    "mode": "RGB",
                    "depth": (848, 480, rs.format.z16, 15),
                    "view": ("color", 640, 480, rs.format.rgb8, 15),
                },
                {
                    "mode": "MONO",
                    "depth": (640, 480, rs.format.z16, 15),
                    "view": ("infrared", 640, 480, rs.format.y8, 15),
                },
            ]

            profile = None
            chosen = None
            errors: list[str] = []

            for candidate in candidates:
                if self._stop.is_set():
                    return

                trial_pipeline = rs.pipeline()
                config = rs.config()
                dw, dh, dfmt, dfps = candidate["depth"]
                kind, vw, vh, vfmt, vfps = candidate["view"]

                config.enable_stream(rs.stream.depth, dw, dh, dfmt, dfps)
                if kind == "color":
                    config.enable_stream(rs.stream.color, vw, vh, vfmt, vfps)
                else:
                    config.enable_stream(rs.stream.infrared, 1, vw, vh, vfmt, vfps)

                try:
                    profile = trial_pipeline.start(config)
                    pipeline = trial_pipeline
                    started = True
                    chosen = candidate
                    break
                except Exception as exc:
                    errors.append(f"{candidate['mode']} {dw}x{dh}+{vw}x{vh}: {exc}")
                    try:
                        trial_pipeline.stop()
                    except Exception:
                        pass

            if not started or pipeline is None or profile is None or chosen is None:
                raise RuntimeError(
                    "Unable to start a D405 live view. Tried supported RGB and "
                    "left-imager profiles. " + " | ".join(errors)
                )

            dw, dh, _, dfps = chosen["depth"]
            kind, vw, vh, _, vfps = chosen["view"]
            colorizer = rs.colorizer()

            with self._lock:
                self._running = True
                self._error = None
                self._view_mode = chosen["mode"]
                self._color_resolution = f"{vw}x{vh}"
                self._depth_resolution = f"{dw}x{dh}"
                self._target_fps = min(dfps, vfps)

            frame_count = 0
            fps_window_start = time.monotonic()
            warmup = 6

            align = rs.align(rs.stream.color) if kind == "color" else None

            while not self._stop.is_set():
                frames = pipeline.wait_for_frames(3000)

                if align is not None:
                    frames = align.process(frames)

                depth = frames.get_depth_frame()

                if kind == "color":
                    view = frames.get_color_frame()
                else:
                    view = frames.get_infrared_frame(1)

                if not depth or not view:
                    continue

                if warmup:
                    warmup -= 1
                    continue

                view_arr = np.asanyarray(view.get_data())
                if kind == "infrared":
                    view_rgb = np.stack((view_arr, view_arr, view_arr), axis=-1)
                else:
                    fmt = view.profile.format()
                    if fmt == rs.format.bgr8:
                        view_rgb = view_arr[:, :, ::-1]
                    else:
                        view_rgb = view_arr

                color_jpeg = _encode_jpeg(view_rgb, quality=82)

                depth_raw = np.asanyarray(depth.get_data()).copy()
                depth_profile = depth.profile.as_video_stream_profile()
                depth_intrinsics = depth_profile.intrinsics
                depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()

                depth_color = colorizer.colorize(depth)
                depth_arr = np.asanyarray(depth_color.get_data())
                # Colorizer output is RGB8 in current librealsense builds.
                depth_jpeg = _encode_jpeg(depth_arr, quality=82)

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
                    self._latest_depth_raw = depth_raw
                    self._depth_intrinsics = depth_intrinsics
                    self._depth_scale = float(depth_scale)
                    self._intrinsics_info = {
                        "width": int(depth_intrinsics.width),
                        "height": int(depth_intrinsics.height),
                        "fx": float(depth_intrinsics.fx),
                        "fy": float(depth_intrinsics.fy),
                        "ppx": float(depth_intrinsics.ppx),
                        "ppy": float(depth_intrinsics.ppy),
                        "model": str(depth_intrinsics.model),
                        "coeffs": [float(value) for value in depth_intrinsics.coeffs],
                    }
                    self._frame_width = int(depth.get_width())
                    self._frame_height = int(depth.get_height())
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


def sample_live_pixel(u: float, v: float, radius: int = 2) -> dict[str, Any]:
    if not LIVE_CAMERA.status()["running"]:
        status = LIVE_CAMERA.start()
        if status.get("error"):
            raise RuntimeError(status["error"])
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if LIVE_CAMERA.status().get("sample_ready"):
            return LIVE_CAMERA.sample_pixel(u, v, radius=radius)
        time.sleep(0.05)
    raise RuntimeError("Timed out waiting for an aligned D405 depth frame.")


def sample_live_pixels(pixels: list[tuple[float, float]], radius: int = 2) -> list[dict[str, Any]]:
    if not LIVE_CAMERA.status()["running"]:
        status = LIVE_CAMERA.start()
        if status.get("error"):
            raise RuntimeError(status["error"])
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if LIVE_CAMERA.status().get("sample_ready"):
            return LIVE_CAMERA.sample_pixels(pixels, radius=radius)
        time.sleep(0.05)
    raise RuntimeError("Timed out waiting for an aligned D405 depth frame.")


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
