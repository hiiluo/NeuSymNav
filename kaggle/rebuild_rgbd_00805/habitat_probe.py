#!/usr/bin/env python3
"""Small Habitat-only probe using NeuSymNav's configured RGB-D capture worker."""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image


def _load_capture(worker_path: Path):
    spec = importlib.util.spec_from_file_location("kaggle_habitat_worker", worker_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load Habitat worker: {worker_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.HabitatCapture


def _decode_packet(value: dict) -> tuple[dict, dict[str, np.ndarray]]:
    metadata = value["metadata"]
    raw = base64.b64decode(value["arrays_b64"], validate=True)
    if hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                      + b"\0" + raw).hexdigest() != value["sha256"]:
        raise ValueError("Habitat worker packet checksum mismatch")
    with np.load(io.BytesIO(raw), allow_pickle=False) as archive:
        arrays = {name: archive[name] for name in archive.files}
    return metadata, arrays


def _depth_preview(depth: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, float | None, float | None]:
    """Stretch valid depth to grayscale using robust per-frame percentiles."""
    preview = np.zeros(depth.shape, dtype=np.uint8)
    if not valid.any():
        return preview, None, None

    low, high = (float(value) for value in np.percentile(depth[valid], (2.0, 98.0)))
    if high <= low:
        # A constant-depth image still deserves visible valid pixels.
        preview[valid] = 255
        return preview, low, high

    normalized = np.clip((depth[valid] - low) * (255.0 / (high - low)), 0.0, 255.0)
    preview[valid] = np.rint(normalized).astype(np.uint8)
    return preview, low, high


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--scene", type=Path, required=True)
    parser.add_argument("--scene-dataset", type=Path, required=True)
    parser.add_argument("--worker", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    profile = json.loads(args.profile.read_text(encoding="utf-8"))
    source = profile["sensor_config"]
    config = {
        "scene_id": str(args.scene.resolve(strict=True)),
        "scene_dataset_config_file": str(args.scene_dataset.resolve(strict=True)),
        "episode_id": profile["episode"]["id"],
        "initial_position": source["initial_position"],
        "initial_rotation_xyzw": source["initial_rotation_xyzw"],
        "primary": source["primary"],
        "navigation": source["navigation"],
        "seed": source.get("seed", 0),
        "gpu_device_id": source.get("gpu_device_id", 0),
        "motion_adapter": source.get("motion_adapter", "strict_3d"),
    }
    capture_type = _load_capture(args.worker.resolve(strict=True))
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    capture = capture_type(config)
    try:
        result = {"habitat_version": capture.habitat_sim.__version__, "sensors": {}}
        for lane in ("primary", "navigation"):
            metadata, arrays = _decode_packet(capture.capture(lane))
            depth = arrays["depth_m"]
            valid = np.isfinite(depth) & (depth >= 0.1) & (depth < 10.0)
            entry = {
                "frame_index": metadata["frame_index"],
                "sensor_id": metadata["sensor_id"],
                "rgb_shape": list(arrays["rgb"].shape) if lane == "primary" and "rgb" in arrays else None,
                "depth_shape": list(depth.shape),
                "valid_depth_pixels": int(valid.sum()),
                "depth_min_valid_m": float(depth[valid].min()) if valid.any() else None,
                "depth_max_valid_m": float(depth[valid].max()) if valid.any() else None,
                "calibration_id": metadata["calibration_id"],
            }
            if lane == "primary":
                rgb = arrays["rgb"]
                Image.fromarray(rgb[..., :3].astype(np.uint8)).save(args.output / "rgb.png")
                scaled, preview_min, preview_max = _depth_preview(depth, valid)
                entry["depth_preview_range_m"] = [preview_min, preview_max]
                entry["depth_preview_scaling"] = "valid-pixel 2nd-98th percentile; invalid=black"
                Image.fromarray(scaled).save(args.output / "depth.png")
            result["sensors"][lane] = entry
        result["elapsed_s"] = time.monotonic() - started
        result["scene_sha256"] = hashlib.sha256(args.scene.read_bytes()).hexdigest()
        result["scene_dataset_sha256"] = hashlib.sha256(args.scene_dataset.read_bytes()).hexdigest()
        result["status"] = "passed"
        (args.output / "habitat_probe.json").write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        capture.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
