#!/usr/bin/env python3
"""Stage the smallest private Kaggle input bundle for the 00805 Habitat probe."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REBUILD = ROOT.parent / "Rebuild_3DScene_OccuSG"
EXPECTED_M4 = "6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693"
EXPECTED_M23 = "617477524aa81acb0a0a46575741497aa15ed9b095f8fd72f92e09a81043cdc6"
EXPECTED_SOURCE = "60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_hash(package: Path) -> tuple[str, int]:
    files = sorted(package.rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest(), len(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-root", type=Path, default=Path(os.environ.get("NEUSYMNAV_REBUILD_ROOT", DEFAULT_REBUILD)))
    parser.add_argument("--output", type=Path, default=ROOT / ".runtime/kaggle/rebuild-rgbd-00805-input")
    args = parser.parse_args()

    rebuild = args.rebuild_root.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing bundle directory: {output}")

    profile_path = ROOT / "configs/demo-00805.local.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    scene_source = Path(profile["sensor_config"]["scene"]["path"]).resolve(strict=True)
    dataset_source = Path(profile["sensor_config"]["scene_dataset"]["path"]).resolve(strict=True)
    worker_source = ROOT / "src/neusymnav/sensors/habitat_worker.py"
    m23 = rebuild / "build/native-m3/occupancy/standalone_sg_octomap_fixture_runner"
    m4 = rebuild / "build/native-m4-dude/occusg_dude_worker"
    source = rebuild / "src/standalone_sg"
    source_hash, source_count = source_tree_hash(source)
    pins = {"m23": sha256(m23), "m4": sha256(m4), "source": source_hash}
    if pins != {"m23": EXPECTED_M23, "m4": EXPECTED_M4, "source": EXPECTED_SOURCE}:
        raise SystemExit(f"Rebuild pin mismatch: {pins}")
    if not os.access(m23, os.X_OK) or not os.access(m4, os.X_OK):
        raise SystemExit("Rebuild binaries must be executable")

    output.mkdir(parents=True)
    scene_dir = output / "scene" / scene_source.parent.name
    scene_dir.mkdir(parents=True)
    (output / "scene").mkdir(exist_ok=True)
    (output / "project/src/neusymnav/sensors").mkdir(parents=True)
    (output / "probe").mkdir()
    (output / "Rebuild/src").mkdir(parents=True)
    (output / "Rebuild/build/native-m3/occupancy").mkdir(parents=True)
    (output / "Rebuild/build/native-m4-dude").mkdir(parents=True)
    scene_name = scene_source.name
    shutil.copy2(scene_source, scene_dir / scene_name)
    navmesh = scene_source.with_suffix(".navmesh")
    if not navmesh.is_file():
        raise SystemExit(f"map navmesh is missing: {navmesh}")
    shutil.copy2(navmesh, scene_dir / navmesh.name)
    shutil.copy2(dataset_source, output / "scene" / dataset_source.name)
    shutil.copy2(worker_source, output / "project/src/neusymnav/sensors/habitat_worker.py")
    shutil.copy2(ROOT / "kaggle/rebuild_rgbd_00805/habitat_probe.py", output / "probe/habitat_probe.py")
    shutil.copy2(ROOT / "kaggle/rebuild_rgbd_00805/export_run.py", output / "probe/export_run.py")
    shutil.copytree(source, output / "Rebuild/src/standalone_sg")
    shutil.copy2(m23, output / "Rebuild/build/native-m3/occupancy/" / m23.name)
    shutil.copy2(m4, output / "Rebuild/build/native-m4-dude/" / m4.name)

    minimal_profile = {
        "episode": profile["episode"],
        "floor": {key: value for key, value in profile["floor"].items() if key != "datum_source"},
        "sensor_config": json.loads(json.dumps(profile["sensor_config"])),
    }
    minimal_profile["sensor_config"]["scene"] = {"path": f"scene/{scene_name}", "sha256": sha256(scene_source)}
    minimal_profile["sensor_config"]["scene_dataset"] = {
        "path": f"scene/{dataset_source.name}", "sha256": sha256(dataset_source)
    }
    (output / "profile.json").write_text(json.dumps(minimal_profile, indent=2, sort_keys=True) + "\n")
    try:
        commit = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
                                capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    manifest = {
        "bundle": "habitat-rgbd-probe-v1",
        "map": "00805",
        "neusymnav_commit": commit,
        "habitat_worker_sha256": sha256(worker_source),
        "scene_sha256": sha256(scene_source),
        "navmesh_sha256": sha256(navmesh),
        "scene_dataset_sha256": sha256(dataset_source),
        "rebuild_pins_checked_before_staging": {**pins, "source_file_count": source_count},
        "purpose": "Habitat and pinned Rebuild asset probe; not a complete NeuSymNav M1-M5 runtime bundle",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    archive = output.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(output).as_posix())
    print(f"bundle={output}")
    print(f"upload_zip={archive}")
    print(f"scene_bytes={scene_source.stat().st_size}")
    print(f"bundle_manifest={output / 'manifest.json'}")
    print("included map data and pinned Rebuild assets; the NeuSymNav M1-M5 runtime and detector environment are not included")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
