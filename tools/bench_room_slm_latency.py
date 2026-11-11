#!/usr/bin/env python3
"""Measure room-label SLM latency on frozen requests with the persistent server.

Runs the same pinned model/runtime as the live debug service, off the robot:

    .venv/bin/python tools/bench_room_slm_latency.py \
        --config configs/room-label-slm.async-debug.local.json \
        --request-json runs/room-slm-async-debug-20261108/persistent-request-normalized.json \
        --request-json runs/room-slm-diagnosis-20261108/corrected-00805/request-000.json \
        --out runs/room-slm-latency-bench/compact.json

Add ``--baseline`` to also run the old json-v1 policy at one thread for an
A/B on the same machine (slow: roughly a minute per request). Timings are
llama.cpp's own ``prefill``/``decode`` numbers plus host wall time. A label in
this output is a model proposal, not a verified room type.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.contracts.room_semantics import validate_room_label  # noqa: E402
from neusymnav.rooms.persistent_backend import PersistentRoomLabelBackend  # noqa: E402
from neusymnav.rooms.requests import RoomLabelRequest  # noqa: E402
from neusymnav.rooms.slm_backend import RoomSlmBackendConfig  # noqa: E402


def _row(name, index, request, result, metrics):
    timings = metrics.get('native_timings') or {}
    return {'variant': name, 'request': index,
        'objects': [item.category for item in request.context.objects],
        'status': result.status, 'label': result.label,
        'alternatives': list(result.alternatives),
        'supporting_object_ids': list(result.supporting_object_ids), 'reason': result.reason,
        'latency_ms': metrics.get('latency_ms'), 'startup_ms': metrics.get('startup_ms'),
        'server_reused': metrics.get('server_reused'), 'prompt_tokens': metrics.get('prompt_tokens'),
        'cache_n': timings.get('cache_n'), 'prompt_n': timings.get('prompt_n'),
        'prompt_ms': timings.get('prompt_ms'), 'predicted_n': timings.get('predicted_n'),
        'predicted_ms': timings.get('predicted_ms'), 'scheduling': metrics.get('scheduling'),
        'grammar_bytes': metrics.get('grammar_bytes')}


def run_variant(name, config, requests, repeat):
    backend = PersistentRoomLabelBackend(config)
    rows = []
    try:
        warm = backend.warm()
        print(f'[{name}] warm-up: {json.dumps(warm, default=str)}', flush=True)
        for round_index in range(repeat):
            for index, request in enumerate(requests):
                proposal = backend.infer(request)
                result = validate_room_label(proposal, request.context)
                row = _row(name, index, request, result, dict(backend.last_metrics))
                row['round'] = round_index
                rows.append(row)
                print(f"[{name}] r{round_index} req{index} {row['objects']} -> {row['label']} "
                      f"({row['status']}) wall={row['latency_ms']:.0f} ms "
                      f"prefill={row['prompt_n']} tok/{row['prompt_ms']} ms cache={row['cache_n']} "
                      f"decode={row['predicted_n']} tok/{row['predicted_ms']} ms", flush=True)
    finally:
        closed = backend.close(timeout_s=5.0)
    return {'variant': name, 'config': {'threads': config.threads,
        'effective_threads': config.effective_threads, 'nice': config.nice,
        'cpu_affinity': config.cpu_affinity, 'prompt_policy': config.prompt_policy},
        'warmup': warm, 'rows': rows, 'shutdown': closed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', required=True)
    parser.add_argument('--request-json', action='append', required=True)
    parser.add_argument('--threads', type=int, default=None, help='override config threads')
    parser.add_argument('--repeat', type=int, default=2, help='rounds per request (round 2 shows cache reuse)')
    parser.add_argument('--baseline', action='store_true', help='also run json-v1 at 1 thread')
    parser.add_argument('--out', required=True)
    args = parser.parse_args(argv)

    config = RoomSlmBackendConfig.from_json(args.config)
    config = replace(config, enabled=True, prompt_policy='compact-v2',
        **({} if args.threads is None else {'threads': args.threads}))
    requests = [RoomLabelRequest.from_json(Path(path).read_text()) for path in args.request_json]
    for index, request in enumerate(requests):
        if request.inference_block_reason:
            print(f'request {index} is blocked before inference: {request.inference_block_reason}')
    report = {'schema_version': 1, 'kind': 'room_slm_latency_bench',
        'requests': [str(path) for path in args.request_json], 'variants': []}
    report['variants'].append(run_variant('compact-v2', config, requests, args.repeat))
    if args.baseline:
        baseline = replace(config, prompt_policy='json-v1', threads=1, nice=0, cpu_affinity=None,
            max_output_tokens=384)
        report['variants'].append(run_variant('json-v1-1thread', baseline, requests, 1))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str) + '\n')
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
