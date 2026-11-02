#!/usr/bin/env python3
"""Compare the NeuSymNav RGB-D adapter lane with direct pinned Rebuild stages.

Supports a bounded synthetic sequence or an exact admitted-session recording.
It intentionally calls the pinned source M1-M5 classes directly for the oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from neusymnav.contracts import FrameKey, Observation
from neusymnav.regions.rebuild_rgbd_input import RebuildRGBDConfig
from neusymnav.regions.rebuild_room_session import (
    RebuildRoomSession, _decode_input_array, replay_recording,
)
from neusymnav.regions.rebuild_room_worker import (
    EXPECTED_M23_SHA256, EXPECTED_M4_SHA256, EXPECTED_SOURCE_TREE_SHA256,
    _region_payload, _sha256, _source_tree_sha256,
)


SOURCE_ROOT = Path("/home/kiettran05/Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG")
M23 = SOURCE_ROOT / "build/native-m3/occupancy/standalone_sg_octomap_fixture_runner"
M4 = SOURCE_ROOT / "build/native-m4-dude/occusg_dude_worker"
MAX_RECORDED_SEQUENCE_BYTES = 256 * 1024**2


def _observation(index: int) -> Observation:
    height, width = 48, 64
    yy, xx = np.mgrid[:height, :width]
    # A deterministic measured-depth pattern makes occupied/free geometry and
    # frame-to-frame overlap while keeping RGB semantically irrelevant to M1.
    depth = np.full((height, width), 2.4, dtype=np.float32)
    depth[:, 22:26] = 1.8 + .02 * index
    depth[12:36, 42:46] = 3.0
    valid = np.ones((height, width), dtype=bool)
    valid[:2] = False
    depth[~valid] = np.nan
    rgb = np.stack(((xx * 3 + index) % 255, (yy * 5) % 255, np.full_like(xx, 80)), axis=-1).astype(np.uint8)
    k = np.array([[58., 0., (width - 1) / 2], [0., 58., (height - 1) / 2], [0., 0., 1.]])
    # Optical +Z maps to world +Y, optical +Y maps to world -Z (Z-up).
    transform = np.array([
        [1., 0., 0., 0.],
        [0., 0., 1., .25 * index],
        [0., -1., 0., 1.2],
        [0., 0., 0., 1.],
    ])
    return Observation(
        key=FrameKey("parity-synthetic", "primary-rgbd", index),
        capture_monotonic_ns=1_000_000_000 + index * 200_000_000,
        clock_domain="rebuild-parity-synthetic-v1", sim_time_s=index * .2,
        rgb=rgb, depth_m=depth, valid_depth=valid, K=k,
        T_world_camera=transform, calibration_id="synthetic-calibration-v1",
        pose_version=index, modality="rgbd",
    )


def _load_recorded_observations(run_dir: Path, config: RebuildRGBDConfig, limit: int | None):
    root = run_dir.expanduser().resolve(strict=True)
    profile = json.loads((root / "run-profile.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "completeness.json").read_text(encoding="utf-8"))
    if (profile.get("source_python_sha256") != EXPECTED_SOURCE_TREE_SHA256
            or profile.get("m23_binary_sha256") != EXPECTED_M23_SHA256
            or profile.get("m4_binary_sha256") != EXPECTED_M4_SHA256):
        raise ValueError("recorded sequence source/native pins differ")
    expected_mapping = {"resolution_m": config.resolution_m,
        "backprojection_stride": config.backprojection_stride,
        "min_depth_m": config.min_depth_m, "max_depth_m": config.max_depth_m,
        "max_range_m": config.max_range_m}
    if profile.get("mapping") != expected_mapping:
        raise ValueError("recorded sequence mapping config differs from oracle config")
    entries = manifest.get("frames")
    if (manifest.get("recording_complete") is not True or not isinstance(entries, list)
            or len(entries) != manifest.get("admitted_frames") or not 2 <= len(entries) <= 8):
        raise ValueError("recording must contain 2..8 complete admitted frames")
    if limit is not None:
        if type(limit) is not int or not 2 <= limit <= len(entries):
            raise ValueError("--recording-frames must select a 2..N frame prefix")
        entries = entries[:limit]
    total = 0
    sequence_hash = hashlib.sha256(b"NeuSymNav:admitted-room-sequence:v1\0")
    observations = []
    from neusymnav.regions.rebuild_rgbd_input import RebuildRGBDInputAdapter
    adapter = RebuildRGBDInputAdapter(config)
    for entry in entries:
        relative = Path(entry["payload_path"])
        payload_path = (root / relative).resolve(strict=True)
        if root not in payload_path.parents or payload_path.is_symlink():
            raise ValueError("recorded frame path escapes the admitted-session root")
        raw = payload_path.read_bytes()
        total += len(raw)
        if (total > MAX_RECORDED_SEQUENCE_BYTES or len(raw) != entry["payload_bytes"]
                or hashlib.sha256(raw).hexdigest() != entry["payload_sha256"]):
            raise ValueError("recorded frame size/checksum invalid or sequence exceeds 256 MiB")
        sequence_hash.update(len(raw).to_bytes(8, "big")); sequence_hash.update(raw)
        wire = json.loads(raw)
        if set(wire) != {"wire_version", "frame", "mapping", "arrays"} or wire["wire_version"] != 1:
            raise ValueError("unsupported recorded Rebuild RGB-D wire schema")
        if wire["mapping"] != {**expected_mapping, "depth_scale_to_m": 1.0}:
            raise ValueError("recorded frame has mismatched mapping parameters")
        frame = wire["frame"]
        if (frame.get("pose_source") != "simulator_ground_truth"
                or frame.get("coordinate_convention") != "canonical_z_up_optical_v1"
                or frame.get("depth_units") != "m" or frame.get("depth_representation") != "axial"):
            raise ValueError("recorded frame source conventions are unsupported")
        arrays = {name: _decode_input_array(wire["arrays"][name], name) for name in
                  ("rgb", "depth_m", "valid_depth", "K", "T_world_camera")}
        source_depth = _decode_input_array(wire["arrays"]["source_depth_m"], "source_depth_m") if "source_depth_m" in wire["arrays"] else arrays["depth_m"]
        source_valid = _decode_input_array(wire["arrays"]["source_valid_depth"], "source_valid_depth") if "source_valid_depth" in wire["arrays"] else arrays["valid_depth"]
        masks = frame.get("source_masks_present", {"no_return": False, "far_plane": False})
        if not isinstance(masks, dict) or set(masks) != {"no_return", "far_plane"}:
            raise ValueError("recorded source mask metadata is invalid")
        no_return = _decode_input_array(wire["arrays"]["no_return_mask"], "no_return_mask") if masks["no_return"] else None
        far_plane = _decode_input_array(wire["arrays"]["far_plane_mask"], "far_plane_mask") if masks["far_plane"] else None
        observation = Observation(
            key=FrameKey(frame["scene_id"], frame["sensor_id"], int(frame["frame_index"])),
            capture_monotonic_ns=int(frame["capture_monotonic_ns"]),
            clock_domain=frame["clock_domain"], sim_time_s=float(frame["timestamp_s"]),
            rgb=arrays["rgb"], depth_m=source_depth, valid_depth=source_valid,
            K=arrays["K"], T_world_camera=arrays["T_world_camera"],
            calibration_id=frame["calibration_id"], pose_version=int(frame["pose_version"]),
            modality="rgbd", no_return=no_return, far_plane=far_plane,
            no_return_range_m=frame.get("no_return_range_m"),
            far_plane_range_m=frame.get("far_plane_range_m"),
        )
        if observation.geometry_hash != frame["geometry_sha256"]:
            raise ValueError("recorded source geometry hash does not reconstruct")
        adapted = adapter.adapt(observation)
        legacy_wire = json.loads(json.dumps(adapted.to_wire()))
        for name in ("source_depth_m", "source_valid_depth", "no_return_mask", "far_plane_mask"):
            legacy_wire["arrays"].pop(name, None)
        for name in ("source_masks_present", "no_return_range_m", "far_plane_range_m"):
            legacy_wire["frame"].pop(name, None)
        canonical_legacy = json.dumps(legacy_wire, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        if adapted.prefix_sha256 != frame["prefix_sha256"] or (adapted.wire_bytes() != raw and canonical_legacy != raw):
            raise ValueError("recorded frame/prefix differs after exact adapter replay")
        observations.append(observation)
    return observations, sequence_hash.hexdigest(), total


def _load_source(package: Path, namespace: str):
    spec = importlib.util.spec_from_file_location(
        namespace, package / "__init__.py", submodule_search_locations=[str(package)])
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pinned Rebuild source package")
    module = importlib.util.module_from_spec(spec)
    sys.modules[namespace] = module
    spec.loader.exec_module(module)
    return namespace


def _direct_source_lane(observations, config):
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    namespace = f"_neusymnav_parity_{EXPECTED_M23_SHA256[:10]}_{EXPECTED_M4_SHA256[:10]}"
    _load_source(SOURCE_ROOT / "src/standalone_sg", namespace)
    mapping_mod = __import__(namespace + ".mapping.native_pipeline", fromlist=["NativeRGBDMappingStage"])
    dude_mod = __import__(namespace + ".regions.dude_client", fromlist=["DuDeWorkerClient"])
    pipeline_mod = __import__(namespace + ".regions.pipeline", fromlist=["RegionUpdateProcessor"])
    stages_mod = __import__(namespace + ".pipeline.stages", fromlist=["DudeM5RegionStage"])
    frames_mod = __import__(namespace + ".contracts.frames", fromlist=["CameraIntrinsics"])
    packet_mod = __import__(namespace + ".pipeline.contracts", fromlist=["FramePacket"])
    mapping = mapping_mod.NativeRGBDMappingStage(
        M23, resolution_m=config.resolution_m, timeout_s=15., default_max_range_m=config.max_range_m)
    regions = None
    dude = None
    results = []
    accepted_regions = []
    accepted_map = None
    m5_revision = 0
    try:
        dude = dude_mod.DuDeWorkerClient(M4, dude_mod.DuDeConfig(
            decomp_threshold_m=1.5, safety_distance_m=.5, timeout_s=30., preprocessing_policy="source"))
        regions = stages_mod.DudeM5RegionStage(dude, pipeline_mod.RegionUpdateProcessor())
        for obs in observations:
            intrinsics = frames_mod.CameraIntrinsics(
                width=obs.depth_m.shape[1], height=obs.depth_m.shape[0],
                fx=float(obs.K[0, 0]), fy=float(obs.K[1, 1]),
                cx=float(obs.K[0, 2]), cy=float(obs.K[1, 2]),
                calibration_id=obs.calibration_id)
            transform = frames_mod.Transform(
                obs.T_world_camera, "world", "camera_optical", obs.sim_time_s, "ground_truth")
            depth = np.asarray(obs.depth_m, dtype=np.float32).copy()
            valid = np.asarray(obs.valid_depth, dtype=bool).copy()
            valid &= np.isfinite(depth) & (depth >= config.min_depth_m) & (depth <= config.max_depth_m)
            depth[~valid] = np.nan
            rgbd = frames_mod.RGBDFrame(
                depth, intrinsics, transform, obs.sim_time_s, rgb=obs.rgb,
                valid_mask=valid, frame_id=f"{obs.key.sensor_id}:{obs.key.frame_index}")
            packet = packet_mod.FramePacket(
                scene_id=obs.key.episode_id, sequence_id=obs.key.episode_id,
                frame_id=f"{obs.key.sensor_id}:{obs.key.frame_index}",
                frame_index=obs.key.frame_index, timestamp_s=obs.sim_time_s,
                input_mode="rgbd", base_pose_W=None, rgbd=rgbd,
                source_metadata={
                    "depth_units": "m", "depth_representation": "axial", "depth_scale_to_m": 1.0,
                    "backprojection_stride": config.backprojection_stride,
                    "min_depth_m": config.min_depth_m, "max_depth_m": config.max_depth_m,
                    "max_range_m": config.max_range_m,
                    "source_frame_key": {"episode_id": obs.key.episode_id,
                        "sensor_id": obs.key.sensor_id, "frame_index": obs.key.frame_index},
                    "capture_monotonic_ns": obs.capture_monotonic_ns,
                    "clock_domain": obs.clock_domain, "calibration_id": obs.calibration_id,
                    "pose_version": obs.pose_version, "geometry_sha256": obs.geometry_hash,
                    "pose_source": "simulator_ground_truth",
                    "coordinate_convention": "canonical_z_up_optical_v1",
                    "semantic_gt_in_mapping": False,
                })
            grid = mapping.build_grid(packet)
            record = mapping.records.pop()
            outcome = regions.update(grid, timestamp_s=obs.sim_time_s)
            if outcome.accepted:
                accepted_regions = _region_payload(outcome.current_regions)
                accepted_map = grid
                m5_revision += 1
            results.append({"grid": grid, "record": record,
                "regions": list(accepted_regions), "accepted_map": accepted_map,
                "m5_revision": m5_revision, "stale": not outcome.accepted})
        return results
    finally:
        try:
            if regions is not None:regions.close()
            elif dude is not None:dude.close()
        finally:
            mapping.close()


def _compare_map(actual, expected, label):
    if actual is None or expected is None:
        if actual is not expected:
            raise AssertionError(f"{label}: map availability differs")
        return
    states = np.where(expected.values < 0, -1, np.where(expected.values == 0, 0, 100)).astype(np.int8)
    if (actual.revision != expected.revision or actual.origin_xy != tuple(expected.origin_xy)
            or actual.resolution_m != expected.resolution_m or not np.array_equal(actual.states, states)):
        raise AssertionError(f"{label}: M3 revision/domain/origin/resolution/states differ")
    for name, left, left_valid, right in (
        ("floor", actual.z_floor_m, actual.floor_valid, expected.z_floor),
        ("ceiling", actual.z_ceiling_m, actual.ceiling_valid, expected.z_ceiling),
    ):
        right_valid = np.isfinite(right) & (states != -1)
        if not np.array_equal(left_valid, right_valid):
            raise AssertionError(f"{label}: M3 {name} validity mask differs")
        if not np.allclose(left[left_valid], right[right_valid], rtol=0., atol=1e-7):
            raise AssertionError(f"{label}: M3 {name} heights differ")


def _compare_regions(actual, expected, label):
    if actual is None:
        if expected:
            raise AssertionError(f"{label}: M5 regions missing in adapter lane")
        return
    found = {}
    for region_id, region in actual.regions.items():
        found[region_id.rsplit(":", 1)[-1]] = region
    wanted = {str(item["persistent_id"]): item for item in expected}
    if set(found) != set(wanted):
        raise AssertionError(f"{label}: M5 persistent region IDs differ")
    for region_id, region in found.items():
        polygon = np.asarray(wanted[region_id]["polygon"], dtype=np.float64)
        if not np.array_equal(region.polygon, polygon):
            raise AssertionError(f"{label}: M5 polygon differs for persistent ID {region_id}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--recording", type=Path,
        help="room-pipeline/session directory containing a complete admitted input sequence")
    parser.add_argument("--recording-frames", type=int,
        help="compare this many frames from the recorded admitted prefix (2..8)")
    args = parser.parse_args()
    if args.recording is None and (args.recording_frames is not None or not 2 <= args.frames <= 8):
        parser.error("--frames must be between 2 and 8 for this bounded synthetic oracle")
    if _sha256(M23) != EXPECTED_M23_SHA256 or _sha256(M4) != EXPECTED_M4_SHA256:
        raise SystemExit("pinned Rebuild executable hash mismatch")
    if _source_tree_sha256(SOURCE_ROOT) != EXPECTED_SOURCE_TREE_SHA256:
        raise SystemExit("pinned Rebuild Python source hash mismatch")
    args.out.mkdir(parents=True, exist_ok=False)
    config = RebuildRGBDConfig(resolution_m=.05, backprojection_stride=1,
        min_depth_m=.1, max_depth_m=10., max_range_m=5.)
    if args.recording is None:
        observations = [_observation(index) for index in range(args.frames)]
        sequence_sha256 = None
        recorded_bytes = None
        classification = "synthetic_native_source_oracle"
        episode_id, floor_id = "parity-synthetic", "floor-0"
    else:
        observations, sequence_sha256, recorded_bytes = _load_recorded_observations(
            args.recording, config, args.recording_frames)
        classification = "recorded_admitted_native_source_oracle"
        recorded_profile = json.loads((args.recording / "run-profile.json").read_text(encoding="utf-8"))
        episode_id, floor_id = recorded_profile["episode_id"], recorded_profile["floor_id"]
    session = RebuildRoomSession(source_root=SOURCE_ROOT, m23_binary=M23, m4_binary=M4,
        episode_id=episode_id, floor_id=floor_id, config=config,
        run_dir=args.out / "adapter-session")
    adapter_results = []
    try:
        if args.recording is not None:
            processed = replay_recording(args.recording, session,
                max_frames=args.recording_frames)
            if processed != len(observations) or not session.wait_idle(90.):
                raise RuntimeError("adapter lane failed exact recorded-session replay")
            # Replay processing is ordered and drains before return; the final
            # source result is compared below, while the report binds every
            # intermediate M3/M5 checkpoint from the recording manifest.
            adapter_results.append(session.snapshot())
        else:
            for obs in observations:
                admission = session.submit(obs)
                if not admission.accepted or not session.wait_idle(90.):
                    raise RuntimeError(f"adapter lane failed admission/processing: {admission}")
                adapter_results.append(session.snapshot())
        close_result = session.close(timeout_s=30.)
        if not close_result.get("clean_shutdown"):
            raise RuntimeError(f"adapter lane did not shut down cleanly: {close_result}")
    except BaseException:
        session.close(timeout_s=3.)
        raise
    direct_results = _direct_source_lane(observations, config)
    if args.recording is not None:
        adapter = adapter_results[-1]
        direct = direct_results[-1]
        _compare_map(adapter.latest_map, direct["grid"], "recorded final latest")
        _compare_map(adapter.accepted_map, direct["accepted_map"], "recorded final accepted")
        _compare_regions(adapter.regions, direct["regions"], "recorded final")
        frame_reports = [{"frame_index": adapter.latest_map.source.frame_index,
            "m3_revision": adapter.latest_map.revision,
            "accepted_m3_revision": adapter.accepted_map_revision,
            "m5_revision": adapter.m5_revision, "regions_stale": adapter.regions_stale,
            "map_shape": list(adapter.latest_map.states.shape),
            "occupied_cells": int(np.count_nonzero(adapter.latest_map.states == 100)),
            "free_cells": int(np.count_nonzero(adapter.latest_map.states == 0)),
            "unknown_cells": int(np.count_nonzero(adapter.latest_map.states == -1)),
            "raw_m5_regions": 0 if adapter.regions is None else len(adapter.regions.regions)}]
    else:
        if len(adapter_results) != len(direct_results):
            raise AssertionError("direct source result count differs from admitted frame count")
        frame_reports = []
        for index, (adapter, direct) in enumerate(zip(adapter_results, direct_results)):
            _compare_map(adapter.latest_map, direct["grid"], f"frame {index} latest")
            direct_accepted_grid = direct["accepted_map"]
            if adapter.accepted_map is None:
                if direct_accepted_grid is not None:
                    raise AssertionError(f"frame {index}: accepted M3 pair availability differs")
            else:
                _compare_map(adapter.accepted_map, direct_accepted_grid, f"frame {index} accepted")
            _compare_regions(adapter.regions, direct["regions"], f"frame {index}")
            frame_reports.append({"frame_index": adapter.latest_map.source.frame_index,
                "m3_revision": adapter.latest_map.revision,
                "accepted_m3_revision": adapter.accepted_map_revision,
                "m5_revision": adapter.m5_revision, "regions_stale": adapter.regions_stale,
                "map_shape": list(adapter.latest_map.states.shape),
                "occupied_cells": int(np.count_nonzero(adapter.latest_map.states == 100)),
                "free_cells": int(np.count_nonzero(adapter.latest_map.states == 0)),
                "unknown_cells": int(np.count_nonzero(adapter.latest_map.states == -1)),
                "raw_m5_regions": 0 if adapter.regions is None else len(adapter.regions.regions)})
    report = {
        "schema_version": 1, "result": "parity_pass", "classification": classification,
        "source_root": str(SOURCE_ROOT), "source_python_sha256": EXPECTED_SOURCE_TREE_SHA256,
        "m23_sha256": EXPECTED_M23_SHA256, "m4_sha256": EXPECTED_M4_SHA256,
        "config": {"resolution_m": config.resolution_m, "stride": config.backprojection_stride,
            "min_depth_m": config.min_depth_m, "max_depth_m": config.max_depth_m,
            "max_range_m": config.max_range_m, "m4_decomp_threshold_m": 1.5,
            "m4_safety_distance_m": .5},
        "frames": frame_reports, "admitted_frame_count": len(observations),
        "recorded_sequence_sha256": sequence_sha256, "recorded_bytes": recorded_bytes,
        "comparison": {"m3_states": "exact", "m3_origin_resolution_revision": "exact",
            "m3_height_masks": "exact", "m3_height_values_atol": 1e-7,
            "m5_persistent_ids_and_polygons": "exact"},
        "limits": (["recorded sequence covers only frames admitted by the bounded room lane",
            "does not establish historical 3DSG caller parameter parity",
            "does not measure room quality", "does not validate control under load"]
            if args.recording is not None else ["synthetic analytic RGB-D only",
            "does not establish live caller parameter parity", "does not measure room quality",
            "does not validate Habitat runtime or control under load"]),
        "adapter_session": close_result,
    }
    (args.out / "parity-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
