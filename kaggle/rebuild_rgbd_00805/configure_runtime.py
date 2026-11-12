#!/usr/bin/env python3
"""Bind the portable 00805 bundle to Kaggle's working-directory interpreters."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _asset(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    return {"path": str(resolved), "sha256": sha256(resolved)}


def _interpreter(path: Path) -> dict[str, str]:
    # Keep the virtual-environment entry point; resolving a venv symlink would
    # bypass its site-packages and make preflight inspect the system Python.
    lexical = path.expanduser().absolute()
    if not lexical.is_file():
        raise FileNotFoundError(f"configured interpreter is missing: {lexical}")
    return {"path": str(lexical), "sha256": sha256(lexical)}


def build_runtime_config(*, bundle: Path, template: Path, host_python: Path,
                         habitat_python: Path, output: Path,
                         detector_device: str = "cpu",
                         raycast_backend: str = "cpu") -> dict:
    bundle = bundle.resolve(strict=True)
    template = template.resolve(strict=True)
    project = bundle / "project"
    profile = json.loads(template.read_text(encoding="utf-8"))
    if detector_device not in {"cpu", "cuda:0"}:
        raise ValueError("detector_device must be cpu or cuda:0")
    if raycast_backend not in {"cpu", "triton_cuda"}:
        raise ValueError("raycast_backend must be cpu or triton_cuda")
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    pins = manifest["pins"]
    scene = next((bundle / "scene").rglob("*.basis.glb"), None)
    scene_dataset = bundle / "scene" / "hm3d_minival_basis.scene_dataset_config.json"
    if scene is None or not scene_dataset.is_file():
        raise FileNotFoundError("bundle scene or Habitat scene dataset config is missing")

    host_python = host_python.expanduser().absolute()
    habitat_python = habitat_python.expanduser().absolute()
    if not host_python.is_file() or not habitat_python.is_file():
        raise FileNotFoundError("host or Habitat Python interpreter is missing")
    scene_entry = _asset(scene)
    scene_entry["path"] = str(scene.resolve())
    dataset_entry = _asset(scene_dataset)
    dataset_entry["path"] = str(scene_dataset.resolve())
    profile["sensor_config"]["scene"] = scene_entry
    profile["sensor_config"]["scene_dataset"] = dataset_entry
    profile["floor"]["datum_source"] = (
        "measured-downward-depth-v1:" + profile["floor"]["calibration_sha256"]
    )

    model_dir = project / "local-assets" / "models"
    checkpoint = _asset(model_dir / "yoloe-26m-seg.pt")
    encoder = _asset(model_dir / "mobileclip2_b.ts")
    taxonomy = _asset(project / "configs" / "taxonomy-v1.json")
    profile["detector"]["checkpoint"] = checkpoint
    profile["detector"]["encoder"] = encoder
    profile["detector"]["taxonomy"] = taxonomy
    profile["detector"]["device"] = detector_device
    profile.setdefault("navigation", {}).setdefault("mapper", {})[
        "raycast_backend"
    ] = raycast_backend

    sensor_script = _asset(project / "src/neusymnav/sensors/habitat_worker.py")
    detector_script = _asset(project / "src/neusymnav/perception/detector_worker.py")
    region_binary = _asset(project / "local-assets/native/bin/occusg_dude_worker")
    m23_binary = _asset(bundle / "Rebuild/build/native-m3/occupancy/standalone_sg_octomap_fixture_runner")
    m4_binary = _asset(bundle / "Rebuild/build/native-m4-dude/occusg_dude_worker")
    source_root = bundle / "Rebuild"

    profile["profile"] = "rebuild-rgbd-m1-m5-v1"
    profile["workers"] = {
        "sensor": {"python": _interpreter(habitat_python), "script": sensor_script, "timeout_s": 60.0},
        "detector": {
            "python": _interpreter(host_python), "script": detector_script,
            "startup_timeout_s": 60.0, "timeout_s": profile.get("workers", {}).get("detector", {}).get("timeout_s", 5.0),
        },
        "region": {"executable": region_binary},
        "room_pipeline": {
            "source_root": str(source_root.resolve()),
            "m23_binary": m23_binary,
            "m4_binary": m4_binary,
            "resolution_m": 0.05,
            "backprojection_stride": 1,
            "min_depth_m": 0.1,
            "max_depth_m": 10.0,
            "max_range_m": 5.0,
            "ipc_timeout_s": 60.0,
            "m23_timeout_s": 15.0,
            "m4_timeout_s": 30.0,
        },
    }
    if raycast_backend == "triton_cuda":
        profile["workers"]["raycast"] = {
            "python": _interpreter(host_python),
            "script": _asset(project / "src/neusymnav/mapping/gpu_raycast_worker.py"),
            "timeout_s": 0.25,
            "startup_timeout_s": 30.0,
        }
    profile["ui"] = {"enabled": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return profile


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--template", type=Path, default=None)
    parser.add_argument("--host-python", type=Path, required=True)
    parser.add_argument("--habitat-python", type=Path, required=True)
    parser.add_argument("--detector-device", choices=("cpu", "cuda:0"), default="cpu")
    parser.add_argument("--raycast-backend", choices=("cpu", "triton_cuda"), default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    template = args.template or args.bundle / "profile_template.json"
    profile = build_runtime_config(bundle=args.bundle, template=template,
                                   host_python=args.host_python, habitat_python=args.habitat_python,
                                   output=args.output, detector_device=args.detector_device,
                                   raycast_backend=args.raycast_backend)
    print(json.dumps({"config": str(args.output.resolve()), "profile": profile["profile"],
                      "scene": profile["sensor_config"]["scene"],
                      "detector_device": profile["detector"]["device"],
                      "raycast_backend": profile["navigation"]["mapper"]["raycast_backend"],
                      "room_pipeline": profile["workers"]["room_pipeline"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
