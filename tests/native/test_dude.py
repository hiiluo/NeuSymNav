"""Bounded subprocess checks for the actual schema-1 DuDe worker binaries."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "runs/p06-native/build-config.json"
POLICY = "extended_unknown_boundary"
COORDINATE_CONVENTION = (
    "world_x=origin_x+col*resolution; world_y=origin_y+row*resolution"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_config() -> dict:
    path = Path(os.environ.get("NEUSYMNAV_DUDE_BUILD_CONFIG", DEFAULT_CONFIG))
    if not path.is_file():
        pytest.skip(f"native build config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _request() -> tuple[dict, list[list[int]]]:
    width, height = 24, 20
    values = [[-1 for _ in range(width)] for _ in range(height)]
    for row in range(1, height - 1):
        for col in range(1, width - 1):
            values[row][col] = 0

    # Keep an internal unknown patch and a measured obstacle so preprocessing
    # sees both unknown-boundary and occupied evidence in the same narrow raster.
    for row in range(8, 11):
        for col in range(10, 13):
            values[row][col] = -1
    for col in range(5, 19):
        values[6][col] = 100

    request = {
        "protocol_version": 1,
        "op": "integrate",
        "request_id": "p06-extended-unknown-boundary-0",
        "revision": 0,
        "frame_id": "canonical_world_z_up:p06-native-fixture",
        "grid": {
            "width": width,
            "height": height,
            "resolution_m": 0.1,
            "origin_xy": [-1.1, 2.2],
            "values": [value for row in values for value in row],
        },
        "config": {
            "decomp_threshold_m": 1.5,
            "safety_distance_m": 0.0,
            "preprocessing_policy": POLICY,
        },
        "debug_capture_preprocessing": True,
    }
    return request, values


def _worker_env() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("LD_LIBRARY_PATH", None)
    return env


def _run_worker(binary: Path, request: dict) -> tuple[dict, dict]:
    process = subprocess.Popen(
        [str(binary)],
        cwd=REPO_ROOT,
        env=_worker_env(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    payload = json.dumps(request, separators=(",", ":")) + "\n"
    payload += json.dumps(
        {"protocol_version": 1, "op": "close"}, separators=(",", ":")
    ) + "\n"
    try:
        stdout, stderr = process.communicate(payload, timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        pytest.fail(
            f"DuDe worker timed out after 20 seconds; stdout={stdout!r}; stderr={stderr!r}"
        )
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert process.returncode == 0, (
        f"DuDe worker exit={process.returncode}; stdout={stdout!r}; stderr={stderr!r}"
    )
    assert len(lines) == 2, f"expected integrate and close responses; stderr={stderr!r}"
    integrate, close = (json.loads(line) for line in lines)
    assert close.get("protocol_version") == 1
    assert close.get("status") == "closed"
    return integrate, close


@pytest.fixture(scope="session")
def source_worker_result() -> tuple[dict, list[list[int]], dict]:
    config = _build_config()
    assert config.get("status") == "source_build_passed", (
        "source-built worker is unavailable; native test cannot be satisfied by a fixture"
    )
    binary = Path(config["binary"])
    assert binary.is_file(), f"source-built binary is missing: {binary}"
    assert _sha256(binary) == config.get("binary_sha256"), "source-built binary hash changed"
    request, input_values = _request()
    response, _ = _run_worker(binary, request)
    return response, input_values, config


@pytest.fixture(scope="session")
def candidate_worker_result() -> tuple[dict, list[list[int]], dict]:
    config = _build_config()
    candidate = config.get("candidate")
    if not candidate:
        pytest.skip("no explicitly pinned prebuilt candidate was configured")
    binary = Path(candidate["path"])
    assert binary.is_file(), f"pinned prebuilt candidate is missing: {binary}"
    assert _sha256(binary) == candidate.get("expected_sha256"), (
        "prebuilt candidate no longer matches its pinned SHA-256"
    )
    request, input_values = _request()
    response, _ = _run_worker(binary, request)
    return response, input_values, config


def _assert_extended_unknown_boundary(response: dict, input_values: list[list[int]]) -> None:
    assert response.get("protocol_version") == 1
    assert response.get("protocol_status") == "ok"
    assert response.get("request_id") == "p06-extended-unknown-boundary-0"
    assert response.get("input_revision") == 0
    assert response.get("status") in {"success", "fallback"}
    assert response.get("coordinate_convention") == COORDINATE_CONVENTION
    assert response.get("units") == "meters"

    diagnostics = response.get("diagnostics", {})
    assert diagnostics.get("preprocessing_policy") == POLICY
    assert diagnostics.get("unknown_byte_value") == 255
    assert diagnostics.get("preprocessed_unknown_pixels") == 0
    assert diagnostics.get("preprocessed_free_pixels", 0) > 0
    preprocessed = diagnostics.get("preprocessed_mask")
    assert preprocessed is not None
    assert len(preprocessed) == len(input_values)
    for row_idx, row in enumerate(input_values):
        assert len(preprocessed[row_idx]) == len(row)
        for col_idx, value in enumerate(row):
            if value == -1:
                assert preprocessed[row_idx][col_idx] is False, (
                    f"unknown cell ({row_idx},{col_idx}) became free under {POLICY}"
                )
    for region in response.get("regions", []):
        assert region.get("holes_supported") is False


@pytest.mark.native
def test_source_worker_preserves_unknown_through_preprocessing(source_worker_result) -> None:
    response, input_values, _ = source_worker_result
    _assert_extended_unknown_boundary(response, input_values)


@pytest.mark.native
def test_prebuilt_candidate_preserves_unknown_through_preprocessing(candidate_worker_result) -> None:
    response, input_values, _ = candidate_worker_result
    _assert_extended_unknown_boundary(response, input_values)


@pytest.mark.native
def test_source_and_candidate_preprocessing_parity_on_same_raster(
    source_worker_result, candidate_worker_result
) -> None:
    source, source_input, _ = source_worker_result
    candidate, candidate_input, _ = candidate_worker_result
    _assert_extended_unknown_boundary(source, source_input)
    _assert_extended_unknown_boundary(candidate, candidate_input)

    source_diagnostics = source["diagnostics"]
    candidate_diagnostics = candidate["diagnostics"]
    for key in (
        "preprocessing_policy",
        "preprocessed_mask",
        "black_mask",
        "crop",
        "pixel_tau",
        "preprocessed_free_pixels",
        "preprocessed_unknown_pixels",
    ):
        assert source_diagnostics.get(key) == candidate_diagnostics.get(key), (
            f"source/prebuilt raster preprocessing differs for {key}"
        )
