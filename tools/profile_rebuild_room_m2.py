#!/usr/bin/env python3
"""Profile a few raw RGB-D updates through the pinned Rebuild room worker."""
from __future__ import annotations

import argparse
import json
import pstats
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def _even_samples(frames, count):
    if not frames:
        return []
    if count <= 1:
        return [frames[0]]
    indices = sorted({round(i * (len(frames) - 1) / (count - 1)) for i in range(count)})
    return [frames[index] for index in indices]


def _stats(profile_path, limit=60):
    stats = pstats.Stats(str(profile_path))
    rows = []
    for (filename, line, function), (primitive, calls, own_s, cumulative_s, _callers) in stats.stats.items():
        rows.append({"file": filename, "line": line, "function": function,
                     "primitive_calls": primitive, "calls": calls,
                     "own_seconds": own_s, "cumulative_seconds": cumulative_s})
    return {
        "top_cumulative": sorted(rows, key=lambda row: row["cumulative_seconds"], reverse=True)[:limit],
        "top_own_time": sorted(rows, key=lambda row: row["own_seconds"], reverse=True)[:limit],
        "function_count": len(rows),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=3)
    parser.add_argument("--cprofile", action="store_true",
                        help="collect call-level profile; substantially slows the worker")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.frames <= 8:
        raise ValueError("--frames must be in [1, 8]")

    from neusymnav.recording.replay import ReplayReader
    from neusymnav.runtime.configuration import load_config
    from neusymnav.regions.rebuild_rgbd_input import RebuildRGBDConfig
    import neusymnav.regions.rebuild_room_session as session_module
    from neusymnav.regions.rebuild_room_session import RebuildRoomSession
    from tools.compare_rebuild_room_sampling import stage_timing_summary

    config_data = load_config(args.config).data
    episode = config_data["episode"]
    room = config_data["workers"]["room_pipeline"]
    raw_frames = [frame for frame in ReplayReader(args.recording).frames()
                  if frame.modality == "rgbd" and frame.key.sensor_id == episode["primary_sensor_id"]]
    frames = _even_samples(raw_frames, args.frames)
    if not frames:
        raise ValueError("raw recording has no primary RGB-D frames")
    args.out.mkdir(parents=True, exist_ok=False)
    profile_path = args.out / "worker-update.prof" if args.cprofile else None
    timings_path = args.out / "integrate-phase-timings.json"
    profile_worker = PROJECT_ROOT / "tools" / "rebuild_room_profile_worker.py"
    original_worker_type = session_module._WorkerProcess

    def profiled_worker(worker_config, *, timeout_s, python=None, command=None):
        worker_command = [
            sys.executable, str(profile_worker),
            "--timings-output", str(timings_path),
            "--config-json", json.dumps(worker_config, sort_keys=True,
                                           separators=(",", ":"), allow_nan=False),
        ]
        if profile_path is not None:
            worker_command.extend(("--profile-output", str(profile_path)))
        return original_worker_type(worker_config, timeout_s=timeout_s, command=tuple(worker_command))

    session_module._WorkerProcess = profiled_worker
    profile = RebuildRGBDConfig(**{key: room[key] for key in (
        "resolution_m", "backprojection_stride", "min_depth_m", "max_depth_m", "max_range_m")
        if key in room})
    session = RebuildRoomSession(
        source_root=room["source_root"], m23_binary=room["m23_binary"]["path"],
        m4_binary=room["m4_binary"]["path"], episode_id=episode["id"],
        floor_id=episode["floor_id"], config=profile,
        ipc_timeout_s=room.get("ipc_timeout_s", 60.),
        m23_timeout_s=room.get("m23_timeout_s", 15.),
        m4_timeout_s=room.get("m4_timeout_s", 30.), run_dir=args.out / "session")
    session_module._WorkerProcess = original_worker_type
    try:
        for frame in frames:
            admission = session.submit(frame)
            if not admission.accepted:
                raise RuntimeError(f"profile frame was rejected: {admission.reason}")
            if not session.wait_idle(session.ipc_timeout_s):
                raise TimeoutError("profile update did not drain")
            if session.health.get("failed"):
                raise RuntimeError(session.health.get("failure_reason"))
        publication = session.snapshot()
        if publication is None:
            raise RuntimeError("profile produced no room publication")
    finally:
        close_result = session.close()

    journal = [json.loads(line) for line in
               (args.out / "session" / "admission-journal.jsonl").read_text().splitlines()]
    report = {
        "schema_version": 1,
        "recording_manifest_sha256": __import__("hashlib").sha256(
            (args.recording / "manifest.json").read_bytes()).hexdigest(),
        "sampled_primary_frame_indices": [int(frame.key.frame_index) for frame in frames],
        "backprojection_stride": profile.backprojection_stride,
        "session_close": close_result,
        "worker_update_profile": None if profile_path is None else _stats(profile_path),
        "profiling_overhead": "cProfile enabled; wall-clock durations in this run are diagnostic-only and must not be compared with unprofiled timings" if profile_path is not None else "cProfile disabled; only lightweight method-boundary wall timers enabled",
        "integrate_phase_timings": json.loads(timings_path.read_text()),
        "per_update_stage_summary": stage_timing_summary(journal),
        "m3_revision": publication.latest_map.revision,
        "m5_regions": 0 if publication.regions is None else len(publication.regions.regions),
        "m5_stale": publication.regions_stale,
        "acceptance_checker": "not_run; profile run is diagnostic only",
    }
    (args.out / "profile-summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not close_result["clean_shutdown"] or not close_result["runtime_complete"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
