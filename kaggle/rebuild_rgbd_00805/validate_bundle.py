#!/usr/bin/env python3
"""Check that a Kaggle bundle ZIP and notebook use the same pinned workflow."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile


EXPECTED_BUNDLE = "neusymnav-rebuild-rgbd-m1-m5-v1"
EXPECTED_MAP = "00805"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest_from_directory(root: Path) -> tuple[dict | None, dict[str, bytes], list[str]]:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return None, {}, [f"missing manifest: {manifest_path}"]
    files = {}
    for relative in ("probe/detector_diagnostic.py", "probe/network_preflight.py",
                     "requirements-host-kaggle-gpu.txt"):
        path = root / relative
        if not path.is_file():
            return None, {}, [f"missing pinned bundle file: {relative}"]
        files[relative] = path.read_bytes()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, {}, [f"invalid bundle manifest: {exc}"]
    return manifest, files, []


def _manifest_from_zip(path: Path) -> tuple[dict | None, dict[str, bytes], list[str]]:
    try:
        with zipfile.ZipFile(path) as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                return None, {}, [f"corrupt archive member: {bad_member}"]
            names = archive.namelist()
            for name in names:
                member = PurePosixPath(name)
                if member.is_absolute() or ".." in member.parts:
                    return None, {}, [f"unsafe archive member: {name}"]
            manifests = [name for name in names if name == "manifest.json" or name.endswith("/manifest.json")]
            if len(manifests) != 1:
                return None, {}, [f"expected one bundle manifest in ZIP, found {len(manifests)}"]
            manifest_name = manifests[0]
            prefix = manifest_name[:-len("manifest.json")]
            files = {}
            for relative in ("probe/detector_diagnostic.py", "probe/network_preflight.py",
                             "requirements-host-kaggle-gpu.txt"):
                name = prefix + relative
                if name not in names:
                    return None, {}, [f"missing pinned bundle file in ZIP: {relative}"]
                files[relative] = archive.read(name)
            try:
                manifest = json.loads(archive.read(manifest_name))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return None, {}, [f"invalid bundle manifest: {exc}"]
            return manifest, files, []
    except (OSError, zipfile.BadZipFile) as exc:
        return None, {}, [f"cannot read bundle ZIP: {exc}"]


def validate_bundle(bundle_path: Path, notebook_path: Path) -> list[str]:
    """Return integrity issues; an empty list means upload inputs are aligned."""
    bundle_path = Path(bundle_path)
    notebook_path = Path(notebook_path)
    if not notebook_path.is_file():
        return [f"notebook not found: {notebook_path}"]
    try:
        notebook_bytes = notebook_path.read_bytes()
    except OSError as exc:
        return [f"cannot read notebook: {exc}"]

    if bundle_path.is_dir():
        manifest, files, issues = _manifest_from_directory(bundle_path)
    elif bundle_path.is_file():
        manifest, files, issues = _manifest_from_zip(bundle_path)
    else:
        return [f"bundle path not found: {bundle_path}"]
    if issues or manifest is None:
        return issues
    if not isinstance(manifest, dict):
        return ["manifest must be a JSON object"]

    expected_identity = {
        "bundle": EXPECTED_BUNDLE,
        "map": EXPECTED_MAP,
        "kaggle_gpu_enabled": True,
    }
    issues = [f"manifest {key} mismatch: expected {expected!r}, got {manifest.get(key)!r}"
              for key, expected in expected_identity.items() if manifest.get(key) != expected]
    expected_files = {
        "workflow_notebook_sha256": _sha256(notebook_bytes),
        "detector_diagnostic_sha256": _sha256(files["probe/detector_diagnostic.py"]),
        "network_preflight_sha256": _sha256(files["probe/network_preflight.py"]),
        "kaggle_gpu_host_requirements_sha256": _sha256(files["requirements-host-kaggle-gpu.txt"]),
    }
    issues.extend(f"{key.replace('_sha256', '').replace('_', ' ')} SHA-256 mismatch"
                  for key, expected in expected_files.items() if manifest.get(key) != expected)
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="bundle directory or ZIP to upload")
    parser.add_argument("--notebook", type=Path,
                        default=Path(__file__).with_name("m1_m5_smoke_00805.ipynb"),
                        help="workflow notebook whose SHA is pinned by the manifest")
    args = parser.parse_args(argv)
    issues = validate_bundle(args.bundle, args.notebook)
    if issues:
        for issue in issues:
            print(f"FAIL: {issue}", file=sys.stderr)
        return 1
    print(f"OK: bundle and notebook pins match ({args.bundle})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
