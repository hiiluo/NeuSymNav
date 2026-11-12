#!/usr/bin/env python3
"""Offline source-bound stage attribution for a completed measurement artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from neusymnav.evaluation.measurements import analyze_control_stages, load_measurements


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--measurements', required=True, type=Path)
    parser.add_argument('--attempt-id', required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--episode-id')
    parser.add_argument('--clock-domain')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    value, inspection = load_measurements(args.measurements,
        attempt_id=args.attempt_id, config_sha256=args.config_sha256,
        episode_id=args.episode_id, clock_domain=args.clock_domain)
    report = analyze_control_stages(value, inspection)
    report['measurement_file_sha256'] = hashlib.sha256(args.measurements.read_bytes()).hexdigest()
    report['measurement_path'] = str(args.measurements.resolve())
    report['execution_binding'] = {
        'attempt_id': inspection['context'].attempt_id,
        'episode_id': inspection['context'].episode_id,
        'clock_domain': inspection['context'].clock_domain,
        'config_sha256': inspection['context'].config_sha256,
        'launch_config_sha256': inspection['context'].launch_config_sha256,
        'binding_source': 'caller-supplied attempt/config; internal schema and trace independently validated',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n',
                           encoding='utf-8')
    summary = {name: {
        'support': metric['support'], 'p95_ms': metric['p95_ms'],
        'max_ms': metric['max_ms'], 'status': metric['status'],
    } for name, metric in report['stages'].items()
        if metric['support'] or name.startswith(('sensor_', 'navmap_', 'control_', 'local_', 'actuation'))}
    print(json.dumps({'output': str(args.output.resolve()),
        'trace_complete': report['trace_complete'],
        'retained_stage_records': report['retained_stage_records'],
        'unbound_stage_records': report['unbound_stage_records'],
        'stages': summary}, sort_keys=True))
    return 0 if report['trace_complete'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
