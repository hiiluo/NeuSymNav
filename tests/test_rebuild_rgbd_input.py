import base64
from dataclasses import replace
import hashlib

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import FrameKey
from neusymnav.regions.rebuild_rgbd_input import (
    RebuildRGBDConfig, RebuildRGBDInputAdapter,
)


def test_adapter_keeps_source_metadata_masks_invalid_and_wire_hashes_arrays():
    obs = observation(depth_m=np.array([[1., np.nan, 20.], [.05, 2., 3.]], np.float32),
                      valid_depth=np.array([[True, False, True], [True, True, True]]))
    adapter = RebuildRGBDInputAdapter()
    frame = adapter.adapt(obs)
    assert frame.frame_index == 0
    assert frame.capture_monotonic_ns == 100
    assert frame.clock_domain == obs.clock_domain
    assert frame.calibration_id == obs.calibration_id
    assert frame.geometry_sha256 == obs.geometry_hash
    assert frame.config.backprojection_stride == 1
    assert np.isfinite(frame.depth_m[0, 0])
    assert not frame.valid_depth[0, 1] and np.isnan(frame.depth_m[0, 1])
    assert not frame.valid_depth[0, 2] and np.isnan(frame.depth_m[0, 2])
    assert not frame.valid_depth[1, 0] and np.isnan(frame.depth_m[1, 0])
    np.testing.assert_array_equal(frame.source_depth_m, obs.depth_m)
    np.testing.assert_array_equal(frame.source_valid_depth, obs.valid_depth)
    wire = frame.to_wire()
    rgb = wire["arrays"]["rgb"]
    raw = base64.b64decode(rgb["data"], validate=True)
    assert hashlib.sha256(raw).hexdigest() == rgb["sha256"]
    assert wire["frame"]["depth_representation"] == "axial"
    assert wire["frame"]["prefix_sha256"] == frame.prefix_sha256
    assert "source_depth_m" in wire["arrays"] and "source_valid_depth" in wire["arrays"]


def test_adapter_records_empty_optional_masks_for_exact_geometry_hash_replay():
    empty = np.zeros((2, 3), dtype=bool)
    obs = observation(no_return=empty, no_return_range_m=8., far_plane=empty,
                      far_plane_range_m=10.)
    wire = RebuildRGBDInputAdapter().adapt(obs).to_wire()
    assert wire["frame"]["source_masks_present"] == {"no_return": True, "far_plane": True}
    assert wire["frame"]["no_return_range_m"] == 8.
    assert wire["frame"]["far_plane_range_m"] == 10.
    assert "no_return_mask" in wire["arrays"] and "far_plane_mask" in wire["arrays"]


def test_adapter_rejects_duplicate_stale_and_new_sensor():
    adapter = RebuildRGBDInputAdapter()
    first = observation()
    adapter.adapt(first)
    with pytest.raises(ValueError, match="duplicate or out-of-order"):
        adapter.adapt(first)
    older = replace(first, key=FrameKey("episode", "rgbd", 0))
    with pytest.raises(ValueError, match="duplicate or out-of-order"):
        adapter.adapt(older)
    new_sensor = replace(first, key=FrameKey("episode", "other", 1),
                         capture_monotonic_ns=101, sim_time_s=1.)
    with pytest.raises(ValueError, match="one primary RGB-D sensor"):
        adapter.adapt(new_sensor)


@pytest.mark.parametrize("change,match", [
    ({"calibration_id": "calibration:v2", "key": FrameKey("episode", "rgbd", 1),
      "capture_monotonic_ns": 101, "sim_time_s": 1.}, "calibration changed"),
    ({"clock_domain": "host:boot2", "key": FrameKey("episode", "rgbd", 1),
      "capture_monotonic_ns": 101, "sim_time_s": 1.}, "clock domain changed"),
    ({"key": FrameKey("episode", "rgbd", 1), "capture_monotonic_ns": 99,
      "sim_time_s": 1.}, "source time moved backwards"),
])
def test_adapter_rejects_episode_source_changes(change, match):
    adapter = RebuildRGBDInputAdapter()
    adapter.adapt(observation())
    with pytest.raises(ValueError, match=match):
        adapter.adapt(observation(**change))


def test_adapter_requires_explicit_simulator_pose_and_explicit_config_values():
    with pytest.raises(ValueError, match="explicitly declared simulator_ground_truth"):
        RebuildRGBDConfig(pose_source="slam")
    config = RebuildRGBDConfig(resolution_m=.05, backprojection_stride=1,
                               min_depth_m=.1, max_depth_m=10., max_range_m=5.)
    assert config.resolution_m == .05 and config.max_range_m == 5.


def test_adapter_refuses_certified_no_return_that_source_m1_cannot_represent():
    obs = observation(no_return=np.array([[True, False, False], [False, False, False]]),
                      no_return_range_m=10.,
                      valid_depth=np.array([[False, True, True], [True, True, True]]))
    with pytest.raises(ValueError, match="cannot preserve certified no_return"):
        RebuildRGBDInputAdapter().adapt(obs)
