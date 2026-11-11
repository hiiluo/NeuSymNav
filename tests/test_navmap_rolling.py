"""Regression coverage for the optional bounded rolling NavMap policy."""
from dataclasses import replace
import json

import numpy as np
import pytest

from neusymnav.contracts import FrameKey, GridState, Observation
from neusymnav.mapping._raycast_kernel import RaycastVotes
from neusymnav.mapping.occupancy import NavMapper, RobotGeometry
from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.safety import MotionGuard
from neusymnav.mapping.rolling import RollingWindow


def _geometry():
    return RobotGeometry("cylinder-v1", .10, 1., .0, .2)


def _observation(index=0, *, x=0., stamp=1_000_000_000, episode="ep", sensor="navigation"):
    size = 17
    pose = np.eye(4)
    pose[:3, :3] = np.diag([1., -1., -1.])
    pose[:3, 3] = [x, 0., 5.]
    return Observation(
        FrameKey(episode, sensor, index), stamp, "host_monotonic:rolling", float(index),
        np.zeros((size, size, 3), np.uint8), np.full((size, size), 2., np.float32),
        np.ones((size, size), bool),
        np.array([[8., 0., size // 2], [0., 8., size // 2], [0., 0., 1.]], float),
        pose, "down-calibration-v1", 1, "depth_only",
    )


def _fake_collector(state):
    def collect(endpoints, camera_origin, *, resolution_m, origin_x_m, origin_z_m,
                robot_height_m, height_bin_m, **_kwargs):
        cells = state["cells"]
        bins = int(np.ceil(robot_height_m / height_bin_m))
        if not cells:
            return RaycastVotes(0, 0, np.zeros((0, 0), bool), np.zeros((0, 0), bool),
                                np.zeros((0, 0), bool), np.zeros((0, 0, bins), bool),
                                np.zeros((0, 0, bins), bool))
        center_row = int(np.floor((camera_origin[2] - origin_z_m) / resolution_m))
        center_col = int(np.floor((camera_origin[0] - origin_x_m) / resolution_m))
        coords = [(center_row + dr, center_col + dc, kind) for dr, dc, kind in cells]
        min_row = min(r for r, _, _ in coords)
        min_col = min(c for _, c, _ in coords)
        rows = max(r for r, _, _ in coords) - min_row + 1
        cols = max(c for _, c, _ in coords) - min_col + 1
        planar_free = np.zeros((rows, cols), bool)
        planar_hit = np.zeros((rows, cols), bool)
        floor_hit = np.zeros((rows, cols), bool)
        height_free = np.zeros((rows, cols, bins), bool)
        height_hit = np.zeros((rows, cols, bins), bool)
        for row, col, kind in coords:
            r, c = row - min_row, col - min_col
            if kind in {"full", "planar_height"}:
                planar_free[r, c] = True
            if kind in {"full", "planar_height"}:
                height_free[r, c, 1:] = True
            if kind == "floor_height":
                height_free[r, c, 1] = True
            if kind in {"full", "floor_height", "floor_only"}:
                floor_hit[r, c] = True
            if kind == "occupied":
                planar_hit[r, c] = True
                height_hit[r, c, 1] = True
        return RaycastVotes(min_row, min_col, planar_free, planar_hit, floor_hit,
                            height_free, height_hit)
    return collect


def _mapper(tmp_path, *, local_retention_s=None, radius=.2, tile_size=16,
            max_active_tiles=None, collector_state=None):
    state = {"cells": [(0, 0, "full")]} if collector_state is None else collector_state
    mapper = NavMapper(
        robot=_geometry(), floor_z_m=3., floor_datum_source="scene-calibration:v1",
        calibration_hash="a" * 64, resolution_m=.1, tile_size_cells=tile_size,
        height_bin_m=.2, sampling_stride=1, snapshot_radius_m=radius,
        local_retention_s=local_retention_s, tile_archive_dir=tmp_path,
        max_active_tiles=max_active_tiles,
    )
    mapper._core._raycast_collector = _fake_collector(state)
    return mapper, state


def _cell(nav):
    return NavMapper.world_to_snapshot(nav, (.05, .05))


def test_ttl_expires_each_component_at_inclusive_boundary_and_partial_refresh_isolated(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=3.)
    state["cells"] = [(0, 0, "full")]
    mapper.update(_observation(0, stamp=1_000_000_000))
    recent = mapper.update(_observation(1, stamp=2_000_000_000))
    row, col = _cell(recent)
    assert recent.states[row, col] == GridState.FREE

    state["cells"] = []
    before = mapper.update(_observation(2, stamp=4_999_999_999))
    assert before.states[row, col] == GridState.FREE
    expired = mapper.update(_observation(3, stamp=5_000_000_000))
    assert expired.states[row, col] == GridState.UNKNOWN
    assert not expired.floor_support[row, col]
    assert mapper._core.log_odds_at(0, 0) is None
    assert mapper._core.log_odds_at(0, 0, height_bin=1) is None
    diag = mapper.retention_diagnostics
    assert diag["expired_planar_components"] == 1
    assert diag["expired_height_components"] == 4
    assert diag["expired_floor_components"] == 1

    # Fresh height/floor evidence after expiry cannot revive the unrelated plane.
    state["cells"] = [(0, 0, "floor_height")]
    partial = mapper.update(_observation(4, stamp=5_100_000_000))
    row, col = _cell(partial)
    assert partial.states[row, col] == GridState.UNKNOWN
    assert partial.floor_support[row, col]
    assert mapper._core.log_odds_at(0, 0) is None
    assert mapper._core.log_odds_at(0, 0, height_bin=1) == pytest.approx(-.4)
    assert mapper._core.log_odds_at(0, 0, height_bin=2) is None


def test_partial_plane_and_height_refresh_cannot_revive_expired_floor(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=3.)
    for index, stamp in enumerate((1_000_000_000, 2_000_000_000)):
        state["cells"] = [(0, 0, "full")]
        mapper.update(_observation(index, stamp=stamp))
    state["cells"] = [(0, 0, "planar_height")]
    nav = mapper.update(_observation(2, stamp=5_000_000_000))
    row, col = _cell(nav)
    assert nav.states[row, col] == GridState.UNKNOWN
    assert not nav.floor_support[row, col]
    assert mapper._core.log_odds_at(0, 0) == pytest.approx(-.4)
    assert mapper._core.log_odds_at(0, 0, height_bin=1) == pytest.approx(-.4)


def test_zero_capture_timestamp_is_valid_and_expires_from_distinct_sentinel(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=3.)
    mapper.update(_observation(0, stamp=0))
    state["cells"] = []
    nav = mapper.update(_observation(1, stamp=3_000_000_000))
    row, col = _cell(nav)
    assert nav.states[row, col] == GridState.UNKNOWN
    assert mapper.retention_diagnostics["expired_planar_components"] == 1


def test_no_return_evidence_stays_unknown(tmp_path):
    mapper, state = _mapper(tmp_path)
    state["cells"] = [(0, 0, "planar_height")]
    nav = None
    for index in (0, 1, 2):
        observation = _observation(index, stamp=1_000_000_000 + index)
        observation = replace(observation, valid_depth=np.zeros_like(observation.valid_depth),
                              no_return=np.ones_like(observation.valid_depth),
                              no_return_range_m=2.)
        nav = mapper.update(observation)
    row, col = _cell(nav)
    assert nav.states[row, col] == GridState.UNKNOWN
    assert not nav.floor_support[row, col]


def test_spatial_window_is_grid_aligned_with_negative_indices_and_excludes_outside_votes(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=10., radius=.2)
    # x=-0.05 maps to column -1; the five-cell window is [-3, 1].
    state["cells"] = [(0, -2, "full")]
    accepted = mapper.update(_observation(0, x=-.05))
    assert mapper._core.log_odds_at(0, -3) == pytest.approx(-.4)
    assert accepted.origin_xy[0] == pytest.approx(-.3)

    state["cells"] = [(0, 3, "full")]  # column 2 is just outside the inclusive upper edge.
    outside = mapper.update(_observation(1, x=-.05, stamp=1_000_000_001))
    assert mapper._core.log_odds_at(0, 2) is None
    assert outside.states.shape == (5, 5)


def test_far_exit_evicts_without_archive_and_reentry_starts_unknown(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=10.)
    mapper.update(_observation(0, x=0., stamp=1_000_000_000))
    state["cells"] = [(0, 0, "full")]
    mapper.update(_observation(1, x=20., stamp=1_100_000_000))
    assert mapper._core.log_odds_at(0, 0) is None
    assert mapper._core.archived_tile_keys == ()
    assert mapper.retention_diagnostics["spatially_evicted_tiles"] >= 1

    state["cells"] = []
    nav = mapper.update(_observation(2, x=0., stamp=1_200_000_000))
    assert np.all(nav.states == GridState.UNKNOWN)
    assert mapper._core.log_odds_at(0, 0) is None
    assert mapper._core.archived_tile_keys == ()
    diag = mapper.retention_diagnostics
    assert diag["resident_tile_count"] <= diag["max_window_tiles"]


def test_enabled_rolling_mapper_never_resurrects_an_existing_archive(tmp_path):
    rolling, rolling_state = _mapper(tmp_path, local_retention_s=10.)
    legacy, legacy_state = _mapper(tmp_path, max_active_tiles=1)
    legacy.update(_observation(0, x=0., stamp=1_000_000_000))
    legacy_state["cells"] = [(0, 0, "full")]
    legacy.update(_observation(1, x=20., stamp=1_100_000_000))
    assert (0, 0) in legacy._core.archived_tile_keys

    rolling_state["cells"] = [(0, 0, "full")]
    rolling.update(_observation(0, x=0., stamp=1_200_000_000))
    assert rolling._core.log_odds_at(0, 0) == pytest.approx(-.4)
    assert (0, 0) not in rolling._core.archived_tile_keys


@pytest.mark.parametrize("retention", [True, False, 0, -1, float("nan"), float("inf"), 300.1, "3"])
def test_local_retention_requires_finite_positive_numeric_seconds(tmp_path, retention):
    with pytest.raises(ValueError, match="local_retention_s"):
        _mapper(tmp_path, local_retention_s=retention)


def test_local_retention_accepts_300_second_upper_bound(tmp_path):
    mapper, _ = _mapper(tmp_path, local_retention_s=300.)
    assert mapper.local_retention_s == 300.


def test_rolling_prevalidates_global_timestamp_domain_episode_and_future_before_mutation(tmp_path):
    mapper, _state = _mapper(tmp_path, local_retention_s=10.)
    mapper.update(_observation(0, stamp=2_000_000_000))
    baseline = (mapper._revision, mapper._core.active_tile_keys, mapper._ray_geometry_key,
                mapper.retention_diagnostics["resident_bytes"])

    rollback = _observation(0, stamp=1_500_000_000, sensor="auxiliary")
    with pytest.raises(ValueError, match="timestamp|monotonic"):
        mapper.update(rollback)
    wrong_episode = _observation(1, stamp=2_100_000_000, episode="other")
    with pytest.raises(ValueError, match="episode"):
        mapper.update(wrong_episode)
    wrong_domain = replace(_observation(1, stamp=2_100_000_000), clock_domain="other-domain")
    with pytest.raises(ValueError, match="clock domain"):
        mapper.update(wrong_domain)
    future = _observation(1, stamp=__import__("time").monotonic_ns() + 1_000_000_000)
    with pytest.raises(ValueError, match="future"):
        mapper.update(future)

    assert (mapper._revision, mapper._core.active_tile_keys, mapper._ray_geometry_key,
            mapper.retention_diagnostics["resident_bytes"]) == baseline


def test_equal_capture_stamp_is_allowed_for_a_distinct_increasing_frame(tmp_path):
    mapper, _state = _mapper(tmp_path, local_retention_s=10.)
    mapper.update(_observation(0, stamp=1_000_000_000))
    nav = mapper.update(_observation(1, stamp=1_000_000_000))
    assert nav.revision == 2


def test_reset_clears_rolling_timestamps_counters_and_cached_diagnostics(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=3.)
    mapper.update(_observation(0, stamp=1_000_000_000))
    state["cells"] = []
    mapper.update(_observation(1, stamp=5_000_000_000))
    assert mapper.retention_diagnostics["expired_planar_components"] == 1
    mapper.reset("ep")
    diag = mapper.retention_diagnostics
    assert diag["resident_tile_count"] == 0
    assert diag["resident_bytes"] == 0
    assert diag["expired_planar_components"] == 0
    assert mapper._last_capture_ns is None
    state["cells"] = [(0, 0, "full")]
    nav = mapper.update(_observation(0, stamp=500_000_000))
    assert np.any(nav.floor_support)


def test_optional_policy_preserves_legacy_archive_reactivation_and_diagnostics(tmp_path):
    mapper, state = _mapper(tmp_path, max_active_tiles=1)
    mapper.update(_observation(0, x=0., stamp=1_000_000_000))
    state["cells"] = [(0, 0, "full")]
    mapper.update(_observation(1, x=20., stamp=1_100_000_000))
    assert (0, 0) in mapper._core.archived_tile_keys
    state["cells"] = [(0, 0, "full")]
    nav = mapper.update(_observation(2, x=0., stamp=1_200_000_000))
    row, col = _cell(nav)
    assert nav.states[row, col] == GridState.FREE
    assert mapper.retention_diagnostics["policy"] == "legacy"
    assert mapper.retention_diagnostics["resident_timestamp_bytes"] == 0


def test_memory_diagnostics_count_timestamp_arrays_once_and_are_copy_safe_json(tmp_path):
    mapper, _state = _mapper(tmp_path, local_retention_s=10., tile_size=4)
    mapper.update(_observation(0))
    tile = next(iter(mapper._core._tiles.values()))
    diag = mapper.retention_diagnostics
    expected_timestamp_bytes = tile.planar_last_ns.nbytes + tile.floor_last_ns.nbytes + tile.height_last_ns.nbytes
    expected_bytes = (tile.planar_log_odds.nbytes + tile.floor_support.nbytes + tile.height_log_odds.nbytes
                      + expected_timestamp_bytes)
    assert diag["resident_timestamp_bytes"] == expected_timestamp_bytes
    assert diag["resident_bytes"] == expected_bytes
    json.dumps(diag)
    diag["resident_bytes"] = -1
    assert mapper.retention_diagnostics["resident_bytes"] == expected_bytes


def test_legacy_snapshot_immutability_and_rolling_window_snapshot_immutability(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=3.)
    first = mapper.update(_observation(0, stamp=1_000_000_000))
    frozen = first.states.copy()
    state["cells"] = []
    second = mapper.update(_observation(1, stamp=5_000_000_000))
    assert not first.states.flags.writeable
    assert np.array_equal(first.states, frozen)
    assert np.all(second.states == GridState.UNKNOWN)


def test_retained_free_map_cannot_rescue_missing_latest_depth(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=3.)
    state["cells"] = [(0, 0, "full")]
    mapper.update(_observation(0, stamp=1_000_000_000))
    nav = mapper.update(_observation(1, stamp=1_000_000_010))
    row, col = _cell(nav)
    assert nav.states[row, col] == GridState.FREE

    guard = MotionGuard(mapper, clock_domain=nav.clock_domain)
    guard.bind_nav(nav, robot_xy=(0., 0.), yaw_rad=0.)
    latest = _observation(2, stamp=1_000_000_020)
    latest = replace(latest, valid_depth=np.zeros_like(latest.valid_depth))
    decision = NavigationDecision("goal", ((0., 0.), (.1, 0.)), .1, 0., nav.revision, "tracking")
    command = guard.filter(decision, latest, latest.capture_monotonic_ns)
    assert command.reason == "bootstrap_blocked"
    assert command.linear_mps == command.yaw_radps == 0.


def test_no_return_clipping_ignores_expired_wall_but_keeps_fresh_wall(tmp_path):
    mapper, state = _mapper(tmp_path, local_retention_s=3.)
    state["cells"] = [(0, 0, "occupied")]
    mapper.update(_observation(0, stamp=1_000_000_000))
    core = mapper._core
    window = RollingWindow.centered(core.grid, x_m=0., z_m=0., radius_m=.2)
    origin = np.array([.01, 5., .05])
    endpoint = np.array([[.3, 5., .05]])
    no_hits = np.empty((0, 3), dtype=np.float64)

    fresh = core._clip_no_return_rays(origin, endpoint, no_hits,
        capture_monotonic_ns=1_500_000_000, rolling_window=window)
    expired = core._clip_no_return_rays(origin, endpoint, no_hits,
        capture_monotonic_ns=4_000_000_000, rolling_window=window)

    assert fresh.shape == (0, 3)
    assert expired.shape == (1, 3)

