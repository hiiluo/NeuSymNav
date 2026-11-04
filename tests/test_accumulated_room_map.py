from dataclasses import replace

import numpy as np
import pytest

from neusymnav.contracts import FrameKey, NavSnapshot
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.mapping.overview import OverviewTiles
from neusymnav.mapping.room_map import RoomMapEvidence, RoomMapUnavailable, build_room_map


def nav(*, revision=4, source_index=8, robot_id="robot-v1", resolution=0.5, origin=(0.0, 0.0)):
    states = np.full((3, 3), -1, dtype=np.int8)
    states[1, 1] = 0
    return NavSnapshot(
        "episode-a",
        revision,
        FrameKey("episode-a", "nav", source_index),
        10_000 + source_index,
        "host:room-map-test",
        resolution,
        origin,
        states,
        states == 0,
        np.where(states == 0, 0.5, 0.0).astype(np.float64),
        robot_id,
        -0.25,
        "fixture-floor-datum-v1",
        "a" * 64,
    )


def tile(size=4, cells=()):
    result = np.full((size, size), -1, dtype=np.int8)
    for row, col, value in cells:
        result[row, col] = value
    return result


def evidence(source, tile_map, *, origin=(-10.0, -20.0), resolution=0.5, size=4,
             complete=True, robot=None):
    return RoomMapEvidence(
        OverviewTiles(source, origin, resolution, size, tile_map, complete),
        robot or RobotGeometry("robot-v1", 0.125, 1.234),
    )


def test_raw_tiles_build_exact_native_resolution_world_map_and_preserve_source():
    source = nav()
    source_before = source.states.copy()
    raw = {
        (-1, -2): tile(4, ((1, 2, 0), (1, 3, 100))),
        (1, 1): tile(4, ((2, 0, 0),)),
    }
    result = build_room_map(evidence(source, raw), source)

    assert result is not source
    assert result.source == source.source
    assert result.revision == source.revision
    assert result.capture_monotonic_ns == source.capture_monotonic_ns
    assert result.clock_domain == source.clock_domain
    assert result.robot_geometry_id == source.robot_geometry_id
    assert result.floor_z_m == source.floor_z_m
    assert result.floor_datum_source == source.floor_datum_source
    assert result.calibration_hash == source.calibration_hash
    assert result.origin_xy == pytest.approx((-13.0, -21.5))
    assert result.resolution_m == source.resolution_m
    assert result.states.shape == (10, 11)
    assert result.states[0, 0] == 0
    assert result.states[0, 1] == 100
    assert result.states[0, 2] == -1  # unknown hole between known cells
    assert result.states[9, 10] == 0
    assert result.states[5, 5] == -1  # unobserved gap between distant tiles
    assert result.floor_support.dtype == np.bool_
    assert np.array_equal(result.floor_support, result.states == 0)
    assert result.clearance.dtype == np.float64
    assert result.clearance[0, 0] == 1.234
    assert result.clearance[0, 1] == 0.0
    assert result.clearance[9, 10] == 1.234
    assert np.array_equal(source.states, source_before)
    assert source.origin_xy == (0.0, 0.0)
    assert not result.states.flags.writeable


def test_no_known_raw_cells_returns_source_aligned_unknown_cell():
    source = nav(origin=(1.0, -2.0))
    raw = {(0, 0): tile(4)}
    result = build_room_map(evidence(source, raw, origin=(0.0, -2.0)), source)
    assert result.origin_xy == source.origin_xy
    assert result.resolution_m == source.resolution_m
    assert result.states.shape == (1, 1)
    assert result.states.tolist() == [[-1]]
    assert not result.floor_support.any()
    assert result.clearance.dtype == np.float64
    assert result.clearance.tolist() == [[0.0]]


@pytest.mark.parametrize(
    "case",
    ["incomplete", "stale_revision", "stale_source", "robot_geometry", "missing_provider"],
)
def test_unavailable_incomplete_or_stale_room_input_is_rejected(case):
    source = nav()
    raw = {(0, 0): tile(4, ((0, 0, 0),))}
    candidate = evidence(source, raw, origin=(0.0, 0.0), complete=case != "incomplete")
    expected = source
    if case == "stale_revision":
        expected = replace(source, revision=source.revision + 1)
    elif case == "stale_source":
        expected = replace(source, source=FrameKey("episode-a", "nav", source.source.frame_index + 1))
    elif case == "robot_geometry":
        candidate = evidence(
            source,
            raw,
            origin=(0.0, 0.0),
            robot=RobotGeometry("robot-v2", 0.125, 1.234),
        )
    elif case == "missing_provider":
        candidate = RoomMapEvidence(None, RobotGeometry("robot-v1", 0.125, 1.234))

    with pytest.raises(RoomMapUnavailable):
        build_room_map(candidate, expected)


def test_extent_budget_rejects_distant_raw_tiles_before_dense_allocation(monkeypatch):
    source = nav()
    raw = {
        (0, 0): tile(4, ((0, 0, 0),)),
        (2000, 2000): tile(4, ((0, 0, 100),)),
    }
    candidate = evidence(source, raw, origin=(0.0, 0.0))

    def forbidden_dense_allocation(*args, **kwargs):
        raise AssertionError("dense raster allocation occurred before extent rejection")

    monkeypatch.setattr("neusymnav.mapping.room_map.np.full", forbidden_dense_allocation)
    with pytest.raises(RoomMapUnavailable, match="extent exceeds max_cells"):
        build_room_map(candidate, source, max_cells=64)


def test_evidence_freezes_input_tiles_and_new_tile_revision_applies_updates():
    first_source = nav(revision=4, source_index=8)
    caller_tile = tile(4, ((1, 1, 0), (1, 2, 100)))
    first = evidence(first_source, {(0, 0): caller_tile}, origin=(0.0, 0.0))
    caller_tile[1, 1] = 100
    first_result = build_room_map(first, first_source)
    assert first_result.states.tolist() == [[0, 100]]

    second_source = nav(revision=5, source_index=9)
    second_tiles = {
        (0, 0): tile(4, ((1, 1, 100), (1, 2, -1))),
        (2, 3): tile(4, ((0, 0, 0),)),  # retained history outside the local nav raster
    }
    second = evidence(second_source, second_tiles, origin=(0.0, 0.0))
    second_result = build_room_map(second, second_source)
    assert second_result.states[0, 0] == 100
    assert second_result.states[0, 1] == -1
    assert second_result.states[-1, -1] == 0
    assert second_result.origin_xy == pytest.approx((0.5, 0.5))
    assert first_result.states.tolist() == [[0, 100]]


def test_non_native_or_misaligned_raw_tile_geometry_is_rejected():
    source = nav()
    coarse = evidence(source, {(0, 0): tile(4, ((0, 0, 0),))}, origin=(0.0, 0.0), resolution=1.0)
    with pytest.raises(ValueError, match="source navigation resolution"):
        build_room_map(coarse, source)

    misaligned = evidence(source, {(0, 0): tile(4, ((0, 0, 0),))}, origin=(0.1, 0.0))
    with pytest.raises(ValueError, match="not aligned"):
        build_room_map(misaligned, source)


def test_raw_tile_retention_limit_matches_provider_contract():
    source = nav()
    too_many = {(row, 0): tile(4) for row in range(4097)}
    with pytest.raises(ValueError, match="4096-tile/16-MiB"):
        evidence(source, too_many, origin=(0.0, 0.0))
