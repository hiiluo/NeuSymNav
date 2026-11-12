"""Opt-in adapter for the pinned Rebuild OccuSG M4 + M5 room stage.

The M4 worker segments NeuSymNav's already-measured occupancy raster. This
adapter does not claim to run Rebuild's RGB-D/M3 mapping stage.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
from copy import copy
from contextlib import contextmanager
from pathlib import Path
import sys
import threading
from types import ModuleType
from typing import Any

import numpy as np

from ..contracts import NavSnapshot, Region, RegionSnapshot
from .geometry import intersection_area, valid_ring
from ._types import Polygon2D

EXPECTED_WORKER_SHA256 = "6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693"
EXPECTED_SOURCE_TREE_SHA256 = "60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0"
DEFAULT_SOURCE_ROOT = Path("/home/kiettran05/Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG")


@contextmanager
def _no_bytecode_writes():
    """Prevent importlib from creating __pycache__ under the read-only source."""
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = previous


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _python_tree_sha256(root: Path) -> str:
    """Hash every Python source file by relative path and file digest."""
    package = root / "src" / "standalone_sg"
    paths = sorted(package.rglob("*.py"))
    if not paths:
        raise ValueError("Rebuild source package has no Python files")
    h = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(package).as_posix().encode("utf-8")
        h.update(relative)
        h.update(b"\0")
        h.update(bytes.fromhex(_sha256(path)))
    return h.hexdigest()


def _load_private_package(package_dir: Path, namespace: str) -> ModuleType:
    """Load source under a unique package name, avoiding standalone_sg clashes."""
    existing = sys.modules.get(namespace)
    if existing is not None:
        return existing
    init = package_dir / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        namespace, init, submodule_search_locations=[str(package_dir)]
    )
    if spec is None or spec.loader is None:
        raise ValueError("cannot load pinned Rebuild standalone_sg package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[namespace] = module
    try:
        with _no_bytecode_writes():
            spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(namespace, None)
        raise
    return module


class RebuildRegionBackend:
    """RegionBackend-compatible owner backed by Rebuild's source M5 stage."""

    def __init__(self, binary: str | Path, *, floor_id: str, source_root: str | Path = DEFAULT_SOURCE_ROOT,
                 decomp_threshold_m: float = 1.5, safety_distance_m: float = 0.5,
                 timeout_s: float = 30.0, preprocessing_policy: str = "source",
                 expected_worker_sha256: str = EXPECTED_WORKER_SHA256,
                 expected_source_tree_sha256: str = EXPECTED_SOURCE_TREE_SHA256):
        if not isinstance(floor_id, str) or not floor_id:
            raise ValueError("floor_id required")
        if preprocessing_policy != "source":
            raise ValueError("Rebuild backend is pinned to its source preprocessing policy")
        for name, value in (("decomp_threshold_m", decomp_threshold_m), ("safety_distance_m", safety_distance_m), ("timeout_s", timeout_s)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if decomp_threshold_m <= 0 or safety_distance_m < 0 or timeout_s <= 0:
            raise ValueError("threshold/timeout must be positive and safety distance nonnegative")
        root = Path(source_root).expanduser().resolve(strict=True)
        package_dir = root / "src" / "standalone_sg"
        worker = Path(binary).expanduser().resolve(strict=True)
        if not package_dir.is_dir() or not (package_dir / "__init__.py").is_file():
            raise ValueError("Rebuild source root must contain src/standalone_sg")
        worker_hash = _sha256(worker)
        if worker_hash != expected_worker_sha256:
            raise ValueError("Rebuild worker SHA-256 mismatch")
        source_hash = _python_tree_sha256(root)
        if source_hash != expected_source_tree_sha256:
            raise ValueError("Rebuild source tree SHA-256 mismatch")
        namespace = "_neusymnav_rebuild_occusg_" + worker_hash[:16]
        with _no_bytecode_writes():
            _load_private_package(package_dir, namespace)
            stage_mod = __import__(namespace + ".pipeline.stages", fromlist=["DudeM5RegionStage"])
            client_mod = __import__(namespace + ".regions.dude_client", fromlist=["DuDeWorkerClient"])
            processor_mod = __import__(namespace + ".regions.pipeline", fromlist=["RegionUpdateProcessor"])
            projection_mod = __import__(namespace + ".mapping.projection", fromlist=["FreeSpaceGrid2D"])
        source_config = client_mod.DuDeConfig(
            decomp_threshold_m=float(decomp_threshold_m), safety_distance_m=float(safety_distance_m),
            timeout_s=float(timeout_s), preprocessing_policy=preprocessing_policy,
        )
        worker_client = client_mod.DuDeWorkerClient(worker, source_config)
        processor = processor_mod.RegionUpdateProcessor()
        self.stage = stage_mod.DudeM5RegionStage(worker_client, processor)
        self._grid_type = projection_mod.FreeSpaceGrid2D
        self.floor_id = floor_id
        self.worker_path = worker
        self.worker_sha256 = worker_hash
        self.source_tree_sha256 = source_hash
        self.source_root = root
        self.source_namespace = namespace
        self._snapshot: RegionSnapshot | None = None
        self.accepted_nav: NavSnapshot | None = None
        self.inflight_nav: NavSnapshot | None = None
        self.last_reason: str | None = None
        self._last_request = -1
        self._episode: str | None = None
        self._native_geometry = None
        self._lock = threading.Lock()
        self._stats = {"requests": 0, "accepted_updates": 0, "rejected_updates": 0,
                       "native_resets": 0, "backend": "rebuild_m4_m5"}
        self._reasons: dict[str, int] = {}

    @staticmethod
    def _bridge(nav: NavSnapshot, grid_type: Any):
        """Preserve raster states; only measured floor/clearance get z values."""
        states = np.array(nav.states, dtype=np.int8, copy=True)
        supported = np.asarray(nav.floor_support, dtype=bool)
        clear = np.asarray(nav.clearance, dtype=np.float64)
        floor = np.full(states.shape, np.nan, dtype=np.float64)
        ceiling = np.full(states.shape, np.nan, dtype=np.float64)
        floor[supported] = float(nav.floor_z_m)
        valid_ceiling = supported & (clear > 0) & np.isfinite(clear)
        ceiling[valid_ceiling] = float(nav.floor_z_m) + clear[valid_ceiling]
        return grid_type(values=states, resolution_m=nav.resolution_m, origin_xy=nav.origin_xy,
                         z_floor=floor, z_ceiling=ceiling, revision=nav.revision,
                         frame_id="world", projection_mode="full_refresh", updated=True,
                         source="NeuSymNav.NavSnapshot.measured_v1", backend="neusymnav_measured_bridge")

    def _begin(self, nav: NavSnapshot):
        if self._episode is not None and nav.episode_id != self._episode:
            raise ValueError("new episode requires a new region owner")
        if nav.revision <= self._last_request:
            raise ValueError("region input revisions must increase")
        self._episode = nav.episode_id
        self._last_request = nav.revision
        self._stats.update(requests=self._stats["requests"] + 1, last_input_revision=nav.revision,
                           last_input_shape=list(nav.states.shape), last_input_origin=list(nav.origin_xy),
                           last_input_resolution_m=nav.resolution_m, last_raw_region_count=None,
                           last_native_status=None, last_native_branch=None, last_native_invoked=False)

    def _stale(self, nav: NavSnapshot, reason: str):
        self.last_reason = str(reason)
        self._stats["rejected_updates"] += 1
        key = self.last_reason[:160]
        if key not in self._reasons and len(self._reasons) >= 32:
            key = "other"
        self._reasons[key] = self._reasons.get(key, 0) + 1
        self._stats["last_rejection_reason"] = self.last_reason[:160]
        old = self._snapshot
        if old is None:
            return RegionSnapshot(nav.episode_id, 0, nav.revision, self.floor_id, {}, True)
        return RegionSnapshot(old.episode_id, old.revision, old.source_map_revision,
                              old.floor_id, old.regions, True)

    def mark_unavailable(self, nav: NavSnapshot, reason: str):
        if not isinstance(nav, NavSnapshot):
            raise ValueError("expected NavSnapshot")
        with self._lock:
            self._begin(nav)
            return self._stale(nav, reason)

    def update(self, nav: NavSnapshot) -> RegionSnapshot:
        if not isinstance(nav, NavSnapshot):
            raise ValueError("expected NavSnapshot")
        with self._lock:
            self._begin(nav)
            if not np.any(nav.states == 0):
                return self._stale(nav, "no_observed_free_support")
            self.inflight_nav = nav
            try:
                geometry = (nav.origin_xy, nav.resolution_m, nav.states.shape)
                if self._native_geometry is not None and self._native_geometry != geometry:
                    ack = self.stage.worker.reset()
                    if not isinstance(ack, dict) or ack.get("status") != "reset":
                        raise ValueError("Rebuild native geometry reset was not acknowledged")
                    self._stats["native_resets"] += 1
                self._native_geometry = geometry
                self._stats["last_native_invoked"] = True
                original_processor = self.stage.processor
                trial = copy(original_processor)
                trial.guard = copy(original_processor.guard)
                trial.tracker = copy(original_processor.tracker)
                trial.tracker._tracks = [copy(track) for track in original_processor.tracker._tracks]
                self.stage.processor = trial
                committed_processor = False
                with _no_bytecode_writes():
                    outcome = self.stage.update(self._bridge(nav, self._grid_type),
                                                 timestamp_s=nav.capture_monotonic_ns / 1e9)
                response = getattr(self.stage, "last_response", None) or {}
                raw_regions = response.get("regions")
                self._stats.update(last_raw_region_count=len(raw_regions) if isinstance(raw_regions, list) else None,
                                   last_m5_region_count=len(outcome.current_regions),
                                   last_native_status=outcome.backend_status,
                                   last_native_branch=outcome.backend_branch,
                                   last_kernel_invoked=response.get("diagnostics", {}).get("kernel_invoked"))
                if not outcome.accepted:
                    return self._stale(nav, outcome.reason or "rebuild_m5_rejected")
                current = {}
                for candidate in outcome.current_regions:
                    if candidate.source_grid_revision != nav.revision:
                        raise ValueError("Rebuild M5 candidate revision mismatch")
                    if candidate.persistent_id is None:
                        raise ValueError("Rebuild M5 tracker returned no canonical ID")
                    if not valid_ring(candidate.polygon.outer):
                        raise ValueError("Rebuild M5 polygon is not simple and nonzero")
                    key = f"region:{self.floor_id}:{candidate.persistent_id}"
                    adjacency = tuple(sorted(f"region:{self.floor_id}:{int(i)}" for i in candidate.adjacent_region_ids))
                    old = {} if self._snapshot is None else self._snapshot.regions
                    polygon = np.asarray(candidate.polygon.outer, dtype=np.float64)
                    predecessors = tuple(sorted(rid for rid, previous in old.items()
                        if intersection_area(Polygon2D(tuple(map(tuple, polygon))),
                                            Polygon2D(tuple(map(tuple, previous.polygon)))) > 1e-10))
                    current[key] = Region(key, polygon, predecessors, adjacency)
                snapshot = RegionSnapshot(nav.episode_id,
                    1 if self._snapshot is None else self._snapshot.revision + 1,
                    nav.revision, self.floor_id, current, False)
                self._snapshot = snapshot
                self.accepted_nav = nav
                self.stage.processor = trial
                committed_processor = True
                self.last_reason = None
                self._stats["accepted_updates"] += 1
                self._stats["last_rejection_reason"] = None
                return snapshot
            except (ValueError, OSError, RuntimeError) as exc:
                return self._stale(nav, str(exc))
            finally:
                if "committed_processor" in locals() and not committed_processor:
                    self.stage.processor = original_processor
                self.inflight_nav = None

    def diagnostics(self):
        with self._lock:
            result = dict(self._stats, reason_counts=dict(self._reasons),
                source_revision="sha256-pinned-source-tree", source_root=str(self.source_root),
                source_namespace=self.source_namespace, worker_path=str(self.worker_path),
                worker_sha256=self.worker_sha256, source_tree_sha256=self.source_tree_sha256,
                preprocessing_policy="source",
                input_scope="NeuSymNav measured NavSnapshot; Rebuild M4 segmentation + source M5 guard/tracker")
            timing = getattr(self.stage, "last_timing", {})
            result["last_timing"] = dict(timing)
            return result

    def close(self):
        self.stage.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
