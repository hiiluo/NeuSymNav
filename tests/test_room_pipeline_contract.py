import numpy as np
import pytest

from neusymnav.contracts import (
    FrameKey, Region, RegionSnapshot, RoomMapSnapshot, RoomPipelinePublication,
    dumps, loads,
)


def _map():
    states = np.array([[-1, 0], [100, 0]], dtype=np.int8)
    floor = np.array([[np.nan, 0.0], [0.0, 0.0]], dtype=np.float64)
    ceiling = np.array([[np.nan, 2.0], [2.0, 2.0]], dtype=np.float64)
    valid = np.array([[False, True], [True, True]])
    sha = "a" * 64
    return RoomMapSnapshot(
        episode_id="episode-a", map_domain_id="rebuild-m3:episode-a", revision=1,
        source=FrameKey("episode-a", "primary-rgbd", 3), capture_monotonic_ns=30,
        clock_domain="boot-a", calibration_id="calib-a", prefix_sha256=sha,
        resolution_m=0.05, origin_xy=(-0.1, 0.2), states=states,
        z_floor_m=floor, z_ceiling_m=ceiling, floor_valid=valid,
        ceiling_valid=valid, m2_revision=1, m3_revision=1, source_hash=sha,
        worker_sha256=sha, region_worker_sha256=sha, config_sha256=sha,
    )


def test_room_map_roundtrip_preserves_unknown_and_height_masks():
    snapshot = _map()
    restored = loads(dumps(snapshot))
    assert isinstance(restored, RoomMapSnapshot)
    np.testing.assert_array_equal(restored.states, snapshot.states)
    np.testing.assert_array_equal(restored.floor_valid, snapshot.floor_valid)
    assert np.isnan(restored.z_floor_m[0, 0])
    assert not restored.states.flags.writeable


def test_unknown_cells_cannot_claim_height_evidence():
    snapshot = _map()
    floor = snapshot.z_floor_m.copy()
    floor[0, 0] = 0.0
    floor_valid = snapshot.floor_valid.copy()
    floor_valid[0, 0] = True
    with pytest.raises(ValueError, match="unknown M3 cells"):
        RoomMapSnapshot(
            episode_id=snapshot.episode_id, map_domain_id=snapshot.map_domain_id,
            revision=snapshot.revision, source=snapshot.source,
            capture_monotonic_ns=snapshot.capture_monotonic_ns,
            clock_domain=snapshot.clock_domain, calibration_id=snapshot.calibration_id,
            prefix_sha256=snapshot.prefix_sha256, resolution_m=snapshot.resolution_m,
            origin_xy=snapshot.origin_xy, states=snapshot.states, z_floor_m=floor,
            z_ceiling_m=snapshot.z_ceiling_m, floor_valid=floor_valid,
            ceiling_valid=snapshot.ceiling_valid, m2_revision=1, m3_revision=1,
            source_hash=snapshot.source_hash, worker_sha256=snapshot.worker_sha256,
            region_worker_sha256=snapshot.region_worker_sha256,
            config_sha256=snapshot.config_sha256,
        )


def test_publication_rejects_region_from_another_m3_revision():
    snapshot = _map()
    regions = RegionSnapshot("episode-a", 4, 0, "floor-0", {
        "r1": Region("r1", np.array([[0., 0.], [1., 0.], [1., 1.]])),
    }, False)
    with pytest.raises(ValueError, match="accepted M3 map revision"):
        RoomPipelinePublication("episode-a", snapshot.map_domain_id, 1,
                                snapshot, 1, regions, 4, False, False,
                                accepted_map=snapshot)


def test_publication_serializes_exact_accepted_region_pair():
    snapshot = _map()
    regions = RegionSnapshot("episode-a", 1, 1, "floor-0", {
        "r1": Region("r1", np.array([[0., 0.], [1., 0.], [1., 1.]])),
    }, False)
    publication = RoomPipelinePublication("episode-a", snapshot.map_domain_id,
                                          1, snapshot, 1, regions, 1, False,
                                          False, timings_ms={"m1": 2.5},
                                          accepted_map=snapshot)
    restored = loads(dumps(publication))
    assert restored.accepted_map_revision == restored.latest_map.revision == 1
    assert restored.regions.source_map_revision == 1
    assert restored.accepted_map.revision == 1
    assert restored.timings_ms["m1"] == 2.5


def test_publication_rejects_accepted_map_revision_ahead_of_latest():
    snapshot = _map()
    regions = RegionSnapshot("episode-a", 2, 2, "floor-0", {}, False)
    with pytest.raises(ValueError, match="cannot exceed latest M3"):
        RoomPipelinePublication("episode-a", snapshot.map_domain_id, 1,
            snapshot, 2, regions, 2, False, False, accepted_map=snapshot)


def test_failure_or_replay_required_publication_cannot_be_fresh():
    snapshot = _map()
    regions = RegionSnapshot("episode-a", 1, 1, "floor-0", {}, False)
    with pytest.raises(ValueError, match="must be stale"):
        RoomPipelinePublication("episode-a", snapshot.map_domain_id, 1,
            snapshot, 1, regions, 1, False, True, "native worker failed",
            accepted_map=snapshot)
    with pytest.raises(ValueError, match="must be stale"):
        RoomPipelinePublication("episode-a", snapshot.map_domain_id, 1,
            snapshot, 1, regions, 1, False, False, "M5 rejected update",
            accepted_map=snapshot)


def test_publication_requires_retained_map_for_older_accepted_pair():
    snapshot = _map()
    regions = RegionSnapshot("episode-a", 1, 1, "floor-0", {}, True)
    with pytest.raises(ValueError, match="requires its retained map snapshot"):
        RoomPipelinePublication("episode-a", snapshot.map_domain_id, 2,
            snapshot, 1, regions, 1, True, False)
