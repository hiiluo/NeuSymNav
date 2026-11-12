#!/usr/bin/env python3
"""Stage a private, pinned map-00805 NeuSymNav M1-M5 Kaggle input bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REBUILD = ROOT.parent / "Rebuild_3DScene_OccuSG"
EXPECTED = {
    "m23": "617477524aa81acb0a0a46575741497aa15ed9b095f8fd72f92e09a81043cdc6",
    "m4": "6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693",
    "source": "60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_hash(root: Path) -> tuple[str, int]:
    files = sorted(root.rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest(), len(files)


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _native_runtime_libs(binary: Path, output: Path) -> dict[str, str]:
    result = subprocess.run(["ldd", str(binary)], check=True, capture_output=True, text=True)
    if "not found" in result.stdout:
        raise RuntimeError(f"native worker has unresolved libraries:\n{result.stdout}")
    copied = {}
    skip = re.compile(r"^(?:libc\.so|libm\.so|libpthread\.so|librt\.so|libdl\.so|libgcc_s\.so|libstdc\+\+\.so|ld-linux|linux-vdso)")
    for line in result.stdout.splitlines():
        match = re.match(r"\s*(\S+)\s+=>\s+(\S+)", line)
        if not match:
            continue
        soname, resolved = match.groups()
        if skip.match(soname):
            continue
        source = Path(resolved).resolve(strict=True)
        target = output / soname
        _copy_file(source, target)
        copied[soname] = sha256(target)
    return copied


def _safe_zip(bundle: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as output:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                rel = path.relative_to(bundle).as_posix()
                if rel.startswith("/") or ".." in Path(rel).parts:
                    raise ValueError(f"unsafe path in bundle: {rel}")
                output.write(path, rel)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild-root", type=Path,
                        default=Path(os.environ.get("NEUSYMNAV_REBUILD_ROOT", DEFAULT_REBUILD)))
    parser.add_argument("--output", type=Path,
                        default=ROOT / ".runtime/kaggle/rebuild-rgbd-00805-full")
    args = parser.parse_args()
    rebuild = args.rebuild_root.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing bundle directory: {output}")

    profile_path = ROOT / "configs/demo-00805.local.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    scene_source = Path(profile["sensor_config"]["scene"]["path"]).resolve(strict=True)
    dataset_source = Path(profile["sensor_config"]["scene_dataset"]["path"]).resolve(strict=True)
    navmesh_source = scene_source.with_suffix(".navmesh")
    if not navmesh_source.is_file():
        raise SystemExit(f"map navmesh is missing: {navmesh_source}")

    m23_source = rebuild / "build/native-m3/occupancy/standalone_sg_octomap_fixture_runner"
    m4_source = rebuild / "build/native-m4-dude/occusg_dude_worker"
    rebuild_source = rebuild / "src/standalone_sg"
    m23_hash, m4_hash = sha256(m23_source), sha256(m4_source)
    source_hash, source_count = source_tree_hash(rebuild_source)
    if {"m23": m23_hash, "m4": m4_hash, "source": source_hash} != EXPECTED:
        raise SystemExit("Rebuild source pin mismatch; refusing to stage a mixed pipeline.")
    if source_count != 50 or not os.access(m23_source, os.X_OK) or not os.access(m4_source, os.X_OK):
        raise SystemExit("Rebuild source closure or executable permissions differ from the pinned profile")

    output.mkdir(parents=True)
    project = output / "project"
    shutil.copytree(ROOT / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(ROOT / "tools", project / "tools", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (project / "configs").mkdir(parents=True)
    _copy_file(ROOT / "configs/taxonomy-v1.json", project / "configs/taxonomy-v1.json")
    _copy_file(ROOT / "pyproject.toml", project / "pyproject.toml")
    _copy_file(ROOT / "THIRD_PARTY_NOTICES.md", project / "THIRD_PARTY_NOTICES.md")
    _copy_file(ROOT / "local-assets/models/yoloe-26m-seg.pt", project / "local-assets/models/yoloe-26m-seg.pt")
    _copy_file(ROOT / "local-assets/models/mobileclip2_b.ts", project / "local-assets/models/mobileclip2_b.ts")
    region_source = ROOT / "local-assets/native/bin/occusg_dude_worker"
    _copy_file(region_source, project / "local-assets/native/bin/occusg_dude_worker")
    native_lib_dir = ROOT / "local-assets/native/lib"
    if native_lib_dir.is_dir():
        shutil.copytree(native_lib_dir, project / "local-assets/native/lib", dirs_exist_ok=True)

    # Package the exact CLIP module already used by the calibrated detector env.
    detector_python = ROOT / ".runtime/detector26/bin/python"
    clip_root = Path(subprocess.run([str(detector_python), "-c", "import clip,pathlib;print(pathlib.Path(clip.__file__).parent)"],
                                    check=True, capture_output=True, text=True).stdout.strip())
    clip_target = project / "third_party/clip/clip"
    shutil.copytree(clip_root, clip_target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    clip_dist = clip_root.parent / "clip-1.0.dist-info"
    license_path = next((clip_dist / "licenses").glob("*"))
    _copy_file(license_path, project / "third_party/clip/LICENSE")
    (project / "third_party/clip/setup.py").write_text(
        "from setuptools import setup\n"
        "setup(name='clip', version='1.0', packages=['clip'], "
        "package_data={'clip': ['bpe_simple_vocab_16e6.txt.gz']})\n", encoding="utf-8")

    scene_dir = output / "scene" / scene_source.parent.name
    scene_dir.mkdir(parents=True)
    _copy_file(scene_source, scene_dir / scene_source.name)
    _copy_file(navmesh_source, scene_dir / navmesh_source.name)
    _copy_file(dataset_source, output / "scene" / dataset_source.name)

    _copy_file(m23_source, output / "Rebuild/build/native-m3/occupancy/standalone_sg_octomap_fixture_runner")
    _copy_file(m4_source, output / "Rebuild/build/native-m4-dude/occusg_dude_worker")
    shutil.copytree(rebuild_source, output / "Rebuild/src/standalone_sg",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # M4's pinned RUNPATH points to the developer build tree; stage its runtime
    # dependency closure and set LD_LIBRARY_PATH at launch instead of patching binary bytes.
    native_libs = _native_runtime_libs(m4_source, output / "native/lib")
    _copy_file(ROOT / "kaggle/rebuild_rgbd_00805/habitat_probe.py", output / "probe/habitat_probe.py")
    _copy_file(ROOT / "kaggle/rebuild_rgbd_00805/export_run.py", output / "probe/export_run.py")
    _copy_file(ROOT / "kaggle/rebuild_rgbd_00805/configure_runtime.py", output / "probe/configure_runtime.py")
    _copy_file(ROOT / "kaggle/rebuild_rgbd_00805/detector_diagnostic.py",
               output / "probe/detector_diagnostic.py")
    _copy_file(ROOT / "kaggle/rebuild_rgbd_00805/network_preflight.py",
               output / "probe/network_preflight.py")
    _copy_file(ROOT / "kaggle/rebuild_rgbd_00805/requirements-host.txt", output / "requirements-host.txt")
    _copy_file(ROOT / "kaggle/rebuild_rgbd_00805/requirements-host-kaggle-gpu.txt",
               output / "requirements-host-kaggle-gpu.txt")
    template = json.loads(json.dumps(profile))
    template["floor"]["datum_source"] = (
        "measured-downward-depth-v1:" + template["floor"]["calibration_sha256"]
    )
    template["sensor_config"]["scene"] = {"path": "scene/map.basis.glb"}
    template["sensor_config"]["scene_dataset"] = {
        "path": "scene/hm3d_minival_basis.scene_dataset_config.json"
    }
    for key, relative in (("checkpoint", "local-assets/models/yoloe-26m-seg.pt"),
                          ("encoder", "local-assets/models/mobileclip2_b.ts"),
                          ("taxonomy", "configs/taxonomy-v1.json")):
        template["detector"][key] = {"path": relative}
    template.pop("workers", None)
    template["ui"] = {"enabled": False}
    (output / "profile_template.json").write_text(
        json.dumps(template, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    project_hash, project_count = source_tree_hash(project / "src/neusymnav")
    manifest = {
        "bundle": "neusymnav-rebuild-rgbd-m1-m5-v1",
        "map": "00805",
        "kaggle_gpu_enabled": True,
        "purpose": "bounded live M1-M5 smoke from Habitat RGB-D; UI disabled; no semantic GT",
        "habitat_sim": "0.3.3",
        "host_python": "3.12",
        "pins": {"m23_sha256": m23_hash, "m4_sha256": m4_hash,
                 "source_tree_sha256": source_hash, "source_file_count": source_count},
        "neusymnav_source": {"tree_sha256": project_hash, "python_file_count": project_count},
        "scene_sha256": sha256(scene_source),
        "navmesh_sha256": sha256(navmesh_source),
        "scene_dataset_sha256": sha256(dataset_source),
        "detector_checkpoint_sha256": sha256(project / "local-assets/models/yoloe-26m-seg.pt"),
        "detector_encoder_sha256": sha256(project / "local-assets/models/mobileclip2_b.ts"),
        "region_worker_sha256": sha256(project / "local-assets/native/bin/occusg_dude_worker"),
        "native_runtime_libraries": native_libs,
        "profile_template_sha256": sha256(output / "profile_template.json"),
        "detector_diagnostic_sha256": sha256(output / "probe/detector_diagnostic.py"),
        "network_preflight_sha256": sha256(output / "probe/network_preflight.py"),
        "workflow_notebook_sha256": sha256(ROOT / "kaggle/rebuild_rgbd_00805/m1_m5_smoke_00805.ipynb"),
        "host_requirements_sha256": sha256(output / "requirements-host.txt"),
        "kaggle_gpu_host_requirements_sha256": sha256(output / "requirements-host-kaggle-gpu.txt"),
        "source_commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                          check=True, capture_output=True, text=True).stdout.strip(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    archive = output.with_suffix(".zip")
    _safe_zip(output, archive)
    print(json.dumps({"bundle": str(output), "upload_zip": str(archive),
                      "bundle_bytes": sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
                      "zip_bytes": archive.stat().st_size, "manifest": manifest}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
