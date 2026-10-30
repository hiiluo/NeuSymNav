"""Native public-wire regression: moving local grids preserve world geometry."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np
import pytest


pytestmark = pytest.mark.native
ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / ".runtime/retained-assets/p06-native/build-config.json"


def _worker() -> Path:
    config_path = Path(os.environ.get("NEUSYMNAV_DUDE_BUILD_CONFIG", DEFAULT_CONFIG))
    if not config_path.is_file():
        pytest.skip(f"native build config unavailable: {config_path}")
    config = json.loads(config_path.read_text())
    assert config["status"] == "source_build_passed"
    binary = Path(config["binary"])
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == config["binary_sha256"]
    return binary


def _request(values, origin, revision):
    return {
        "protocol_version": 1,
        "op": "integrate",
        "request_id": f"origin-shift-{revision}",
        "revision": revision,
        "frame_id": "canonical_world_z_up:origin-shift-test",
        "grid": {
            "width": 101,
            "height": 101,
            "resolution_m": 0.05,
            "origin_xy": list(origin),
            "values": values.ravel().tolist(),
        },
        "config": {
            "decomp_threshold_m": 1.5,
            "safety_distance_m": 0.5,
            "preprocessing_policy": "extended_unknown_boundary",
        },
        "debug_capture_preprocessing": True,
    }


def _integrate(requests):
    env = os.environ.copy()
    env.pop("LD_LIBRARY_PATH", None)
    payload = "\n".join(json.dumps(x) for x in [*requests, {"protocol_version": 1, "op": "close"}]) + "\n"
    process = subprocess.run(
        [str(_worker())], input=payload, capture_output=True, text=True,
        cwd=ROOT, env=env, timeout=20,
    )
    assert process.returncode == 0, process.stderr
    responses = [json.loads(line) for line in process.stdout.splitlines()]
    assert len(responses) == len(requests) + 1
    assert responses[-1]["status"] == "closed"
    return responses[:-1]


@pytest.mark.parametrize("axis,direction", [(0, 1), (0, -1), (1, 1), (1, -1)])
def test_grid_aligned_window_moves_preserve_stationary_world_room(axis, direction):
    requests = []
    for step in range(10):
        values = np.full((101, 101), -1, np.int8)
        start = 30 - direction * step
        if axis == 0:
            values[10:91, start:start + 51] = 0
        else:
            values[start:start + 51, 10:91] = 0
        origin = [0.0, 0.0]
        origin[axis] = direction * step * 0.05
        requests.append(_request(values, origin, step + 1))

    for step, response in enumerate(_integrate(requests)):
        assert response["status"] in {"success", "fallback"}
        assert len(response["regions"]) == 1
        polygon = np.array(response["regions"][0]["outer"])
        # Literal stationary-world oracle independent of the correction formula.
        bounds = np.array([[1.5, 0.5], [4.0, 4.5]]) if axis == 0 else np.array([[0.5, 1.5], [4.5, 4.0]])
        actual = np.array([polygon.min(0), polygon.max(0)])
        np.testing.assert_allclose(actual, bounds, rtol=0, atol=2e-6, err_msg=f"step={step}")
        assert response["diagnostics"]["preprocessed_unknown_pixels"] == 0
        request = requests[step]
        rows, columns = np.indices((101, 101))
        x = request["grid"]["origin_xy"][0] + (columns + 0.5) * 0.05
        y = request["grid"]["origin_xy"][1] + (rows + 0.5) * 0.05
        interior = (x > actual[0, 0]) & (x < actual[1, 0]) & (y > actual[0, 1]) & (y < actual[1, 1])
        states = np.array(request["grid"]["values"]).reshape(101, 101)
        preprocessing = np.array(response["diagnostics"]["preprocessed_mask"])
        assert interior.any()
        assert np.all(states[interior] == 0)
        assert np.all(preprocessing[interior])


@pytest.mark.parametrize("offset", [0.03, -0.03])
def test_genuinely_non_grid_aligned_origin_retains_source_truncation(offset):
    values = np.full((101, 101), -1, np.int8)
    values[10:91, 30:81] = 0
    responses = _integrate([
        _request(values, (0.0, 0.0), 1),
        _request(values, (offset, 0.0), 2),
    ])
    # This established wire permits sub-cell origins. Its source convention
    # truncates a 0.6-cell correction to zero; only representational integer
    # errors are normalized by the grid-alignment fix.
    polygon = np.array(responses[-1]["regions"][0]["outer"])
    np.testing.assert_allclose(
        [polygon[:, 0].min(), polygon[:, 0].max()],
        [1.5 + offset, 4.0 + offset], rtol=0, atol=2e-6,
    )
