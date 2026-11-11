"""Fail-closed bootstrap for the optional native Hydra room-stability ABI.

This module is deliberately safe to import before ``hydra_python``.  The
disabled path never imports ctypes or loads a native library.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


VERSION = "neusymnav-room-stability-v1"
_CONFIG_KEY = "neusymnav_room_stability"
_MAX_DIAGNOSTICS_BYTES = 64 * 1024
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_POLICY_CONFIG = {
    "enabled": True,
    "confirm_observations": 3,
    "candidate_tolerance_m": 0.02,
    "numerical_epsilon_m": 0.0001,
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _valid_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _reject_constant(value: str):
    raise ValueError(f"non-finite JSON constant {value!r} is forbidden")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _require_finite_json(value: Any) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("diagnostics JSON contains a non-finite number")
    elif isinstance(value, list):
        for item in value:
            _require_finite_json(item)
    elif isinstance(value, dict):
        for item in value.values():
            _require_finite_json(item)


def _read_process_maps() -> str:
    return Path("/proc/self/maps").read_text(encoding="utf-8")


def _unescape_proc_path(value: str) -> str:
    return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)


def _hydra_paths_from_maps(maps_text: str) -> set[Path]:
    paths: set[Path] = set()
    for line in maps_text.splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        raw_path = _unescape_proc_path(fields[5])
        deleted = raw_path.endswith(" (deleted)")
        path_text = raw_path[:-10] if deleted else raw_path
        if Path(path_text).name != "libhydra.so":
            continue
        if deleted:
            raise RuntimeError("loaded libhydra.so mapping is deleted or no longer resolvable")
        try:
            paths.add(Path(path_text).resolve(strict=True))
        except OSError as exc:
            raise RuntimeError("loaded libhydra.so mapping cannot be resolved") from exc
    return paths


def _read_c_string(value: object, *, label: str, max_bytes: int) -> bytes:
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raise RuntimeError(f"native {label} function returned a null or invalid C string")
    if len(raw) > max_bytes:
        raise RuntimeError(f"native {label} exceeds its {max_bytes}-byte bound")
    return raw


class RoomStabilityBridge:
    """Strongly own the configured private Hydra library for this process."""

    def __init__(self, *, native_library, version: str, library_path: Path,
                 library_sha256: str, policy_config: dict[str, Any],
                 policy_sha256: str, python_bridge_sha256: str,
                 worker_source_sha256: str):
        self._native_library = native_library
        self._version = version
        self._library_path = library_path
        self._library_sha256 = library_sha256
        self._policy_config = dict(policy_config)
        self._policy_sha256 = policy_sha256
        self._python_bridge_sha256 = python_bridge_sha256
        self._worker_source_sha256 = worker_source_sha256
        self._diagnostics_fn = native_library.nsn_room_stability_last_decision

    @property
    def metadata(self) -> dict[str, Any]:
        """Return a detached, JSON-serializable provenance snapshot."""
        return {
            "enabled": True,
            "version": self._version,
            "library_sha256": self._library_sha256,
            "policy_config": dict(self._policy_config),
            "policy_sha256": self._policy_sha256,
            "library_path": str(self._library_path),
            "python_bridge_sha256": self._python_bridge_sha256,
            "worker_source_sha256": self._worker_source_sha256,
        }

    def validate_loaded_library(self) -> None:
        """Require one and only one mapped Hydra library, at the pinned path."""
        if self._library_path.name != "libhydra.so":
            raise RuntimeError("configured private library path must resolve to libhydra.so")
        try:
            maps_text = _read_process_maps()
        except OSError as exc:
            raise RuntimeError("cannot inspect /proc/self/maps for loaded libhydra.so") from exc
        paths = _hydra_paths_from_maps(maps_text)
        if len(paths) != 1:
            raise RuntimeError(
                f"expected exactly one distinct loaded libhydra.so path; found {len(paths)}")
        if paths != {self._library_path}:
            raise RuntimeError("loaded libhydra.so does not resolve to the configured private file")

    def diagnostics(self) -> dict[str, Any]:
        """Read bounded native diagnostics and retain bridge enable/version facts."""
        raw = _read_c_string(self._diagnostics_fn(), label="room-stability diagnostics",
                             max_bytes=_MAX_DIAGNOSTICS_BYTES)
        try:
            text = raw.decode("utf-8", errors="strict")
            result = json.loads(text, parse_constant=_reject_constant,
                                object_pairs_hook=_unique_object)
            _require_finite_json(result)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise RuntimeError(f"native room-stability diagnostics JSON is malformed: {exc}") from exc
        if not isinstance(result, dict):
            raise RuntimeError("native room-stability diagnostics JSON must be an object")
        result["enabled"] = True
        result["version"] = self._version
        if len(_canonical_json(result)) > _MAX_DIAGNOSTICS_BYTES:
            raise RuntimeError("native room-stability diagnostics exceed 64 KiB after provenance fields")
        return result

    def build_sha256(self, binding_sha256: str) -> str:
        """Hash the complete Python/native/policy closure with canonical JSON."""
        if not _valid_sha256(binding_sha256):
            raise ValueError("binding_sha256 must be a 64-character hexadecimal SHA-256")
        closure = {
            "binding_sha256": binding_sha256.lower(),
            "library_sha256": self._library_sha256,
            "policy_sha256": self._policy_sha256,
            "python_bridge_sha256": self._python_bridge_sha256,
            "version": self._version,
            "worker_source_sha256": self._worker_source_sha256,
        }
        return hashlib.sha256(_canonical_json(closure)).hexdigest()


def create_room_stability_bridge(config_root: Path) -> RoomStabilityBridge | None:
    """Load and configure the opt-in native bridge before Hydra bindings import."""
    root = Path(config_root).resolve()
    dataset_path = root / "datasets" / "neusymnav.yaml"
    import yaml

    try:
        document = yaml.safe_load(dataset_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read Hydra dataset configuration {dataset_path}") from exc
    if not isinstance(document, dict):
        raise ValueError("Hydra dataset configuration must be a YAML object")
    if _CONFIG_KEY not in document:
        return None
    profile = document[_CONFIG_KEY]
    if not isinstance(profile, dict):
        raise ValueError(f"{_CONFIG_KEY} must be an object")
    if type(profile.get("enabled")) is not bool:
        raise ValueError(f"{_CONFIG_KEY}.enabled must be a boolean")
    if profile["enabled"] is False:
        if set(profile) != {"enabled"}:
            raise ValueError(f"disabled {_CONFIG_KEY} must contain only enabled: false")
        return None
    required = {"enabled", "library_path", "library_sha256"}
    if set(profile) != required:
        raise ValueError(f"enabled {_CONFIG_KEY} requires exactly {sorted(required)}")
    path_value = profile["library_path"]
    expected_sha = profile["library_sha256"]
    if not isinstance(path_value, str) or not path_value or "\x00" in path_value:
        raise ValueError(f"{_CONFIG_KEY}.library_path must be a non-empty path string")
    if not _valid_sha256(expected_sha):
        raise ValueError(f"{_CONFIG_KEY}.library_sha256 must be a 64-character hexadecimal SHA-256")
    configured_path = Path(path_value)
    if not configured_path.is_absolute():
        configured_path = root / configured_path
    try:
        library_path = configured_path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"configured private library path does not exist: {configured_path}") from exc
    if not library_path.is_file():
        raise ValueError("configured private library path is not a regular file")
    actual_sha = _sha256_file(library_path)
    if actual_sha != expected_sha.lower():
        raise ValueError("configured private library SHA-256 does not match its file contents")

    # This import and all native loading are reachable only for a valid enabled profile.
    import ctypes

    try:
        native_library = ctypes.CDLL(str(library_path), mode=ctypes.RTLD_GLOBAL)
    except (OSError, TypeError) as exc:
        raise RuntimeError("failed to load configured private Hydra library") from exc
    try:
        version_fn = native_library.nsn_room_stability_version
        configure_fn = native_library.nsn_room_stability_configure
        diagnostics_fn = native_library.nsn_room_stability_last_decision
    except AttributeError as exc:
        raise RuntimeError("private Hydra library is missing the room-stability C API") from exc
    version_fn.argtypes = []
    version_fn.restype = ctypes.c_char_p
    configure_fn.argtypes = [ctypes.c_char_p]
    configure_fn.restype = ctypes.c_int
    diagnostics_fn.argtypes = []
    diagnostics_fn.restype = ctypes.c_char_p
    version_bytes = _read_c_string(version_fn(), label="room-stability version", max_bytes=128)
    try:
        version = version_bytes.decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError("private Hydra library returned a non-ASCII room-stability version") from exc
    if version != VERSION:
        raise RuntimeError(f"private Hydra library version mismatch: {version!r}")
    policy_config = dict(_POLICY_CONFIG)
    policy_bytes = _canonical_json(policy_config)
    if configure_fn(policy_bytes) != 0:
        raise RuntimeError("private Hydra room-stability configuration failed")

    bridge_file = Path(__file__).resolve()
    worker_file = bridge_file.with_name("worker.py")
    try:
        bridge_sha = _sha256_file(bridge_file)
        worker_sha = _sha256_file(worker_file)
    except OSError as exc:
        raise RuntimeError("cannot hash room-stability bridge or Hydra worker source") from exc
    return RoomStabilityBridge(
        native_library=native_library,
        version=version,
        library_path=library_path,
        library_sha256=actual_sha,
        policy_config=policy_config,
        policy_sha256=hashlib.sha256(policy_bytes).hexdigest(),
        python_bridge_sha256=bridge_sha,
        worker_source_sha256=worker_sha,
    )
