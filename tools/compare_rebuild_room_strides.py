#!/usr/bin/env python3
"""Compare full-sequence Rebuild M1-M5 replay at backprojection strides 1/2/4."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from tools.compare_rebuild_room_sampling import compare_m3, compare_m5, stage_timing_summary


def _run_stride(frames, room, episode, floor, stride, output):
    from neusymnav.regions.rebuild_rgbd_input import RebuildRGBDConfig
    from neusymnav.regions.rebuild_room_session import RebuildRoomSession

    mapping = RebuildRGBDConfig(**{
        **{key: room[key] for key in (
            "resolution_m", "backprojection_stride", "min_depth_m", "max_depth_m", "max_range_m")
            if key in room},
        "backprojection_stride": stride,
    })
    session = RebuildRoomSession(
        source_root=room["source_root"], m23_binary=room["m23_binary"]["path"],
        m4_binary=room["m4_binary"]["path"], episode_id=episode, floor_id=floor,
        config=mapping, ipc_timeout_s=room.get("ipc_timeout_s", 60.),
        m23_timeout_s=room.get("m23_timeout_s", 15.),
        m4_timeout_s=room.get("m4_timeout_s", 30.), run_dir=output / "session")
    started = time.monotonic()
    try:
        for frame in frames:
            admission = session.submit(frame)
            if not admission.accepted:
                if not session.wait_idle(session.ipc_timeout_s):
                    raise TimeoutError("room session failed to drain before retry")
                admission = session.submit(frame)
            if not admission.accepted:
                raise RuntimeError(f"stride {stride} rejected frame {frame.key.frame_index}: {admission.reason}")
            if not session.wait_idle(session.ipc_timeout_s):
                raise TimeoutError(f"stride {stride} update timed out")
            if session.health.get("failed"):
                raise RuntimeError(str(session.health.get("failure_reason")))
        publication = session.snapshot()
        if publication is None:
            raise RuntimeError(f"stride {stride} produced no M3 publication")
    finally:
        close_result = session.close()
    elapsed = time.monotonic() - started
    if not close_result["clean_shutdown"] or not close_result["runtime_complete"]:
        raise RuntimeError(f"stride {stride} session integrity failed: {close_result}")
    journal = [json.loads(line) for line in
               (output / "session" / "admission-journal.jsonl").read_text().splitlines()]
    np.savez_compressed(output / "m3.npz", states=publication.latest_map.states,
        origin_xy=np.asarray(publication.latest_map.origin_xy),
        resolution_m=np.asarray(publication.latest_map.resolution_m))
    return publication, dict(
        backprojection_stride=stride, elapsed_wall_s=elapsed,
        processed_updates=close_result["processed_frames"],
        m3_revision=publication.latest_map.revision,
        accepted_m3_revision=publication.accepted_map_revision,
        m5_revision=publication.m5_revision,
        m5_region_count=0 if publication.regions is None else len(publication.regions.regions),
        m5_regions_stale=publication.regions_stale,
        m3_modes=[event.get("m3_projection_mode") for event in journal if event.get("reason")=="processed"],
        timing=stage_timing_summary(journal),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True,
                        help="complete raw sensor recording; all primary RGB-D frames are replayed")
    parser.add_argument("--config", type=Path, required=True,
                        help="checked local profile with pinned Rebuild binaries/source")
    parser.add_argument("--strides", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.strides or any(stride not in (1, 2, 4) for stride in args.strides):
        raise ValueError("only the predeclared local comparison strides 1, 2, and 4 are allowed")
    if len(set(args.strides)) != len(args.strides):
        raise ValueError("stride values must be unique")

    from neusymnav.recording.replay import ReplayReader
    from neusymnav.runtime.configuration import load_config

    config = load_config(args.config).data
    episode = config["episode"]
    room = config["workers"]["room_pipeline"]
    reader = ReplayReader(args.recording)
    frames = [frame for frame in reader.frames()
              if frame.modality == "rgbd" and frame.key.sensor_id == episode["primary_sensor_id"]]
    if not frames:
        raise ValueError("raw recording has no primary RGB-D frames")
    args.out.mkdir(parents=True, exist_ok=False)

    publications = {}
    variants = {}
    for stride in args.strides:
        variant_root = args.out / f"stride-{stride}"
        variant_root.mkdir()
        publications[stride], variants[stride] = _run_stride(
            frames, room, episode["id"], episode["floor_id"], stride, variant_root)

    baseline_stride = 1 if 1 in publications else args.strides[0]
    baseline = publications[baseline_stride]
    comparisons = {}
    for stride, publication in publications.items():
        if stride == baseline_stride:
            continue
        comparisons[str(stride)] = dict(
            baseline_stride=baseline_stride,
            m3=compare_m3(baseline.latest_map, publication.latest_map),
            m5=compare_m5(baseline, publication),
        )

    report = dict(
        schema_version=1,
        recording_manifest_sha256=hashlib.sha256((args.recording / "manifest.json").read_bytes()).hexdigest(),
        recording_certificate=reader.certificate,
        episode_id=episode["id"], primary_sensor_id=episode["primary_sensor_id"],
        raw_primary_rgbd_frames=len(frames),
        source_mapping_profile={key: room.get(key) for key in (
            "resolution_m", "min_depth_m", "max_depth_m", "max_range_m")},
        variants=variants, baseline_stride=baseline_stride,
        quality_comparisons=comparisons,
        acceptance_checker="not_run; this is a local mapping parameter study",
    )
    (args.out / "stride-comparison.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
