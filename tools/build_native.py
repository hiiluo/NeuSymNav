#!/usr/bin/env python3
"""Build the vendored DuDe worker using an explicitly supplied dependency prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_CLOSURE = REPO_ROOT / "native/dude"
RUN_ROOT = REPO_ROOT / "runs/p06-native"
BUILD_ROOT = RUN_ROOT / "build"
CONFIG_PATH = RUN_ROOT / "build-config.json"
WORKER_PATH = BUILD_ROOT / "occusg_dude_worker"
RAM_FLOOR_GIB = 4.0


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def available_memory_gib() -> float:
    meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
    for line in meminfo.splitlines():
        if line.startswith("MemAvailable:"):
            kib = int(line.split()[1])
            return kib / (1024 * 1024)
    raise RuntimeError("MemAvailable was not reported by /proc/meminfo")


def verify_source_closure(source_root: Path) -> dict:
    manifest_path = source_root / "source-closure.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"source closure manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise RuntimeError("source closure manifest must use schema_version=1 and list files")

    for candidate in (source_root, *source_root.rglob("*")):
        if candidate.is_symlink():
            raise RuntimeError(f"source closure contains a symlink: {candidate}")

    for record in manifest["files"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"source closure manifest path escapes its root: {relative}")
        path = source_root / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"vendored source file is missing or linked: {path}")
        digest = sha256(path)
        if digest != record.get("vendored_sha256"):
            raise RuntimeError(
                f"vendored source hash mismatch for {relative}: "
                f"expected {record.get('vendored_sha256')}, got {digest}"
            )
        if record.get("source_sha256") != digest:
            raise RuntimeError(f"copied file no longer matches its source snapshot: {relative}")

    cmake_text = (source_root / "CMakeLists.txt").read_text(encoding="utf-8")
    if "../3DSG" in cmake_text or "../NewOH3DSG" in cmake_text:
        raise RuntimeError("active native CMake configuration refers to a sibling source tree")
    return {
        "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path),
        "file_count": len(manifest["files"]),
    }


def run_logged(command: list[str], cwd: Path, log_path: Path) -> tuple[int, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    log = completed.stdout
    if completed.stderr:
        log += "\n[stderr]\n" + completed.stderr
    log_path.write_text(log, encoding="utf-8")
    print(log, end="" if log.endswith("\n") or not log else "\n")
    print(f"command_exit={completed.returncode}")
    return completed.returncode, log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-closure",
        type=Path,
        default=DEFAULT_SOURCE_CLOSURE,
        help=f"versioned vendored source root (default: {DEFAULT_SOURCE_CLOSURE})",
    )
    parser.add_argument(
        "--dependency-prefix",
        type=Path,
        required=True,
        help="explicit local prefix containing CGAL, GMP, and MPFR development files",
    )
    parser.add_argument(
        "--prebuilt-candidate",
        type=Path,
        help="optional read-only worker candidate to exercise for bounded parity",
    )
    parser.add_argument(
        "--prebuilt-candidate-sha256",
        help="required expected SHA-256 when --prebuilt-candidate is supplied",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_closure.resolve()
    dependency_prefix = args.dependency_prefix.resolve()
    try:
        source_root.relative_to(REPO_ROOT)
    except ValueError:
        raise SystemExit("--source-closure must resolve inside NeuSymNav")

    candidate = None
    expected_candidate_hash = args.prebuilt_candidate_sha256
    if bool(args.prebuilt_candidate) != bool(expected_candidate_hash):
        raise SystemExit("--prebuilt-candidate and --prebuilt-candidate-sha256 must be supplied together")
    if args.prebuilt_candidate:
        candidate_path = args.prebuilt_candidate.resolve(strict=True)
        if not candidate_path.is_file():
            raise SystemExit(f"prebuilt candidate is not a file: {candidate_path}")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_candidate_hash or ""):
            raise SystemExit("--prebuilt-candidate-sha256 must be 64 hexadecimal characters")
        actual_candidate_hash = sha256(candidate_path)
        if actual_candidate_hash.lower() != expected_candidate_hash.lower():
            raise SystemExit(
                f"prebuilt candidate SHA-256 mismatch: expected {expected_candidate_hash}, "
                f"got {actual_candidate_hash}"
            )
        candidate = {
            "path": str(candidate_path),
            "sha256": actual_candidate_hash,
            "expected_sha256": expected_candidate_hash.lower(),
        }

    try:
        closure = verify_source_closure(source_root)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        raise SystemExit(f"source closure validation failed: {error}")

    cgal_config = dependency_prefix / "lib/x86_64-linux-gnu/cmake/CGAL/CGALConfig.cmake"
    library_directory = dependency_prefix / "lib/x86_64-linux-gnu"
    dependency_files = {
        "gmp_include": dependency_prefix / "include/x86_64-linux-gnu",
        "gmp_header": dependency_prefix / "include/x86_64-linux-gnu/gmp.h",
        "gmpxx_include": dependency_prefix / "include",
        "gmpxx_header": dependency_prefix / "include/gmpxx.h",
        "mpfr_include": dependency_prefix / "include",
        "mpfr_header": dependency_prefix / "include/mpfr.h",
        "gmp_library": library_directory / "libgmp.so",
        "gmpxx_library": library_directory / "libgmpxx.a",
        "mpfr_library": library_directory / "libmpfr.so",
    }
    missing = [str(path) for path in dependency_files.values() if not path.exists()]
    if not cgal_config.is_file() or missing:
        missing_items = ([str(cgal_config)] if not cgal_config.is_file() else []) + missing
        raise SystemExit("explicit dependency prefix is incomplete: " + ", ".join(missing_items))

    try:
        ram_gib = available_memory_gib()
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit(f"RAM preflight failed: {error}")
    print(f"MemAvailable_GiB={ram_gib:.2f}; build_parallelism=1; minimum_GiB={RAM_FLOOR_GIB:.1f}")
    if ram_gib < RAM_FLOOR_GIB:
        raise SystemExit("RAM preflight rejected build: available memory is below the 4 GiB floor")

    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    configure_command = [
        "cmake",
        "-S",
        str(source_root),
        "-B",
        str(BUILD_ROOT),
        f"-DM4_PREFIX={dependency_prefix}",
        f"-DGMP_INCLUDE_DIR={dependency_files['gmp_include']}",
        f"-DGMP_LIBRARIES={dependency_files['gmp_library']}",
        f"-DGMPXX_INCLUDE_DIR={dependency_files['gmpxx_include']}",
        f"-DGMPXX_LIBRARIES={dependency_files['gmpxx_library']}",
        f"-DMPFR_INCLUDE_DIR={dependency_files['mpfr_include']}",
        f"-DMPFR_LIBRARIES={dependency_files['mpfr_library']}",
        "-DCMAKE_SKIP_RPATH=ON",
    ]
    build_command = [
        "cmake",
        "--build",
        str(BUILD_ROOT),
        "--target",
        "occusg_dude_worker",
        "--parallel",
        "1",
    ]
    config = {
        "schema_version": 1,
        "status": "in_progress",
        "source_closure": str(source_root),
        "source_closure_manifest": closure,
        "dependency_prefix": str(dependency_prefix),
        "dependency_library_directory": str(library_directory),
        "binary": str(WORKER_PATH),
        "binary_sha256": None,
        "candidate": candidate,
        "ram_preflight_available_gib": round(ram_gib, 3),
        "parallelism": 1,
        "commands": {
            "configure": configure_command,
            "build": build_command,
        },
        "exit_codes": {"configure": None, "build": None},
        "logs": {
            "configure": str((RUN_ROOT / "configure.log").resolve()),
            "build": str((RUN_ROOT / "build.log").resolve()),
        },
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    try:
        configure_exit, _ = run_logged(configure_command, REPO_ROOT, RUN_ROOT / "configure.log")
        config["exit_codes"]["configure"] = configure_exit
        if configure_exit != 0:
            config["status"] = "source_build_failed"
            CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return configure_exit

        build_exit, _ = run_logged(build_command, REPO_ROOT, RUN_ROOT / "build.log")
        config["exit_codes"]["build"] = build_exit
        if build_exit == 0 and WORKER_PATH.is_file():
            config["status"] = "source_build_passed"
            config["binary_sha256"] = sha256(WORKER_PATH)
        else:
            config["status"] = "source_build_failed"
        CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"status={config['status']}")
        print(f"binary={WORKER_PATH}")
        print(f"build_config={CONFIG_PATH}")
        return build_exit if build_exit != 0 else (0 if config["status"] == "source_build_passed" else 1)
    except OSError as error:
        config["status"] = "source_build_failed"
        config["error"] = str(error)
        CONFIG_PATH.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"build_tool_error={error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
