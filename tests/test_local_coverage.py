"""Local measured-ray vote collection stays exact inside requested map cells."""

from dataclasses import replace

import numpy as np
import pytest

from neusymnav.contracts import FrameKey, Observation
from neusymnav.mapping.local_coverage import collect_local_measured_votes
from neusymnav.mapping.occupancy import NavMapper, RobotGeometry


def mapper(*, stride=2, origin_xy=(0.3, -1.2), floor_z_m=3.0):
    return NavMapper(
        robot=RobotGeometry("cylinder-v1", 0.10, 1.0, 0.0, 0.10),
        floor_z_m=floor_z_m,
        floor_datum_source="fixture-calibration:v1",
        calibration_hash="a" * 64,
        resolution_m=0.1,
        origin_xy=origin_xy,
        tile_size_cells=16,
        height_bin_m=0.1,
        min_depth_m=0.15,
        max_depth_m=5.0,
        sampling_stride=stride,
        snapshot_radius_m=3.0,
    )


def observation(*, size=(49, 57), stride_certificates=True):
    height, width = size
    depth = np.full((height, width), 2.0, np.float32)
    depth[16:24, 24:32] = 1.5  # body-height occupied returns
    valid = np.ones((height, width), bool)
    valid[::7, ::5] = False
    depth[1::11, 3::13] = np.nan
    valid[1::11, 3::13] = False
    depth[2, 4] = 0.1  # valid sensor sample outside the mapper range
    depth[2, 6] = 5.0  # max depth is exclusive
    no_return = np.zeros_like(valid)
    far_plane = np.zeros_like(valid)
    if stride_certificates:
        no_return[0, 0] = True
        far_plane[0, 2] = True
        valid[0, 0] = valid[0, 2] = False

    focal = 48.0
    intrinsics = np.array(
        [[focal, 0.0, width // 2], [0.0, focal, height // 2], [0.0, 0.0, 1.0]],
        dtype=np.float64,
    )
    yaw = 0.63
    c, s = np.cos(yaw), np.sin(yaw)
    yaw_rotation = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    camera_down = np.diag([1.0, -1.0, -1.0])
    pose = np.eye(4)
    pose[:3, :3] = yaw_rotation @ camera_down
    pose[:3, 3] = [0.55, -0.25, 5.0]
    return Observation(
        FrameKey("episode", "navigation", 4),
        1_000_000_004,
        "host_monotonic:fixture",
        4.0,
        np.zeros((height, width, 3), np.uint8),
        depth,
        valid,
        intrinsics,
        pose,
        "down-camera-calibration:v1",
        1,
        "depth_only",
        no_return=no_return if stride_certificates else None,
        no_return_range_m=2.5 if stride_certificates else None,
        far_plane=far_plane if stride_certificates else None,
        far_plane_range_m=5.0 if stride_certificates else None,
    )


def _coverage_mask(nav, bounds_xy):
    (xmin, ymin), (xmax, ymax) = bounds_xy
    xs = nav.origin_xy[0] + (np.arange(nav.states.shape[1]) + 0.5) * nav.resolution_m
    ys = nav.origin_xy[1] + (np.arange(nav.states.shape[0]) + 0.5) * nav.resolution_m
    return ((ys[:, None] >= ymin) & (ys[:, None] <= ymax)
            & (xs[None, :] >= xmin) & (xs[None, :] <= xmax))


def test_local_votes_match_full_measured_oracle_inside_requested_cells():
    mapper_instance = mapper()
    obs = observation(size=(101, 121))
    bounds = ((0.15, -0.65), (0.95, 0.15))
    measured = replace(
        obs,
        no_return=None,
        no_return_range_m=None,
        far_plane=None,
        far_plane_range_m=None,
    )

    # The unfiltered source oracle uses the actual occupancy integration path.
    full_votes = mapper_instance._core._integrate(
        mapper_instance._adapt(measured)
    ).frame_votes
    local_votes, measured_ray_count, selected_ray_count = collect_local_measured_votes(
        obs, mapper_instance._core, bounds
    )
    local_without_certificates, _, _ = collect_local_measured_votes(
        measured, mapper_instance._core, bounds
    )
    full_coverage = mapper_instance._coverage_from_votes(obs, full_votes)
    local_coverage = mapper_instance._coverage_from_votes(obs, local_votes)
    target = _coverage_mask(full_coverage, bounds)

    assert measured_ray_count > selected_ray_count > 0
    assert selected_ray_count * 2 < measured_ray_count
    assert np.array_equal(local_votes.planar_free, local_without_certificates.planar_free)
    assert np.array_equal(local_votes.planar_hit, local_without_certificates.planar_hit)
    assert np.array_equal(local_votes.floor_hit, local_without_certificates.floor_hit)
    assert np.array_equal(local_votes.height_free, local_without_certificates.height_free)
    assert np.array_equal(local_votes.height_hit, local_without_certificates.height_hit)
    assert target.any()
    assert np.array_equal(full_coverage.states[target], local_coverage.states[target])
    assert np.array_equal(full_coverage.floor_support[target], local_coverage.floor_support[target])
    assert np.array_equal(full_coverage.clearance[target], local_coverage.clearance[target])


def test_local_filter_includes_a_ray_tangent_to_expanded_planar_and_height_bounds():
    single = mapper(stride=1, origin_xy=(0.0, 0.0), floor_z_m=0.0)
    pose = np.eye(4)
    pose[:3, :3] = np.diag([1.0, -1.0, -1.0])
    pose[:3, 3] = [-0.2, 0.0, 2.1]
    obs = Observation(
        FrameKey("episode", "navigation", 0),
        1,
        "host_monotonic:fixture",
        0.0,
        np.zeros((1, 1, 3), np.uint8),
        np.ones((1, 1), np.float32),
        np.ones((1, 1), bool),
        np.eye(3, dtype=np.float64),
        pose,
        "down-camera-calibration:v1",
        1,
        "depth_only",
    )

    _votes, measured_ray_count, selected_ray_count = collect_local_measured_votes(
        obs, single._core, ((0.0, 0.0), (0.0, 0.0))
    )

    assert measured_ray_count == 1
    assert selected_ray_count == 1


def test_local_vote_collection_rejects_reversed_bounds_and_excessive_rays():
    mapper_instance = mapper()
    obs = observation(stride_certificates=False)
    with pytest.raises(ValueError, match="bounds"):
        collect_local_measured_votes(
            obs, mapper_instance._core, ((1.0, 0.0), (0.0, 1.0))
        )

    large = observation(size=(317, 317), stride_certificates=False)
    large = replace(large,
                    depth_m=np.full_like(large.depth_m, 2.0),
                    valid_depth=np.ones_like(large.valid_depth))
    crowded_mapper = mapper(stride=1)
    with pytest.raises(MemoryError, match="ray count"):
        collect_local_measured_votes(
            large, crowded_mapper._core, ((-0.5, -0.5), (0.5, 0.5))
        )
