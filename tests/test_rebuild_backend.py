"""Opt-in Rebuild adapter contract tests (CPU-only synthetic stage outcomes)."""
from types import SimpleNamespace
from pathlib import Path

import numpy as np
import pytest

from neusymnav.contracts import FrameKey, NavSnapshot
from neusymnav.regions.rebuild_backend import RebuildRegionBackend
from neusymnav.runtime.configuration import load_config


def nav(revision=1, *, states=None, origin=(-1.0, -2.0)):
    states = np.array([[0, -1, 100], [0, 0, -1]], dtype=np.int8) if states is None else np.asarray(states, dtype=np.int8)
    if states.shape == (2, 3):
        floor_support = np.array([[True, False, True], [True, True, False]], dtype=bool)
        clearance = np.array([[1.2, 0.0, 0.0], [0.5, 1.0, 0.0]], dtype=np.float64)
    else:
        floor_support = np.zeros(states.shape, dtype=bool)
        clearance = np.zeros(states.shape, dtype=np.float64)
    return NavSnapshot("episode", revision, FrameKey("episode", "nav", revision),
        1_000_000_000 + revision, "host:boot", .25, origin, states, floor_support,
        clearance, "robot-r1", .1, "calibrated-floor", "a" * 64)


class Grid:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_bridge_preserves_exact_states_origin_and_only_measured_z():
    n = nav()
    grid = RebuildRegionBackend._bridge(n, Grid)
    assert grid.values.tolist() == n.states.tolist()
    assert grid.origin_xy == n.origin_xy and grid.resolution_m == n.resolution_m
    assert grid.z_floor[0, 0] == .1 and np.isnan(grid.z_floor[0, 1])
    assert grid.z_ceiling[0, 0] == pytest.approx(1.3)
    assert np.isnan(grid.z_ceiling[0, 1])
    assert np.isnan(grid.z_ceiling[0, 2])  # supported, but no positive clearance contract
    assert grid.source == "NeuSymNav.NavSnapshot.measured_v1"


class FakeWorker:
    def __init__(self):
        self.resets = 0
    def reset(self):
        self.resets += 1
        return {"status": "reset"}


class FakeStage:
    def __init__(self, outcomes):
        self.worker = FakeWorker()
        self.processor = SimpleNamespace(guard=SimpleNamespace(), tracker=SimpleNamespace(_tracks=[]))
        self.outcomes = iter(outcomes)
        self.last_response = {"diagnostics": {"kernel_invoked": True}}
        self.last_timing = {"m4_m5_runtime_ms": 4.2}
        self.grids = []
    def update(self, grid, *, timestamp_s):
        self.grids.append((grid, timestamp_s))
        return next(self.outcomes)
    def close(self):
        pass


def candidate(revision, persistent_id=9):
    poly = SimpleNamespace(outer=((0., 0.), (2., 0.), (2., 2.), (0., 2.)))
    return SimpleNamespace(source_grid_revision=revision, persistent_id=persistent_id,
        polygon=poly, adjacent_region_ids=())


def outcome(accepted, revision, regions=(), reason=None):
    return SimpleNamespace(accepted=accepted, current_regions=regions, reason=reason,
        backend_status="success", backend_branch="incremental")


def backend(stage):
    obj = RebuildRegionBackend.__new__(RebuildRegionBackend)
    obj.stage = stage
    obj._grid_type = Grid
    obj.floor_id = "floor-0"
    obj.worker_path = "/pinned/occusg_dude_worker"
    obj.worker_sha256 = "b" * 64
    obj.source_root = "/pinned/Rebuild_3DScene_OccuSG"
    obj.source_namespace = "_private_rebuild"
    obj.source_tree_sha256 = "c" * 64
    obj._snapshot = None
    obj.accepted_nav = None
    obj.inflight_nav = None
    obj.last_reason = None
    obj._last_request = -1
    obj._episode = None
    obj._native_geometry = None
    import threading
    obj._lock = threading.Lock()
    obj._stats = {"requests": 0, "accepted_updates": 0, "rejected_updates": 0,
                  "native_resets": 0, "backend": "rebuild_m4_m5"}
    obj._reasons = {}
    return obj


def test_source_m5_id_published_and_origin_reset_preserves_tracker_stage():
    stage = FakeStage([outcome(True, 1, (candidate(1, 9),)),
                       outcome(True, 2, (candidate(2, 9),))])
    b = backend(stage)
    first = b.update(nav())
    second = b.update(nav(2, origin=(-.5, -2.0)))
    assert list(first.regions) == ["region:floor-0:9"]
    assert list(second.regions) == ["region:floor-0:9"]
    assert second.source_map_revision == 2 and b.accepted_nav.revision == 2
    assert stage.worker.resets == 1
    assert stage.grids[0][0].values.tolist() == nav().states.tolist()
    assert b.diagnostics()["worker_sha256"] == "b" * 64


def test_stale_result_keeps_accepted_source_pair_and_rejects_bad_binding():
    b = backend(FakeStage([outcome(True, 1, (candidate(1),)),
                           outcome(False, 2, (), "M5 rejected"),
                           outcome(True, 3, (candidate(99),))]))
    accepted = b.update(nav())
    stale = b.update(nav(2))
    assert stale.stale and stale.source_map_revision == accepted.source_map_revision == 1
    assert b.accepted_nav.revision == 1 and stale.regions.keys() == accepted.regions.keys()
    malformed = b.update(nav(3))
    assert malformed.stale and b.accepted_nav.revision == 1
    assert "revision mismatch" in b.last_reason


def test_invalid_candidate_rolls_back_source_m5_tracker_state():
    bad = candidate(2)
    bad.polygon = SimpleNamespace(outer=((0., 0.), (2., 2.), (0., 2.), (2., 0.)))
    class MutatingStage(FakeStage):
        def update(self, grid, *, timestamp_s):
            self.processor.tracker._tracks.append("trial mutation")
            return super().update(grid, timestamp_s=timestamp_s)
    stage = MutatingStage([outcome(True, 1, (candidate(1),)), outcome(True, 2, (bad,))])
    b = backend(stage)
    b.update(nav())
    accepted_processor = stage.processor
    accepted_tracks = list(stage.processor.tracker._tracks)
    stale = b.update(nav(2))
    assert stale.stale and b.accepted_nav.revision == 1
    assert "not simple" in b.last_reason
    assert stage.processor is accepted_processor
    assert stage.processor.tracker._tracks == accepted_tracks


def test_no_free_is_unavailable_and_never_calls_rebuild_stage():
    stage = FakeStage([])
    b = backend(stage)
    result = b.update(nav(states=[[-1, 100]]))
    assert result.stale and not stage.grids and b.accepted_nav is None


def test_region_backend_config_is_opt_in_and_rejects_unused_source_root(tmp_path):
    import json
    source = "/home/kiettran05/Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG"
    base = {"schema_version": 1, "mode": "live", "profile": "baseline",
        "episode": {"id": "e", "primary_sensor_id": "rgbd", "floor_id": "f"},
        "floor": {"z_m": 0.0, "datum_source": "calibration", "calibration_sha256": "a" * 64},
        "workers": {"region": {"backend": "rebuild_m4_m5", "source_root": source}}}
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(base))
    assert load_config(config_path).data["workers"]["region"]["backend"] == "rebuild_m4_m5"
    base["workers"]["region"] = {"backend": "dude", "source_root": source}
    config_path.write_text(json.dumps(base))
    with pytest.raises(ValueError, match="only valid for rebuild_m4_m5"):
        load_config(config_path)
    base["workers"] = {"sensor": {"backend": "rebuild_m4_m5"}}
    config_path.write_text(json.dumps(base))
    with pytest.raises(ValueError, match="unknown fields"):
        load_config(config_path)


def test_full_room_pipeline_config_is_explicit_and_validated(tmp_path):
    import json
    from neusymnav.runtime.configuration import file_sha256
    source = Path("/home/kiettran05/Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG")
    base = {"schema_version": 1, "mode": "live", "profile": "baseline",
        "episode": {"id": "e", "primary_sensor_id": "rgbd", "floor_id": "f"},
        "floor": {"z_m": 0., "datum_source": "calibration", "calibration_sha256": "a" * 64},
        "workers": {"room_pipeline": {
            "source_root": str(source),
            "m23_binary": {"path": str(source / "build/native-m3/occupancy/standalone_sg_octomap_fixture_runner"),
                           "sha256": "617477524aa81acb0a0a46575741497aa15ed9b095f8fd72f92e09a81043cdc6"},
            "m4_binary": {"path": str(source / "build/native-m4-dude/occusg_dude_worker"),
                          "sha256": "6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693"},
            "ipc_timeout_s": 60., "resolution_m": .05, "backprojection_stride": 1,
            "min_depth_m": .1, "max_depth_m": 10., "max_range_m": 8.}}}
    config_path = tmp_path / "room-pipeline.json"
    config_path.write_text(json.dumps(base))
    loaded = load_config(config_path)
    assert loaded.data["workers"]["room_pipeline"]["source_root"] == str(source.resolve())
    assert file_sha256(Path(base["workers"]["room_pipeline"]["m23_binary"]["path"])) == base["workers"]["room_pipeline"]["m23_binary"]["sha256"]
    from neusymnav.runtime.configuration import Configuration
    from neusymnav.runtime.launcher import _assets
    resources, _issues = _assets(Configuration(config_path, loaded.data))
    assert resources["room_pipeline_pins"]["source_sha256"] == "60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0"
    assert resources["room_m23"].is_file() and resources["room_m4"].is_file()
    base["workers"]["room_pipeline"]["backprojection_stride"] = 0
    config_path.write_text(json.dumps(base))
    with pytest.raises(ValueError, match="positive finite integer"):
        load_config(config_path)
