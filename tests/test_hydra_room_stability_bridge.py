"""Contract tests for the opt-in native room-stability bootstrap bridge."""
from __future__ import annotations

import builtins
import ctypes
import hashlib
import importlib
import json
from pathlib import Path

import pytest
import yaml


def _module():
    try:
        return importlib.import_module("neusymnav.backends.hydra.room_stability")
    except ModuleNotFoundError as exc:
        if exc.name == "neusymnav.backends.hydra.room_stability":
            pytest.fail("Hydra room-stability bridge API is not implemented", pytrace=False)
        raise


def _library(tmp_path: Path, name: str = "libhydra.so") -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    path.write_bytes(b"mock private Hydra library")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _config_root(tmp_path: Path, policy: dict | None = None) -> Path:
    root = tmp_path / "hydra-config"
    dataset = root / "datasets" / "neusymnav.yaml"
    dataset.parent.mkdir(parents=True)
    dataset.write_text(yaml.safe_dump({} if policy is None else {
        "neusymnav_room_stability": policy,
    }, sort_keys=True), encoding="utf-8")
    return root


class _NativeFunction:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


class _NativeLibrary:
    def __init__(self, *, version=b"neusymnav-room-stability-v1", configure=0,
                 diagnostics=b'{"decision":"confirmed"}'):
        self.nsn_room_stability_version = _NativeFunction(version)
        self.nsn_room_stability_configure = _NativeFunction(configure)
        self.nsn_room_stability_last_decision = _NativeFunction(diagnostics)


def _enabled_policy(path: Path, digest: str) -> dict:
    return {"enabled": True, "library_path": str(path), "library_sha256": digest}


def _load_mock(monkeypatch, library):
    calls = []

    def fake_cdll(path, *, mode):
        calls.append((path, mode))
        return library

    monkeypatch.setattr(ctypes, "CDLL", fake_cdll)
    return calls


def test_disabled_or_absent_policy_returns_without_importing_ctypes_or_loading_native(tmp_path, monkeypatch):
    module = _module()
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "ctypes":
            raise AssertionError("disabled room-stability policy imported ctypes")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert module.create_room_stability_bridge(_config_root(tmp_path / "absent")) is None
    assert module.create_room_stability_bridge(_config_root(
        tmp_path / "disabled", {"enabled": False})) is None


@pytest.mark.parametrize("policy", [
    {"enabled": 1, "library_path": "/tmp/libhydra.so", "library_sha256": "a" * 64},
    {"enabled": "true", "library_path": "/tmp/libhydra.so", "library_sha256": "a" * 64},
    {"enabled": True, "library_sha256": "a" * 64},
    {"enabled": True, "library_path": "", "library_sha256": "a" * 64},
    {"enabled": True, "library_path": 5, "library_sha256": "a" * 64},
    {"enabled": True, "library_path": "/tmp/libhydra.so", "library_sha256": "z" * 64},
    {"enabled": True, "library_path": "/tmp/libhydra.so", "library_sha256": "a" * 64, "extra": 1},
    {"enabled": False, "library_path": "/tmp/libhydra.so"},
], ids=["integer-enabled", "string-enabled", "missing-path", "empty-path", "non-string-path",
       "invalid-sha", "extra-field", "disabled-extra-field"])
def test_config_schema_and_hash_are_strict(tmp_path, policy):
    module = _module()
    with pytest.raises((ValueError, RuntimeError)):
        module.create_room_stability_bridge(_config_root(tmp_path, policy))


def test_enabled_bridge_checks_library_digest_and_configures_fixed_policy(tmp_path, monkeypatch):
    module = _module()
    path, digest = _library(tmp_path)
    native = _NativeLibrary()
    calls = _load_mock(monkeypatch, native)

    bridge = module.create_room_stability_bridge(_config_root(
        tmp_path, _enabled_policy(path, digest)))

    assert bridge is not None
    assert calls == [(str(path.resolve()), ctypes.RTLD_GLOBAL)]
    configured = json.loads(native.nsn_room_stability_configure.calls[0][0].decode("utf-8"))
    assert configured == {
        "enabled": True,
        "confirm_observations": 3,
        "candidate_tolerance_m": 0.02,
        "numerical_epsilon_m": 0.0001,
    }
    assert bridge.metadata["policy_config"] == configured
    assert bridge.metadata["library_sha256"] == digest


def test_enabled_bridge_rejects_digest_mismatch_before_loading(tmp_path, monkeypatch):
    module = _module()
    path, _ = _library(tmp_path)
    calls = _load_mock(monkeypatch, _NativeLibrary())

    with pytest.raises((ValueError, RuntimeError), match="SHA|digest|hash"):
        module.create_room_stability_bridge(_config_root(
            tmp_path, _enabled_policy(path, "0" * 64)))

    assert calls == []


def test_enabled_bridge_rejects_nonexistent_private_library_path(tmp_path, monkeypatch):
    module = _module()
    calls = _load_mock(monkeypatch, _NativeLibrary())
    missing = tmp_path / "missing" / "libhydra.so"

    with pytest.raises(ValueError, match="path|exist"):
        module.create_room_stability_bridge(_config_root(
            tmp_path, _enabled_policy(missing, "a" * 64)))

    assert calls == []


@pytest.mark.parametrize("version,configure", [
    (b"wrong-version", 0),
    (b"neusymnav-room-stability-v1", 1),
], ids=["wrong-version", "configure-failure"])
def test_enabled_bridge_fails_closed_on_native_abi_mismatch(tmp_path, monkeypatch, version, configure):
    module = _module()
    path, digest = _library(tmp_path)
    _load_mock(monkeypatch, _NativeLibrary(version=version, configure=configure))

    with pytest.raises(RuntimeError, match="version|configure|configuration"):
        module.create_room_stability_bridge(_config_root(
            tmp_path, _enabled_policy(path, digest)))


@pytest.mark.parametrize("payload", [
    b"not-json",
    b"[]",
    b'{"value":NaN}',
    b'{"value":1e9999}',
    b"{" + b" " * (64 * 1024) + b"}",
], ids=["invalid-json", "non-object", "nan", "infinite-number", "oversized"])
def test_native_diagnostics_must_be_small_finite_json_object(tmp_path, monkeypatch, payload):
    module = _module()
    path, digest = _library(tmp_path)
    native = _NativeLibrary(diagnostics=payload)
    _load_mock(monkeypatch, native)
    bridge = module.create_room_stability_bridge(_config_root(
        tmp_path, _enabled_policy(path, digest)))

    with pytest.raises((ValueError, RuntimeError), match="diagnostic|JSON|json|finite|64 KiB|64KiB|size|object"):
        bridge.diagnostics()


def test_diagnostics_keeps_stable_enabled_and_version_metadata(tmp_path, monkeypatch):
    module = _module()
    path, digest = _library(tmp_path)
    native = _NativeLibrary(diagnostics=b'{"decision":"confirmed","score":0.75}')
    _load_mock(monkeypatch, native)
    bridge = module.create_room_stability_bridge(_config_root(
        tmp_path, _enabled_policy(path, digest)))

    assert bridge.diagnostics() == {
        "decision": "confirmed",
        "score": 0.75,
        "enabled": True,
        "version": "neusymnav-room-stability-v1",
    }


def test_loaded_library_validation_rejects_missing_or_duplicate_hydra_paths(tmp_path, monkeypatch):
    module = _module()
    private, digest = _library(tmp_path / "private")
    stock, _ = _library(tmp_path / "stock")
    native = _NativeLibrary()
    _load_mock(monkeypatch, native)
    bridge = module.create_room_stability_bridge(_config_root(
        tmp_path, _enabled_policy(private, digest)))

    monkeypatch.setattr(module, "_read_process_maps", lambda: "")
    with pytest.raises(RuntimeError, match="libhydra|loaded|mapping"):
        bridge.validate_loaded_library()

    maps = f"1000-2000 r-xp 00000000 08:01 1 {private}\n2000-3000 r-xp 00000000 08:01 2 {stock}\n"
    monkeypatch.setattr(module, "_read_process_maps", lambda: maps)
    with pytest.raises(RuntimeError, match="multiple|distinct|libhydra|private"):
        bridge.validate_loaded_library()


def test_loaded_library_validation_accepts_only_configured_private_hydra_file(tmp_path, monkeypatch):
    module = _module()
    private, digest = _library(tmp_path / "private")
    native = _NativeLibrary()
    _load_mock(monkeypatch, native)
    bridge = module.create_room_stability_bridge(_config_root(
        tmp_path, _enabled_policy(private, digest)))
    maps = f"1000-2000 r-xp 00000000 08:01 1 {private}\n2000-3000 r--p 00001000 08:01 1 {private}\n"
    monkeypatch.setattr(module, "_read_process_maps", lambda: maps)

    bridge.validate_loaded_library()


def test_loaded_library_validation_rejects_a_single_stock_hydra_mapping(tmp_path, monkeypatch):
    module = _module()
    private, digest = _library(tmp_path / "private")
    stock, _ = _library(tmp_path / "stock")
    native = _NativeLibrary()
    _load_mock(monkeypatch, native)
    bridge = module.create_room_stability_bridge(_config_root(
        tmp_path, _enabled_policy(private, digest)))
    maps = f"1000-2000 r-xp 00000000 08:01 2 {stock}\n"
    monkeypatch.setattr(module, "_read_process_maps", lambda: maps)

    with pytest.raises(RuntimeError, match="configured private|does not resolve|libhydra"):
        bridge.validate_loaded_library()


def test_build_sha256_is_deterministic_and_closes_over_bridge_worker_and_private_library(tmp_path, monkeypatch):
    module = _module()
    path, digest = _library(tmp_path)
    native = _NativeLibrary()
    _load_mock(monkeypatch, native)
    bridge = module.create_room_stability_bridge(_config_root(
        tmp_path, _enabled_policy(path, digest)))

    first = bridge.build_sha256("a" * 64)
    assert first == bridge.build_sha256("a" * 64)
    assert first != bridge.build_sha256("b" * 64)
    metadata = bridge.metadata
    assert metadata["python_bridge_sha256"] == hashlib.sha256(
        Path(module.__file__).read_bytes()).hexdigest()
    assert metadata["worker_source_sha256"] == hashlib.sha256(
        Path(module.__file__).with_name("worker.py").read_bytes()).hexdigest()
    closure = {
        "binding_sha256": "a" * 64,
        "library_sha256": metadata["library_sha256"],
        "policy_sha256": metadata["policy_sha256"],
        "python_bridge_sha256": metadata["python_bridge_sha256"],
        "version": metadata["version"],
        "worker_source_sha256": metadata["worker_source_sha256"],
    }
    expected = hashlib.sha256(json.dumps(
        closure, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False).encode("utf-8")).hexdigest()
    assert first == expected
    assert len(first) == 64 and all(char in "0123456789abcdef" for char in first)
