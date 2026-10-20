from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path(
    os.environ.get(
        "VT_BIOPRINTER_DATA_DIR",
        Path.home() / ".local" / "share" / "vt-bioprinter",
    )
)
EXPERIMENTS_DIR = DATA_DIR / "experiments"
ACTIVE_FILE = DATA_DIR / "active-experiment.json"
_LOCK = threading.Lock()


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "-", text.strip()).strip("-").lower()
    return value[:48] or "experiment"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def active_experiment() -> dict[str, Any] | None:
    active = _read_json(ACTIVE_FILE)
    if not active:
        return None
    directory = Path(active.get("directory", ""))
    metadata = _read_json(directory / "metadata.json")
    if not metadata or metadata.get("ended_at_unix"):
        try:
            ACTIVE_FILE.unlink()
        except FileNotFoundError:
            pass
        return None
    return metadata


def start_experiment(
    name: str,
    *,
    calibration: dict[str, Any] | None,
    plan: dict[str, Any] | None,
) -> dict[str, Any]:
    with _LOCK:
        existing = active_experiment()
        if existing:
            raise ValueError(f"Experiment '{existing.get('name')}' is already active.")

        now = int(time.time())
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
        directory = EXPERIMENTS_DIR / f"{stamp}_{_slug(name)}"
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "snapshots").mkdir()

        calibration_summary = None
        if calibration:
            calibration_summary = {
                "camera": calibration.get("camera"),
                "bed": calibration.get("bed"),
                "camera_to_printer": calibration.get("camera_to_printer"),
                "nozzle_reference": calibration.get("nozzle_reference"),
            }

        plan_summary = None
        if plan:
            plan_summary = {key: value for key, value in plan.items() if key != "segments"}

        metadata = {
            "version": 1,
            "name": name.strip() or "Experiment",
            "directory": str(directory),
            "started_at_unix": now,
            "ended_at_unix": None,
            "mode": "OBSERVE",
            "calibration": calibration_summary,
            "plan": plan_summary,
            "event_count": 0,
            "snapshot_count": 0,
        }

        (directory / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVE_FILE.write_text(
            json.dumps({"directory": str(directory)}, indent=2) + "\n",
            encoding="utf-8",
        )
        return metadata


def _active_directory() -> tuple[Path, dict[str, Any]]:
    active = active_experiment()
    if not active:
        raise ValueError("No experiment is active.")
    return Path(active["directory"]), active


def log_event(event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with _LOCK:
        try:
            directory, metadata = _active_directory()
        except ValueError:
            return None

        event = {
            "time_unix": time.time(),
            "type": event_type,
            "payload": payload or {},
        }
        with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")

        metadata["event_count"] = int(metadata.get("event_count", 0)) + 1
        (directory / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        return event


def save_snapshot(
    *,
    rgb_jpeg: bytes,
    depth_jpeg: bytes,
    measurement: dict[str, Any] | None,
) -> dict[str, Any]:
    with _LOCK:
        directory, metadata = _active_directory()
        index = int(metadata.get("snapshot_count", 0)) + 1
        stamp = f"{index:05d}_{int(time.time() * 1000)}"

        rgb_name = f"{stamp}_rgb.jpg"
        depth_name = f"{stamp}_depth.jpg"
        (directory / "snapshots" / rgb_name).write_bytes(rgb_jpeg)
        (directory / "snapshots" / depth_name).write_bytes(depth_jpeg)

        record = {
            "index": index,
            "time_unix": time.time(),
            "rgb_file": f"snapshots/{rgb_name}",
            "depth_file": f"snapshots/{depth_name}",
            "measurement": measurement,
        }
        with (directory / "snapshots.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")

        metadata["snapshot_count"] = index
        metadata["event_count"] = int(metadata.get("event_count", 0)) + 1
        (directory / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        with (directory / "events.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "time_unix": record["time_unix"],
                        "type": "snapshot",
                        "payload": {
                            "index": index,
                            "rgb_file": record["rgb_file"],
                            "depth_file": record["depth_file"],
                            "measurement": measurement,
                        },
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
        return record


def stop_experiment() -> dict[str, Any]:
    with _LOCK:
        directory, metadata = _active_directory()
        metadata["ended_at_unix"] = int(time.time())
        metadata["duration_seconds"] = (
            metadata["ended_at_unix"] - int(metadata["started_at_unix"])
        )
        (directory / "metadata.json").write_text(
            json.dumps(metadata, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            ACTIVE_FILE.unlink()
        except FileNotFoundError:
            pass
        return metadata


def list_experiments(limit: int = 20) -> list[dict[str, Any]]:
    if not EXPERIMENTS_DIR.exists():
        return []

    items: list[dict[str, Any]] = []
    for directory in sorted(EXPERIMENTS_DIR.iterdir(), reverse=True):
        if not directory.is_dir():
            continue
        metadata = _read_json(directory / "metadata.json")
        if metadata:
            items.append(metadata)
        if len(items) >= limit:
            break
    return items
