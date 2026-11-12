#!/usr/bin/env python3
"""Measure one NavMap local-window/retention candidate on recorded source frames.

This is an offline historical-source replay. It never creates a live control
source or certifies motion freshness. One candidate is run per invocation; an
optional legacy radius-2 mapper supplies same-source context comparisons.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
import time

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from neusymnav.contracts import GridState
from neusymnav.mapping.occupancy import NavMapper, RobotGeometry
from neusymnav.mapping._raycast_kernel import warmup_raycast_kernel
from neusymnav.recording.replay import ReplayReader
from neusymnav.runtime.configuration import file_sha256, load_config


def mapping_observation(source, replay_domain):
    """Private mapping clock; preserve numeric source intervals and original DTO."""
    if not isinstance(replay_domain,str) or not replay_domain.startswith('replay:'):
        raise ValueError('offline mapping requires a private replay clock domain')
    return replace(source,clock_domain=replay_domain)


def nearest_rank_percentile(values, percentile: float) -> float | None:
    """Return the one-based nearest-rank percentile, or None for no samples."""
    if not math.isfinite(float(percentile)) or not 0 <= percentile <= 100:
        raise ValueError("percentile must be finite and in [0, 100]")
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) for value in ordered):
        raise ValueError("percentile values must be finite")
    rank = max(1, math.ceil((float(percentile) / 100.0) * len(ordered)))
    return ordered[rank - 1]


def _aligned_overlap(candidate, reference):
    """Return paired slices for common world cells in two aligned rasters."""
    if not math.isclose(float(candidate.resolution_m), float(reference.resolution_m),
                        rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("snapshot comparison requires identical grid resolution")
    resolution = float(candidate.resolution_m)
    col_delta_f = (float(candidate.origin_xy[0]) - float(reference.origin_xy[0])) / resolution
    row_delta_f = (float(candidate.origin_xy[1]) - float(reference.origin_xy[1])) / resolution
    col_delta, row_delta = round(col_delta_f), round(row_delta_f)
    if (not math.isclose(col_delta_f, col_delta, rel_tol=0.0, abs_tol=1e-7)
            or not math.isclose(row_delta_f, row_delta, rel_tol=0.0, abs_tol=1e-7)):
        raise ValueError("snapshot origins must be grid-aligned for common-cell comparison")

    candidate_rows, candidate_cols = candidate.states.shape
    reference_rows, reference_cols = reference.states.shape
    candidate_row0 = max(0, -row_delta)
    reference_row0 = max(0, row_delta)
    candidate_col0 = max(0, -col_delta)
    reference_col0 = max(0, col_delta)
    rows = max(0, min(candidate_rows - candidate_row0,
                      reference_rows - reference_row0))
    cols = max(0, min(candidate_cols - candidate_col0,
                      reference_cols - reference_col0))
    return (
        np.s_[candidate_row0:candidate_row0 + rows,
              candidate_col0:candidate_col0 + cols],
        np.s_[reference_row0:reference_row0 + rows,
              reference_col0:reference_col0 + cols],
    )


def compare_snapshots(candidate, reference) -> dict:
    """Compare states, floor support, and measured clearance over common cells."""
    candidate_slice, reference_slice = _aligned_overlap(candidate, reference)
    candidate_states = candidate.states[candidate_slice]
    reference_states = reference.states[reference_slice]
    candidate_floor = candidate.floor_support[candidate_slice]
    reference_floor = reference.floor_support[reference_slice]
    candidate_clearance = candidate.clearance[candidate_slice]
    reference_clearance = reference.clearance[reference_slice]
    common = int(candidate_states.size)
    state_equal = int(np.count_nonzero(candidate_states == reference_states))
    floor_equal = int(np.count_nonzero(candidate_floor == reference_floor))
    clearance_equal = int(np.count_nonzero(np.isclose(
        candidate_clearance, reference_clearance, rtol=0.0, atol=1e-6)))
    return dict(
        common_cells=common,
        state_equal_cells=state_equal,
        state_agreement=None if common == 0 else state_equal / common,
        candidate_free_cells=int(np.count_nonzero(candidate_states == GridState.FREE)),
        reference_free_cells=int(np.count_nonzero(reference_states == GridState.FREE)),
        candidate_occupied_cells=int(np.count_nonzero(candidate_states == GridState.OCCUPIED)),
        reference_occupied_cells=int(np.count_nonzero(reference_states == GridState.OCCUPIED)),
        candidate_unknown_cells=int(np.count_nonzero(candidate_states == GridState.UNKNOWN)),
        reference_unknown_cells=int(np.count_nonzero(reference_states == GridState.UNKNOWN)),
        floor_equal_cells=floor_equal,
        floor_agreement=None if common == 0 else floor_equal / common,
        clearance_equal_cells=clearance_equal,
        clearance_agreement=None if common == 0 else clearance_equal / common,
    )


def footprint_diagnostic(nav, robot_xy, robot) -> dict:
    """Apply the same capsule-cell and FREE/floor/clearance predicates as guard."""
    from neusymnav.mapping.occupancy import capsule_cells

    radius = float(robot.radius_m) + float(robot.margin_m)
    cells = tuple(capsule_cells(nav.origin_xy, nav.resolution_m,
                                robot_xy, robot_xy, radius))
    if not cells:
        return dict(robot_footprint_free=False, footprint_cells_total=0,
                    footprint_inside_map=False, footprint_known_free_cells=0,
                    footprint_unknown_cells=0, footprint_occupied_cells=0,
                    footprint_floor_unsupported_cells=0,
                    footprint_clearance_insufficient_cells=0,
                    footprint_min_clearance_m=None)
    indices = np.asarray(cells, dtype=np.intp)
    rows, cols = indices.T
    inside = ((rows >= 0) & (rows < nav.states.shape[0])
              & (cols >= 0) & (cols < nav.states.shape[1]))
    inside_count = int(np.count_nonzero(inside))
    outside_count = len(cells) - inside_count
    known_free = occupied = unknown = unsupported = insufficient = 0
    minimum_clearance = None
    if inside_count:
        r, c = rows[inside], cols[inside]
        states = nav.states[r, c]
        floor = nav.floor_support[r, c]
        clearance = nav.clearance[r, c]
        unknown = int(np.count_nonzero(states == GridState.UNKNOWN)) + outside_count
        occupied = int(np.count_nonzero(states == GridState.OCCUPIED))
        unsupported = int(np.count_nonzero(~floor)) + outside_count
        clearance_as_scalar_precision = clearance.astype(
            np.result_type(clearance.dtype, type(float(robot.height_m))), copy=False)
        sufficiently_clear = clearance_as_scalar_precision >= float(robot.height_m)
        insufficient = int(np.count_nonzero(~sufficiently_clear)) + outside_count
        known = ((states == GridState.FREE) & floor & sufficiently_clear)
        known_free = int(np.count_nonzero(known))
        minimum_clearance = float(np.min(clearance))
    else:
        unknown = outside_count
        unsupported = insufficient = outside_count
    return dict(
        robot_footprint_free=(inside_count == len(cells) and known_free == len(cells)),
        footprint_cells_total=len(cells),
        footprint_inside_map=(inside_count == len(cells)),
        footprint_known_free_cells=known_free,
        footprint_unknown_cells=unknown,
        footprint_occupied_cells=occupied,
        footprint_floor_unsupported_cells=unsupported,
        footprint_clearance_insufficient_cells=insufficient,
        footprint_min_clearance_m=minimum_clearance,
    )


def _state_counts(nav) -> dict:
    states = nav.states
    counts = {
        "free": int(np.count_nonzero(states == GridState.FREE)),
        "occupied": int(np.count_nonzero(states == GridState.OCCUPIED)),
        "unknown": int(np.count_nonzero(states == GridState.UNKNOWN)),
    }
    counts["total"] = int(states.size)
    counts["unclassified"] = counts["total"] - counts["free"] - counts["occupied"] - counts["unknown"]
    if counts["unclassified"]:
        raise ValueError("NavSnapshot contains an unrecognized occupancy state")
    return counts


def _timing_ms(spans) -> dict[str, float]:
    timings = {}
    for name, span in spans.items():
        if (not isinstance(span, (tuple, list)) or len(span) != 2
                or type(span[0]) is not int or type(span[1]) is not int
                or span[1] < span[0]):
            raise ValueError(f"invalid timing span for {name}")
        timings[name] = (span[1] - span[0]) / 1_000_000.0
    return timings


def _distribution(values) -> dict:
    if not values:
        return dict(count=0, mean=None, p50=None, p95=None, p99=None, max=None)
    numbers = [float(value) for value in values]
    return dict(count=len(numbers), mean=statistics.fmean(numbers),
                p50=nearest_rank_percentile(numbers, 50),
                p95=nearest_rank_percentile(numbers, 95),
                p99=nearest_rank_percentile(numbers, 99), max=max(numbers))


def _stage_summary(frames, stage_names):
    buckets = {name: [] for name in ("early", "mid", "late")}
    for frame in frames:
        bucket = frame["time_bucket"]
        for stage, value in frame["stage_ms"].items():
            buckets[bucket].append((stage, value))
    result = {}
    for bucket in ("early", "mid", "late"):
        selected = defaultdict(list)
        for stage, value in buckets[bucket]:
            selected[stage].append(value)
        result[bucket] = {stage: _distribution(selected[stage]) for stage in stage_names}
    return result


def _key_fields(record: dict) -> dict:
    key = record.get("source_key", {})
    fields = key.get("payload", {}).get("fields")
    if fields is None:
        fields = key.get("fields", {})
    return fields if isinstance(fields, dict) else {}


def _observation_record_index(manifest: dict):
    records = {}
    for record in manifest["records"]:
        fields = _key_fields(record)
        key = (fields.get("sensor_id"), fields.get("frame_index"))
        if None not in key:
            records[key] = record
    return records


def _write_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def _mapper(config_data, *, radius_m: float, retention_s: float):
    nav_config = config_data.get("navigation", {})
    floor = config_data["floor"]
    robot = RobotGeometry(**nav_config.get("robot", dict(
        geometry_id="cylinder-v1", radius_m=0.2, height_m=1.5)))
    options = dict(nav_config.get("mapper", {}))
    backend = options.pop("raycast_backend", "cpu")
    if backend != "cpu":
        raise ValueError("offline harness requires the profile's explicit CPU raycast backend")
    # The comparison measures resident mapper state, not archive round trips.
    options.pop("tile_archive_dir", None)
    options.pop("local_retention_s", None)
    options["snapshot_radius_m"] = float(radius_m)
    options["tile_archive_dir"] = None
    if retention_s > 0:
        options["local_retention_s"] = float(retention_s)
    mapper = NavMapper(
        robot=robot, floor_z_m=floor["z_m"],
        floor_datum_source=floor["datum_source"],
        calibration_hash=floor["calibration_sha256"], **options)
    return mapper, robot


def _retention_diagnostics(mapper) -> dict:
    diagnostics = getattr(mapper, "retention_diagnostics", None)
    if not isinstance(diagnostics, dict):
        raise RuntimeError("NavMapper.retention_diagnostics property is required for measurement")
    required = {"resident_tile_count", "resident_bytes", "resident_timestamp_bytes"}
    missing = required - diagnostics.keys()
    if missing:
        raise RuntimeError("retention diagnostics are missing required memory fields: "
                           + ", ".join(sorted(missing)))
    return diagnostics


def _time_bucket(timestamp_ns, interval_start_ns, interval_end_ns) -> str:
    if interval_end_ns <= interval_start_ns:
        return "early"
    fraction = (timestamp_ns - interval_start_ns) / (interval_end_ns - interval_start_ns)
    if fraction < 1.0 / 3.0:
        return "early"
    if fraction < 2.0 / 3.0:
        return "mid"
    return "late"


def _metrics_path_writer(path):
    return path.open("w", encoding="utf-8", buffering=1)


def run(args) -> dict:
    config = load_config(args.config)
    config_data = config.data
    nav_sensor = config_data.get("sensor_config", {}).get("navigation", {}).get("sensor_id")
    if not isinstance(nav_sensor, str) or not nav_sensor:
        raise ValueError("profile must pin sensor_config.navigation.sensor_id")
    if args.radius <= 0 or not math.isfinite(args.radius):
        raise ValueError("--radius must be finite and positive")
    if args.retention_seconds < 0 or not math.isfinite(args.retention_seconds):
        raise ValueError("--retention-seconds must be finite and nonnegative")
    if type(args.every) is not int or args.every < 1:
        raise ValueError("--every must be a positive integer")
    if args.max_frames is not None and (type(args.max_frames) is not int or args.max_frames < 1):
        raise ValueError("--max-frames must be a positive integer")

    recording = Path(args.recording).resolve()
    manifest_path = recording / "manifest.json"
    manifest_sha = file_sha256(manifest_path)
    reader = ReplayReader(recording)
    manifest = reader.manifest
    source_records = _observation_record_index(manifest)
    nav_manifest_records = []
    for record in manifest["records"]:
        fields = _key_fields(record)
        if fields.get("sensor_id") == nav_sensor:
            nav_manifest_records.append(record)
    if not nav_manifest_records:
        raise ValueError(f"recording has no frames for navigation sensor {nav_sensor!r}")
    full_start_ns = min(int(record["source_capture_monotonic_ns"]) for record in nav_manifest_records)
    full_end_ns = max(int(record["source_capture_monotonic_ns"]) for record in nav_manifest_records)
    source_domains = {record.get("source_clock_domain") for record in nav_manifest_records}
    if len(source_domains) != 1:
        raise ValueError("navigation source changes clock domain in the recording")
    full_domain = next(iter(source_domains))
    input_navigation_count = len(nav_manifest_records)

    code_files = (
        Path(__file__), PROJECT_ROOT / "src/neusymnav/mapping/occupancy.py",
        PROJECT_ROOT / "src/neusymnav/mapping/_occupancy_core.py",
        PROJECT_ROOT / "src/neusymnav/mapping/_raycast_kernel.py",
        PROJECT_ROOT / "src/neusymnav/mapping/_log_odds_kernel.py",
        PROJECT_ROOT / "src/neusymnav/mapping/_retention_kernel.py",
        PROJECT_ROOT / "src/neusymnav/mapping/rolling.py",
        PROJECT_ROOT / "src/neusymnav/recording/replay.py",
        PROJECT_ROOT / "src/neusymnav/runtime/configuration.py",
    )
    source_hashes = {str(path.relative_to(PROJECT_ROOT)): file_sha256(path)
                     for path in code_files if path.is_file()}
    mapping_domain='replay:navmap-window:'+manifest_sha
    source_info = dict(
        kind="offline_recorded_source_replay",
        control_eligible=False,
        mapping_clock_domain=mapping_domain,
        source_domain=full_domain,
        sensor_id=nav_sensor,
        modality="depth_only",
        episode_id=manifest["episode_id"],
        input_navigation_frame_count=input_navigation_count,
        source_start_capture_monotonic_ns=full_start_ns,
        source_end_capture_monotonic_ns=full_end_ns,
        source_duration_s=(full_end_ns - full_start_ns) / 1e9,
        recording_manifest_sha256=manifest_sha,
        config_sha256=file_sha256(args.config),
        source_code_sha256=source_hashes,
    )

    progress = dict(frames_seen=0, candidate_frames=0, baseline_frames=0,
                    last_source_key=None, last_source_capture_monotonic_ns=None)
    candidate = baseline = None
    candidate_robot = baseline_robot = None
    frames = []
    retention_records = []
    baseline_update_times = []
    stage_names = set(["candidate_update_wall"])
    candidate_update_times = []
    last_diagnostics = None
    errors = []
    warmup_started = time.monotonic_ns()
    numba_warmed = warmup_raycast_kernel()
    warmup_duration_ms = (time.monotonic_ns() - warmup_started) / 1_000_000.0
    run_started = time.monotonic_ns()
    try:
        candidate, candidate_robot = _mapper(
            config_data, radius_m=args.radius, retention_s=args.retention_seconds)
        if args.compare_baseline:
            baseline, baseline_robot = _mapper(config_data, radius_m=2.0, retention_s=0.0)
            if (candidate_robot.geometry_id != baseline_robot.geometry_id
                    or candidate_robot.height_m != baseline_robot.height_m
                    or candidate_robot.radius_m != baseline_robot.radius_m
                    or candidate_robot.margin_m != baseline_robot.margin_m):
                raise ValueError("candidate and baseline robot geometry must match")

        frame_file = _metrics_path_writer(args.output / "frames.jsonl")
        seen_nav = 0
        last_capture = None
        previous_selected_capture = None
        source_intervals_s = []
        selected_intervals_s = []
        last_domain = None
        try:
            for observation in reader.source_frames():
                progress["frames_seen"] += 1
                if observation.key.sensor_id != nav_sensor:
                    continue
                if observation.modality != "depth_only":
                    raise ValueError("navigation sensor source must be depth_only")
                if last_domain is not None and observation.clock_domain != last_domain:
                    raise ValueError("navigation source clock domain changed during replay")
                if last_capture is not None and observation.capture_monotonic_ns < last_capture:
                    raise ValueError("navigation source capture timestamp regressed")
                last_domain = observation.clock_domain
                if last_capture is not None:
                    source_intervals_s.append(
                        (observation.capture_monotonic_ns - last_capture) / 1e9)
                last_capture = observation.capture_monotonic_ns
                ordinal = seen_nav
                seen_nav += 1
                if ordinal % args.every != 0:
                    continue
                if args.max_frames is not None and progress["candidate_frames"] >= args.max_frames:
                    continue

                key = (observation.key.sensor_id, observation.key.frame_index)
                source_record = source_records.get(key)
                if source_record is None or source_record.get("source_geometry_hash") != observation.geometry_hash:
                    raise ValueError("decoded navigation observation is not bound to its manifest record")
                expected_time = int(source_record["source_capture_monotonic_ns"])
                if observation.capture_monotonic_ns != expected_time:
                    raise ValueError("decoded capture time differs from the original manifest")

                original_observation=observation
                observation=mapping_observation(observation,mapping_domain)
                start_ns = time.monotonic_ns()
                nav = candidate.update_for_control(observation)
                candidate_wall_ms = (time.monotonic_ns() - start_ns) / 1_000_000.0
                if (nav.source != observation.key
                        or nav.capture_monotonic_ns != observation.capture_monotonic_ns
                        or nav.clock_domain != observation.clock_domain):
                    raise ValueError("candidate snapshot lost the source identity/domain")
                candidate_stages = _timing_ms(candidate.last_update_stages)
                candidate_stages["candidate_update_wall"] = candidate_wall_ms
                stage_names.update(candidate_stages)
                candidate_update_times.append(candidate_wall_ms)
                record = dict(
                    source_key=observation.key.to_dict(),
                    source_capture_monotonic_ns=observation.capture_monotonic_ns,
                    source_clock_domain=original_observation.clock_domain,
                    mapping_clock_domain=observation.clock_domain,
                    source_geometry_hash=original_observation.geometry_hash,
                    source_payload_sha256=source_record["sha256"],
                    source_frame_ordinal=ordinal,
                    source_interval_from_previous_selected_s=(
                        None if previous_selected_capture is None else
                        (observation.capture_monotonic_ns - previous_selected_capture) / 1e9),
                    time_bucket=_time_bucket(observation.capture_monotonic_ns,
                                             full_start_ns, full_end_ns),
                    candidate_stage_ms=candidate_stages,
                    candidate_state_counts=_state_counts(nav),
                    candidate_retention_diagnostics=_retention_diagnostics(candidate),
                    candidate_footprint=footprint_diagnostic(
                        nav, tuple(float(value) for value in observation.T_world_camera[:2, 3]),
                        candidate_robot),
                )
                diagnostics = record["candidate_retention_diagnostics"]
                last_diagnostics = diagnostics
                retention_records.append(diagnostics)
                comparison = None
                if baseline is not None:
                    baseline_started = time.monotonic_ns()
                    baseline_nav = baseline.update_for_control(observation)
                    baseline_wall_ms = (time.monotonic_ns() - baseline_started) / 1_000_000.0
                    baseline_update_times.append(baseline_wall_ms)
                    progress["baseline_frames"] += 1
                    if (baseline_nav.source != observation.key
                            or baseline_nav.capture_monotonic_ns != observation.capture_monotonic_ns
                            or baseline_nav.clock_domain != observation.clock_domain):
                        raise ValueError("reference snapshot lost the source identity/domain")
                    comparison = compare_snapshots(nav, baseline_nav)
                    record["baseline_reference_update_wall_ms"] = baseline_wall_ms
                    record["candidate_vs_legacy_radius2"] = comparison
                    record["baseline_state_counts"] = _state_counts(baseline_nav)
                    record["baseline_retention_diagnostics"] = _retention_diagnostics(baseline)
                    record["baseline_footprint"] = footprint_diagnostic(
                        baseline_nav, tuple(float(value) for value in observation.T_world_camera[:2, 3]),
                        baseline_robot)

                if args.refresh_overview:
                    overview_started = time.monotonic_ns()
                    candidate.refresh_overview(nav)
                    overview_wall_ms = (time.monotonic_ns() - overview_started) / 1_000_000.0
                    record["candidate_overview_outside_core_ms"] = overview_wall_ms
                    record["candidate_overview_stages_ms"] = _timing_ms(candidate.last_overview_stages)

                frame_file.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                frame_file.flush()
                if previous_selected_capture is not None:
                    selected_intervals_s.append(
                        (observation.capture_monotonic_ns - previous_selected_capture) / 1e9)
                previous_selected_capture = observation.capture_monotonic_ns
                frames.append(dict(time_bucket=record["time_bucket"],
                                   stage_ms=candidate_stages))
                progress["candidate_frames"] += 1
                progress["last_source_key"] = observation.key.to_dict()
                progress["last_source_capture_monotonic_ns"] = observation.capture_monotonic_ns
        finally:
            frame_file.close()

        if seen_nav != input_navigation_count:
            raise ValueError(f"decoded {seen_nav} navigation frames but manifest declares {input_navigation_count}")
        if progress["candidate_frames"] == 0:
            raise ValueError("frame selection produced no navigation observations")
        if baseline is not None and progress["baseline_frames"] != progress["candidate_frames"]:
            raise ValueError("same-run baseline did not consume every candidate source frame")

        candidate_close = candidate.close()
        candidate = None
        baseline_close = None
        if baseline is not None:
            baseline_close = baseline.close()
            baseline = None
        if not candidate_close.get("clean_shutdown", False):
            errors.append("candidate mapper close was not clean")
        if baseline_close is not None and not baseline_close.get("clean_shutdown", False):
            errors.append("baseline mapper close was not clean")
        if errors:
            raise RuntimeError("; ".join(errors))

        processed_times = [int(frame["source_capture_monotonic_ns"]) for frame in
                           (json.loads(line) for line in (args.output / "frames.jsonl").read_text().splitlines())]
        selected_count = progress["candidate_frames"]
        sampled = args.every != 1 or selected_count < input_navigation_count
        coverage_s = max(0.0, (processed_times[-1] - processed_times[0]) / 1e9)
        coverage_fraction = (None if full_end_ns <= full_start_ns else
                             max(0.0, min(1.0, (processed_times[-1] - processed_times[0])
                                           / (full_end_ns - full_start_ns))))
        stage_names = sorted(stage_names)
        parsed_frames = [json.loads(line) for line in
                         (args.output / "frames.jsonl").read_text().splitlines()]
        timing = {stage: _distribution([frame["candidate_stage_ms"][stage]
                                        for frame in parsed_frames
                                        if stage in frame["candidate_stage_ms"]])
                  for stage in stage_names}
        thirds = _stage_summary(frames, stage_names)
        latest_counts = parsed_frames[-1]["candidate_state_counts"]
        state_keys = ("free", "occupied", "unknown", "total")
        state_count_distributions = {
            key: _distribution([frame["candidate_state_counts"][key] for frame in parsed_frames])
            for key in state_keys
        }
        state_count_early_mid_late = {
            bucket: {
                key: _distribution([frame["candidate_state_counts"][key] for frame in parsed_frames
                                    if frame["time_bucket"] == bucket])
                for key in state_keys
            }
            for bucket in ("early", "mid", "late")
        }
        footprint_samples = [frame["candidate_footprint"]["robot_footprint_free"]
                             for frame in parsed_frames]
        comparison_samples = [frame["candidate_vs_legacy_radius2"]
                              for frame in parsed_frames if "candidate_vs_legacy_radius2" in frame]
        overview_samples = [frame["candidate_overview_outside_core_ms"]
                            for frame in parsed_frames if "candidate_overview_outside_core_ms" in frame]
        summary = dict(
            schema_version=1,
            status="complete",
            experiment=dict(
                purpose="offline spatial-window and local-retention measurement",
                candidate_radius_m=args.radius,
                candidate_retention_s=args.retention_seconds,
                legacy_baseline=dict(enabled=args.compare_baseline, radius_m=2.0,
                                     retention="absent") if args.compare_baseline else None,
                numba_warmup_succeeded=numba_warmed,
                numba_warmup_duration_ms=warmup_duration_ms,
                raycast_backend="cpu",
                archive_enabled=False,
                overview_refreshed_outside_core=args.refresh_overview,
                single_candidate_per_invocation=True,
            ),
            provenance=source_info,
            recording_certificate=reader.certificate,
            selection=dict(
                policy=f"every {args.every}th {nav_sensor} depth_only frame starting at ordinal 0",
                max_frames=args.max_frames,
                sampled=sampled,
                input_navigation_frames=input_navigation_count,
                decoded_navigation_frames=seen_nav,
                candidate_frames=selected_count,
                frame_fraction=selected_count / input_navigation_count,
                selected_source_start_ns=processed_times[0],
                selected_source_end_ns=processed_times[-1],
                selected_source_span_s=coverage_s,
                full_source_span_covered_fraction=coverage_fraction,
                original_all_frame_interval_s=_distribution(source_intervals_s),
                selected_frame_interval_s=_distribution(selected_intervals_s),
                sample_disclosure=(
                    "Selected frames are integrated at their original capture times; skipped frames are not integrated. "
                    "ReplayReader.source_frames streams and validates source observations sequentially; no image sequence is cached."
                ),
            ),
            timing=dict(
                candidate_update_ms=timing,
                candidate_update_early_mid_late_ms=thirds,
                same_run_legacy_reference_update_ms=_distribution(baseline_update_times),
                overview_outside_core_ms=_distribution(overview_samples),
                timing_scope="wall time around candidate NavMapper.update_for_control; excludes optional overview and legacy reference calls",
            ),
            map_state=dict(
                last_frame_candidate_counts=latest_counts,
                last_frame_candidate_free_fraction=(latest_counts["free"] / latest_counts["total"]),
                state_count_distributions=state_count_distributions,
                state_count_early_mid_late=state_count_early_mid_late,
                last_frame_candidate_footprint=parsed_frames[-1]["candidate_footprint"],
                last_frame_baseline_footprint=parsed_frames[-1].get("baseline_footprint"),
                candidate_footprint_clearance_distribution=_distribution([
                    frame["candidate_footprint"]["footprint_min_clearance_m"]
                    for frame in parsed_frames
                    if frame["candidate_footprint"]["footprint_min_clearance_m"] is not None]),
                candidate_footprint_free_frames=sum(footprint_samples),
                candidate_footprint_frames=len(footprint_samples),
                candidate_footprint_free_fraction=sum(footprint_samples) / len(footprint_samples),
                comparison_summary=(
                    _distribution([value["state_agreement"] for value in comparison_samples
                                   if value["state_agreement"] is not None])
                    if comparison_samples else None),
                floor_parity_summary=(
                    _distribution([value["floor_agreement"] for value in comparison_samples
                                   if value["floor_agreement"] is not None])
                    if comparison_samples else None),
                clearance_parity_summary=(
                    _distribution([value["clearance_agreement"] for value in comparison_samples
                                   if value["clearance_agreement"] is not None])
                    if comparison_samples else None),
            ),
            retention=dict(
                diagnostics_required=True,
                per_frame=retention_records,
                latest=last_diagnostics,
                resident_bytes_distribution=_distribution([item["resident_bytes"] for item in retention_records]),
                timestamp_metadata_bytes_distribution=_distribution(
                    [item["resident_timestamp_bytes"] for item in retention_records]),
                resident_tile_count_distribution=_distribution(
                    [item["resident_tile_count"] for item in retention_records]),
            ),
            limitations=dict(
                live_freshness_or_motion_claim=False,
                historical_source_age_is_not_live_freshness=True,
                robot_footprint_semantics=(
                    "At each recorded navigation pose, capsule_cells(start=end) uses radius+margin and the current map's "
                    "FREE, floor-support, and clearance predicates. This is an offline diagnostic only."
                ),
                artificial_window_boundary=(
                    "A local window can introduce UNKNOWN boundaries, artificial frontiers, repeated goals, or lost usable footprint. "
                    "Out-of-window footprint cells are counted; navigation behavior at these boundaries is not proven by replay."
                ),
                timing_scope="Offline single-thread CPU replay; not a live freshness, native runtime, or UI-on throughput claim.",
            ),
            elapsed_wall_s=(time.monotonic_ns() - run_started) / 1e9,
        )
        _write_json(args.output / "summary.json", summary)
        return summary
    except Exception as exc:
        if candidate is not None:
            try:
                candidate.close()
            except Exception as close_exc:
                errors.append(f"candidate close failed: {type(close_exc).__name__}: {close_exc}")
        if baseline is not None:
            try:
                baseline.close()
            except Exception as close_exc:
                errors.append(f"baseline close failed: {type(close_exc).__name__}: {close_exc}")
        failure = dict(
            schema_version=1,
            status="failed",
            error=dict(type=type(exc).__name__, message=str(exc)),
            close_errors=errors,
            progress=progress,
            provenance=source_info,
            recording_certificate=reader.certificate,
            elapsed_wall_s=(time.monotonic_ns() - run_started) / 1e9,
            partial_metrics_file="frames.jsonl" if (args.output / "frames.jsonl").exists() else None,
        )
        _write_json(args.output / "failure.json", failure)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, required=True,
                        help="complete recording directory; only the configured navigation depth stream is mapped")
    parser.add_argument("--config", type=Path, required=True,
                        help="checked profile that pins floor calibration and navigation sensor")
    parser.add_argument("--output", type=Path, required=True,
                        help="new output directory; existing directories are never overwritten")
    parser.add_argument("--radius", type=float, required=True,
                        help="candidate snapshot radius in meters")
    parser.add_argument("--retention-seconds", type=float, required=True,
                        help="candidate local retention; zero selects legacy behavior (argument omitted from mapper)")
    parser.add_argument("--max-frames", type=int,
                        help="optional maximum selected navigation frames; truncation is disclosed")
    parser.add_argument("--every", type=int, default=1,
                        help="map every Nth navigation depth frame, starting at ordinal zero; timing gaps stay intact")
    parser.add_argument("--compare-baseline", action="store_true",
                        help="also replay a serial unbounded radius-2 legacy mapper and compare common cells")
    parser.add_argument("--refresh-overview", action="store_true",
                        help="time optional overview refresh separately after each candidate map update")
    args = parser.parse_args(argv)
    output = Path(args.output)
    created_output = False
    try:
        if output.exists():
            raise FileExistsError(f"output directory already exists: {output}")
        output.mkdir(parents=True, exist_ok=False)
        created_output = True
        summary = run(args)
    except Exception as exc:
        print(f"navmap window measurement failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        if created_output and not (output / "failure.json").exists():
            _write_json(output / "failure.json", dict(
                schema_version=1, status="failed",
                error=dict(type=type(exc).__name__, message=str(exc)),
                partial_metrics_file="frames.jsonl" if (output / "frames.jsonl").exists() else None,
            ))
        return 1
    print(json.dumps(dict(status="complete", output=str(output.resolve()),
                          candidate_frames=summary["selection"]["candidate_frames"],
                          summary=str((output / "summary.json").resolve())), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

