"""Child-process service that owns one Rebuild M1--M5 episode."""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from copy import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
from types import ModuleType
from typing import Any

import numpy as np

from neusymnav.regions.geometry import valid_ring


MAX_CELLS = 1_000_000
MAX_REGIONS = 4096
MAX_LINE_BYTES = 32 * 1024 * 1024
M3_STATE_CONVERSION = "negative_unknown_zero_free_positive_score_to_occupied_100_v1"
EXPECTED_SOURCE_TREE_SHA256 = "60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0"
EXPECTED_M23_SHA256 = "617477524aa81acb0a0a46575741497aa15ed9b095f8fd72f92e09a81043cdc6"
EXPECTED_M4_SHA256 = "6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_tree_sha256(root: Path) -> str:
    package = root / "src" / "standalone_sg"
    files = sorted(package.rglob("*.py"))
    if len(files) != 50:
        raise ValueError(f"Rebuild Python source count changed: {len(files)}")
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.relative_to(package).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(path)))
    return digest.hexdigest()


@contextmanager
def _read_only_imports():
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = old


def _load_package(package_dir: Path, namespace: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        namespace, package_dir / "__init__.py",
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise ValueError("cannot load pinned Rebuild Python package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[namespace] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(namespace, None)
        raise
    return module


def _decode_array(value: Any, name: str) -> np.ndarray:
    if not isinstance(value, dict) or set(value) != {"dtype", "shape", "sha256", "data"}:
        raise ValueError(f"{name} wire array fields are invalid")
    dtype = np.dtype(value["dtype"])
    if dtype.str not in {"|u1", "<f4", "<f8", "|b1"}:
        raise ValueError(f"{name} dtype is unsupported")
    shape = value["shape"]
    if not isinstance(shape, list) or not shape or any(type(n) is not int or n <= 0 for n in shape):
        raise ValueError(f"{name} shape is invalid")
    count = math.prod(shape)
    if count > MAX_CELLS * 3:
        raise ValueError(f"{name} exceeds array element cap")
    raw = base64.b64decode(value["data"], validate=True)
    if len(raw) != count * dtype.itemsize or _sha256_bytes(raw) != value["sha256"]:
        raise ValueError(f"{name} byte length or SHA-256 mismatch")
    result = np.frombuffer(raw, dtype=dtype).reshape(shape)
    return result.copy()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _encode_array(value: np.ndarray) -> dict[str, Any]:
    canonical = value.astype(value.dtype.newbyteorder("<"), copy=False)
    raw = canonical.tobytes(order="C")
    return {
        "dtype": canonical.dtype.str, "shape": list(canonical.shape),
        "sha256": _sha256_bytes(raw),
        "data": base64.b64encode(raw).decode("ascii"),
    }


def _region_payload(candidates) -> list[dict[str, Any]]:
    regions = []
    for item in candidates:
        if item.persistent_id is None:
            raise ValueError("M5 output has no persistent canonical region ID")
        ring = tuple(tuple(float(v) for v in point) for point in item.polygon.outer)
        if len(ring) < 3 or any(len(point) != 2 or not all(math.isfinite(v) for v in point) for point in ring):
            raise ValueError("M5 output polygon is malformed")
        if not valid_ring(ring):
            raise ValueError("M5 output polygon failed simple/nonzero validation")
        regions.append({
            "persistent_id": str(item.persistent_id),
            "source_map_revision": int(item.source_grid_revision),
            "polygon": [list(point) for point in ring],
            "adjacency": sorted(str(value) for value in item.adjacent_region_ids),
            "timestamp_s": float(item.timestamp_s),
        })
    return regions


def _trial_region_processor(processor):
    """Copy mutable M5 guard/tracker state so rejected geometry cannot advance it."""
    trial = copy(processor)
    trial.guard = copy(processor.guard)
    trial.tracker = copy(processor.tracker)
    trial.tracker._tracks = [copy(track) for track in processor.tracker._tracks]
    return trial


def _validated_m5_result(outcome):
    """Return accepted regions only when M5 geometry is valid; otherwise retain stale state."""
    if not outcome.accepted:
        return False, None, outcome.reason
    try:
        return True, _region_payload(outcome.current_regions), None
    except ValueError as exc:
        return False, None, f"invalid_m5_geometry:{exc}"


class _PersistentMappingRecords(list):
    """Keep Rebuild's first-vs-later M3 mode state after consuming each record.

    The pinned Rebuild mapping stage chooses ``full_refresh`` when its records
    list is falsey and ``partial_update`` otherwise. NeuSymNav consumes each
    detailed update record immediately to keep memory bounded, so ordinary
    ``list.pop`` would accidentally reset that mode decision every frame.
    Preserve only the one-bit 'has integrated' state while keeping list length
    bounded by the current record.
    """
    def __init__(self):
        super().__init__()
        self._has_integrated = False

    def append(self, item):
        self._has_integrated = True
        super().append(item)

    def __bool__(self):
        return self._has_integrated or len(self)>0


class RebuildEpisode:
    """Own M2/M3 and M4/M5 source stages for exactly one ordered episode."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        root = Path(config["source_root"]).expanduser().resolve(strict=True)
        m23 = Path(config["m23_binary"]).expanduser().resolve(strict=True)
        m4 = Path(config["m4_binary"]).expanduser().resolve(strict=True)
        source_hash = _source_tree_sha256(root)
        m23_hash, m4_hash = _sha256(m23), _sha256(m4)
        if source_hash != config.get("expected_source_sha256", EXPECTED_SOURCE_TREE_SHA256):
            raise ValueError("Rebuild Python source closure SHA-256 mismatch")
        if m23_hash != config.get("expected_m23_sha256", EXPECTED_M23_SHA256):
            raise ValueError("Rebuild M2/M3 binary SHA-256 mismatch")
        if m4_hash != config.get("expected_m4_sha256", EXPECTED_M4_SHA256):
            raise ValueError("Rebuild M4 binary SHA-256 mismatch")
        namespace = "_neusymnav_rebuild_m1_m5_" + m23_hash[:12] + m4_hash[:12]
        package_dir = root / "src" / "standalone_sg"
        sys.dont_write_bytecode = True
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        with _read_only_imports():
            _load_package(package_dir, namespace)
            mapping_mod = __import__(namespace + ".mapping.native_pipeline", fromlist=["NativeRGBDMappingStage"])
            native_mod = __import__(namespace + ".regions.dude_client", fromlist=["DuDeWorkerClient"])
            processor_mod = __import__(namespace + ".regions.pipeline", fromlist=["RegionUpdateProcessor"])
            stages_mod = __import__(namespace + ".pipeline.stages", fromlist=["DudeM5RegionStage"])
            frame_mod = __import__(namespace + ".contracts.frames", fromlist=["CameraIntrinsics"])
            packet_mod = __import__(namespace + ".pipeline.contracts", fromlist=["FramePacket"])
        self.mapping_mod, self.native_mod = mapping_mod, native_mod
        self.frame_mod, self.packet_mod = frame_mod, packet_mod
        self.mapping = mapping_mod.NativeRGBDMappingStage(
            m23, resolution_m=float(config["resolution_m"]),
            timeout_s=float(config["m23_timeout_s"]),
            default_max_range_m=float(config["max_range_m"]),
        )
        # Rebuild selects M3 projection mode from records truthiness. We remove
        # each detailed record below, but must retain its bounded mode state.
        self.mapping._native.records = _PersistentMappingRecords()
        try:
            dude = native_mod.DuDeWorkerClient(
                m4, native_mod.DuDeConfig(
                    decomp_threshold_m=float(config["decomp_threshold_m"]),
                    safety_distance_m=float(config["safety_distance_m"]),
                    timeout_s=float(config["m4_timeout_s"]),
                    preprocessing_policy="source",
                ),
            )
            self.region_stage = stages_mod.DudeM5RegionStage(
                dude, processor_mod.RegionUpdateProcessor()
            )
        except BaseException:
            self.mapping.close()
            raise
        self.episode_id: str | None = None
        self.sensor_id: str | None = None
        self.calibration_id: str | None = None
        self.clock_domain: str | None = None
        self.last_index = -1
        self.last_capture_ns = -1
        self.last_sim_time_s = -math.inf
        self.request_revision = 0
        self.m5_revision = 0
        self.accepted_map_revision: int | None = None
        self.accepted_regions: list[dict[str, Any]] = []
        self.poisoned = False
        self.closed = False
        self.source_hash = source_hash
        self.worker_hash = m23_hash
        self.m4_hash = m4_hash
        self.config_hash = hashlib.sha256(json.dumps(
            {**config, "m3_state_conversion": M3_STATE_CONVERSION},
            sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()

    def _check(self, payload: dict[str, Any]):
        if self.closed:
            raise ValueError("episode worker is closed")
        if self.poisoned:
            raise ValueError("episode worker is poisoned; replay required")
        if payload.get("wire_version") != 1:
            raise ValueError("unsupported RGB-D wire version")
        frame = payload.get("frame")
        mapping = payload.get("mapping")
        arrays = payload.get("arrays")
        if not isinstance(frame, dict) or not isinstance(mapping, dict) or not isinstance(arrays, dict):
            raise ValueError("RGB-D wire envelope is malformed")
        if frame.get("coordinate_convention") != "canonical_z_up_optical_v1":
            raise ValueError("unsupported coordinate convention")
        if frame.get("depth_units") != "m" or frame.get("depth_representation") != "axial" or mapping.get("depth_scale_to_m") != 1.0:
            raise ValueError("depth must be metric axial metres")
        if frame.get("pose_source") != "simulator_ground_truth":
            raise ValueError("pose source must be simulator_ground_truth")
        expected_mapping = {
            "resolution_m": float(self.config["resolution_m"]),
            "backprojection_stride": int(self.config["backprojection_stride"]),
            "min_depth_m": float(self.config["min_depth_m"]),
            "max_depth_m": float(self.config["max_depth_m"]),
            "max_range_m": float(self.config["max_range_m"]),
            "depth_scale_to_m": 1.0,
        }
        if mapping != expected_mapping:
            raise ValueError("frame mapping policy differs from the pinned episode config")
        for name in ("rgb", "depth_m", "valid_depth", "K", "T_world_camera"):
            if name not in arrays:
                raise ValueError(f"missing wire array: {name}")
        if self.episode_id is not None and frame["scene_id"] != self.episode_id:
            raise ValueError("episode changed; open a new worker")
        if frame["scene_id"] != self.config.get("episode_id"):
            raise ValueError("frame episode differs from worker profile")
        if self.sensor_id is not None and frame.get("sensor_id") != self.sensor_id:
            raise ValueError("sensor changed within episode")
        if self.calibration_id is not None and frame.get("calibration_id") != self.calibration_id:
            raise ValueError("calibration changed within episode")
        if self.clock_domain is not None and frame.get("clock_domain") != self.clock_domain:
            raise ValueError("clock domain changed within episode")
        index = frame.get("frame_index")
        capture_ns = frame.get("capture_monotonic_ns")
        sim_time = frame.get("timestamp_s")
        if type(index) is not int or index <= self.last_index:
            raise ValueError("duplicate or out-of-order frame index")
        if type(capture_ns) is not int or capture_ns < self.last_capture_ns:
            raise ValueError("capture timestamp moved backwards")
        if isinstance(sim_time, bool) or not isinstance(sim_time, (int, float)) or not math.isfinite(sim_time) or sim_time < self.last_sim_time_s:
            raise ValueError("simulator timestamp moved backwards or is invalid")
        rgb = _decode_array(arrays["rgb"], "rgb")
        depth = _decode_array(arrays["depth_m"], "depth_m")
        valid = _decode_array(arrays["valid_depth"], "valid_depth")
        k = _decode_array(arrays["K"], "K")
        pose = _decode_array(arrays["T_world_camera"], "T_world_camera")
        if rgb.ndim != 3 or rgb.shape[2] != 3 or depth.shape != rgb.shape[:2] or valid.shape != depth.shape:
            raise ValueError("RGB/depth/mask shape mismatch")
        if depth.size > MAX_CELLS or rgb.dtype != np.uint8 or depth.dtype != np.float32 or valid.dtype != np.bool_:
            raise ValueError("RGB-D dimensions or dtypes exceed the source contract")
        if k.shape != (3, 3) or pose.shape != (4, 4) or not np.isfinite(k).all() or not np.isfinite(pose).all():
            raise ValueError("K/T_world_camera is malformed")
        if np.any(valid & (~np.isfinite(depth) | (depth <= 0))):
            raise ValueError("valid mask marks invalid depth")
        if np.any(valid & ((depth < expected_mapping["min_depth_m"]) |
                           (depth > expected_mapping["max_depth_m"]))):
            raise ValueError("valid mask includes depth outside the pinned M1 range")
        return frame, mapping, rgb, depth, valid, k, pose

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        frame, mapping, rgb, depth, valid, k, pose = self._check(payload)
        self.request_revision += 1
        # Native mutation begins at build_grid. Any exception from here onward
        # poisons this episode; the host must replay the admitted prefix.
        try:
            intr = self.frame_mod.CameraIntrinsics(
                width=int(depth.shape[1]), height=int(depth.shape[0]),
                fx=float(k[0, 0]), fy=float(k[1, 1]),
                cx=float(k[0, 2]), cy=float(k[1, 2]),
                calibration_id=str(frame["calibration_id"]),
            )
            transform = self.frame_mod.Transform(
                pose, "world", "camera_optical", float(frame["timestamp_s"]),
                "ground_truth",
            )
            rgbd = self.frame_mod.RGBDFrame(
                depth, intr, transform, float(frame["timestamp_s"]),
                rgb=rgb, valid_mask=valid, frame_id=str(frame["frame_id"]),
            )
            packet = self.packet_mod.FramePacket(
                scene_id=str(frame["scene_id"]), sequence_id=str(frame["sequence_id"]),
                frame_id=str(frame["frame_id"]), frame_index=int(frame["frame_index"]),
                timestamp_s=float(frame["timestamp_s"]), input_mode="rgbd",
                base_pose_W=None,
                rgbd=rgbd,
                source_metadata={
                    "depth_units": "m", "depth_representation": "axial",
                    "depth_scale_to_m": 1.0,
                    "backprojection_stride": int(mapping["backprojection_stride"]),
                    "min_depth_m": float(mapping["min_depth_m"]),
                    "max_depth_m": float(mapping["max_depth_m"]),
                    "max_range_m": float(mapping["max_range_m"]),
                    "source_frame_key": {
                        "episode_id": str(frame["scene_id"]),
                        "sensor_id": str(frame["sensor_id"]),
                        "frame_index": int(frame["frame_index"]),
                    },
                    "capture_monotonic_ns": int(frame["capture_monotonic_ns"]),
                    "clock_domain": str(frame["clock_domain"]),
                    "calibration_id": str(frame["calibration_id"]),
                    "pose_version": int(frame["pose_version"]),
                    "geometry_sha256": str(frame["geometry_sha256"]),
                    "prefix_sha256": str(frame["prefix_sha256"]),
                    "pose_source": str(frame["pose_source"]),
                    "coordinate_convention": str(frame["coordinate_convention"]),
                    "semantic_gt_in_mapping": False,
                },
            )
            grid = self.mapping.build_grid(packet)
            if not self.mapping.records:
                raise ValueError("M1-M3 stage omitted its bounded update record")
            record = self.mapping.records.pop()
            if grid.values.size > MAX_CELLS:
                raise ValueError("M3 cell cap exceeded")
            m2_revision = int(record["m2_revision"])
            m3_revision = int(grid.revision)
            if m2_revision != m3_revision:
                raise ValueError("M2/M3 revision mismatch")
            states = np.where(grid.values < 0, -1, np.where(grid.values == 0, 0, 100)).astype(np.int8)
            floor = np.asarray(grid.z_floor, dtype=np.float64).copy()
            ceiling = np.asarray(grid.z_ceiling, dtype=np.float64).copy()
            floor_valid = np.isfinite(floor) & (states != -1)
            ceiling_valid = np.isfinite(ceiling) & (states != -1)
            floor[~floor_valid] = np.nan
            ceiling[~ceiling_valid] = np.nan
            original_processor = self.region_stage.processor
            trial_processor = _trial_region_processor(original_processor)
            self.region_stage.processor = trial_processor
            committed_m5 = False
            try:
                outcome = self.region_stage.update(grid, timestamp_s=float(frame["timestamp_s"]))
                m5_accepted, regions, m5_reason = _validated_m5_result(outcome)
                if m5_accepted:
                    if len(regions) > MAX_REGIONS:
                        raise ValueError("M5 region count cap exceeded")
                    if any(region["source_map_revision"] != m3_revision for region in regions):
                        raise ValueError("M5 region output is not bound to the current M3 revision")
                    self.accepted_regions = regions
                    self.accepted_map_revision = m3_revision
                    self.m5_revision += 1
                    committed_m5 = True
            finally:
                if not committed_m5:
                    self.region_stage.processor = original_processor
            self.episode_id = str(frame["scene_id"])
            self.sensor_id = str(frame["sensor_id"])
            self.calibration_id = str(frame["calibration_id"])
            self.clock_domain = str(frame["clock_domain"])
            self.last_index = int(frame["frame_index"])
            self.last_capture_ns = int(frame["capture_monotonic_ns"])
            self.last_sim_time_s = float(frame["timestamp_s"])
            response = {
                "status": "ok", "request_revision": self.request_revision,
                "latest_map": {
                    "revision": m3_revision, "m2_revision": m2_revision,
                    "m3_revision": m3_revision, "resolution_m": float(grid.resolution_m),
                    "origin_xy": [float(v) for v in grid.origin_xy],
                    "states": _encode_array(states), "z_floor_m": _encode_array(floor),
                    "z_ceiling_m": _encode_array(ceiling),
                    "floor_valid": _encode_array(floor_valid),
                    "ceiling_valid": _encode_array(ceiling_valid),
                    "source": frame, "source_hash": self.source_hash,
                    "worker_sha256": self.worker_hash, "m4_worker_sha256": self.m4_hash,
                    "config_sha256": self.config_hash,
                },
                "accepted_map_revision": self.accepted_map_revision,
                "regions": self.accepted_regions,
                "m5_revision": self.m5_revision if self.accepted_map_revision is not None else None,
                "regions_stale": not m5_accepted,
                "m4_status": str(outcome.backend_status),
                "m4_branch": str(outcome.backend_branch),
                "m5_accepted": bool(m5_accepted),
                "m5_reason": m5_reason,
                "timings_ms": {
                    **{k: float(v) for k, v in record.items() if k.endswith("_runtime_ms")},
                    **{k: float(v) for k, v in getattr(self.region_stage, "last_timing", {}).items()},
                },
                "record": record,
            }
            # The M1-M3 source record is returned once, not retained in RAM.
            return response
        except BaseException:
            self.poisoned = True
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        for resource in (self.region_stage, self.mapping):
            try:
                resource.close()
            except BaseException as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
        if errors:
            raise RuntimeError("; ".join(errors))


def serve(config: dict[str, Any], stdin=None, stdout=None):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    episode = None
    def send(value):
        line = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
        if len(line) > MAX_LINE_BYTES:
            raise ValueError("worker response exceeds 32 MiB cap")
        stdout.buffer.write(line)
        stdout.buffer.flush()
    try:
        episode = RebuildEpisode(config)
        send({"status": "ready", "source_sha256": episode.source_hash,
              "m23_sha256": episode.worker_hash, "m4_sha256": episode.m4_hash,
              "config_sha256": episode.config_hash})
        for line in stdin.buffer:
            if len(line) > MAX_LINE_BYTES:
                send({"status": "error", "fatal": True, "replay_required": True,
                      "error": "request exceeds 32 MiB cap"})
                break
            try:
                request = json.loads(line)
                if request == {"op": "close"}:
                    episode.close()
                    send({"status": "closed", "clean_shutdown": True})
                    return 0
                if not isinstance(request, dict) or request.get("op") != "update" or set(request) != {"op", "frame"}:
                    raise ValueError("expected update request")
                response = episode.update(request["frame"])
                try:
                    send(response)
                except BaseException:
                    episode.poisoned = True
                    raise
            except BaseException as exc:
                fatal = bool(episode is not None and episode.poisoned)
                try:
                    send({"status": "error", "fatal": fatal,
                          "replay_required": fatal,
                          "error": f"{type(exc).__name__}: {exc}"[:2048]})
                finally:
                    if fatal:
                        break
        return 0
    except BaseException as exc:
        try:
            send({"status": "startup_error", "error": f"{type(exc).__name__}: {exc}"[:2048]})
        except BaseException:
            pass
        return 1
    finally:
        if episode is not None:
            try:
                episode.close()
            except BaseException:
                pass


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-json", required=True)
    args = parser.parse_args(argv)
    config = json.loads(args.config_json)
    if not isinstance(config, dict):
        raise SystemExit("config must be a JSON object")
    return serve(config)


if __name__ == "__main__":
    raise SystemExit(main())
