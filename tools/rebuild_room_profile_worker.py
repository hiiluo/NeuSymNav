#!/usr/bin/env python3
"""Diagnostic-only worker wrapper for cProfile of Rebuild room updates."""
from __future__ import annotations

import argparse
import cProfile
import json
import time
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import neusymnav.regions.rebuild_room_worker as host_worker


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-output", type=Path)
    parser.add_argument("--timings-output", type=Path, required=True)
    parser.add_argument("--config-json", required=True)
    args = parser.parse_args(argv)
    if args.profile_output is not None:
        args.profile_output.parent.mkdir(parents=True, exist_ok=True)

    profiler = cProfile.Profile() if args.profile_output is not None else None
    timing_ns = {}
    patched = set()

    def instrument(episode):
        native_worker_type = type(episode.mapping._native.worker)
        if native_worker_type in patched:
            return
        patched.add(native_worker_type)

        def wrap(owner, name, key, *, operation=None, operation_index=0):
            original = getattr(owner, name)

            def timed(self, *call_args, **call_kwargs):
                if (operation is not None and len(call_args) > operation_index
                        and call_args[operation_index] != operation):
                    return original(self, *call_args, **call_kwargs)
                start = time.perf_counter_ns()
                try:
                    return original(self, *call_args, **call_kwargs)
                finally:
                    timing_ns[key] = timing_ns.get(key, 0) + time.perf_counter_ns() - start
            setattr(owner, name, timed)

        wrap(native_worker_type, "integrate", "integrate_wrapper_ns")
        wrap(native_worker_type, "_validate_scan_request", "point_validation_ns")
        wrap(native_worker_type, "_write_request", "integrate_write_ns", operation="integrate", operation_index=1)
        wrap(native_worker_type, "_read_response", "integrate_response_read_ns", operation="integrate")

    original_update = host_worker.RebuildEpisode.update

    def profiled_update(self, payload):
        instrument(self)
        if profiler is not None:
            profiler.enable()
        try:
            return original_update(self, payload)
        finally:
            if profiler is not None:
                profiler.disable()

    host_worker.RebuildEpisode.update = profiled_update
    try:
        return host_worker.main(["--config-json", args.config_json])
    finally:
        if profiler is not None:
            profiler.dump_stats(args.profile_output)
        args.timings_output.write_text(json.dumps({
            "schema_version": 1,
            "scope": "OctoMapWorker.integrate calls inside profiled frame updates",
            "durations_ms": {key: value / 1_000_000 for key, value in sorted(timing_ns.items())},
            "estimated_format_and_other_integrate_ms": max(0, timing_ns.get("integrate_wrapper_ns", 0)
                - timing_ns.get("point_validation_ns", 0)
                - timing_ns.get("integrate_write_ns", 0)
                - timing_ns.get("integrate_response_read_ns", 0)) / 1_000_000,
            "note": "The residual groups text/list construction, encoding, locks, and other integrate wrapper work; it is not a pure serializer timer.",
        }, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
