#!/usr/bin/env python3
"""Observe read-only Hydra queries, evidence and lineage during a bounded live run."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
from threading import Event, Thread

from neusymnav.contracts.hydra_evidence import HydraObjectKey
from neusymnav.runtime import launcher


def observe(pipeline, stop, rows, errors):
    previous = None
    last = None
    runtime = pipeline._hydra_runtime
    session = runtime.session
    try:
        while not stop.wait(.12):
            token = session.current_read_token()
            if token is None:
                continue
            query = pipeline.scene_graph_query()
            if query is None or query.read_token != token:
                continue
            graph = runtime.reasoninggraph_snapshot()
            if graph is None or graph[0].native != token:
                continue
            graph_token = asdict(graph[0])
            lineage = session.object_lineage(token)
            rooms = query.rooms()
            objects = query.objects()
            available = []
            for obj in objects:
                key = HydraObjectKey(token.episode_id, token.run_id, obj.native_id, token.graph_revision)
                page = query.evidence(key)
                if page.status == 'available':
                    available.extend(asdict(ref) for ref in page.refs)
            stale_prior = previous is not None and previous.read_token != token
            if session.current_read_token() != token or rooms.status != 'available':
                continue
            if any(ref['input_prefix_sha256'] != token.input_prefix_sha256 for ref in available):
                raise ValueError('evidence prefix differs from current revision')
            row = dict(token=graph_token, lineage=lineage is not None, objects=len(objects),
                       rooms=[ref.native_id for ref in rooms.value.items], evidence=available,
                       stale_prior_read=stale_prior and previous.rooms().status == 'stale')
            state = (token, tuple(ref['asset_key'] for ref in available))
            if state != last:
                rows.append(row)
                last = state
            previous = query
    except Exception as exc:
        errors.append(repr(exc))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--duration-s', type=int, default=48, choices=range(20, 121), metavar='20–120')
    args = parser.parse_args()
    if not json.loads(args.config.read_text())['scene_graph']['hydra'].get('reasoninggraph_evidence'):
        parser.error('the live probe requires scene_graph.hydra.reasoninggraph_evidence')
    args.out.mkdir(parents=True, exist_ok=False)

    stop, threads, rows, errors = Event(), [], [], []
    original = launcher._pipeline

    def instrument(*positional, **named):
        pipeline = original(*positional, **named)
        thread = Thread(target=observe, args=(pipeline, stop, rows, errors), daemon=True)
        thread.start()
        threads.append(thread)
        return pipeline

    launcher._pipeline = instrument
    try:
        result = launcher.run(args.config, duration_s=args.duration_s, out=args.out / 'live')
    finally:
        launcher._pipeline = original
        stop.set()
        for thread in threads:
            thread.join(2)
            if thread.is_alive():
                errors.append('observer did not shut down')
        (args.out / 'observations.json').write_text(json.dumps(dict(rows=rows, errors=errors), indent=2) + '\n')
    export = json.loads((args.out / 'live/hydra/native-output/hydra-export-manifest.json').read_text())
    selected = {r['graph_revision']: r for r in export['selected_inputs']}
    for row in rows:
        token = row['token']
        native = token['native']
        entry = selected.get(native['graph_revision'])
        if entry is None or native['input_prefix_sha256'] != entry['input_prefix_sha256']:
            errors.append('observed lineage/query prefix absent from export')
            break
        expected = entry['source']
        fields = ('clock_domain', 'capture_monotonic_ns', 'calibration_hash', 'source_geometry_hash',
                  'vocabulary_id', 'labelspace_hash')
        if (any(expected.get(key) != val for key, val in token['source'].items())
                or any(expected.get(key) != token[key] for key in fields)):
            errors.append('query source differs from exported accepted input')
            break
        if any(ref['source'] != token['source'] or any(token[key] != ref.get(key) for key in
                      ('clock_domain', 'capture_monotonic_ns', 'calibration_hash', 'pose_version',
                       'vocabulary_id', 'detector_profile_id'))
               for ref in row['evidence']):
            errors.append('evidence source differs from exported accepted input')
            break
    checks = dict(recording=result['recording_certificate']['complete'], export=export['complete'],
                  shutdown=result['runtime']['clean_shutdown'],
                  current_topology=any(row['rooms'] and row['objects'] for row in rows),
                  lineage=bool(rows) and all(row['lineage'] for row in rows),
                  evidence=any(row['evidence'] for row in rows),
                  stale_prior_read=any(row['stale_prior_read'] for row in rows),
                  observer_clean=not errors)
    report = dict(scope='live read-only native topology, lineage and evidence', checks=checks,
                  revisions=len({row['token']['native']['graph_revision'] for row in rows}), errors=errors,
                  launcher_outcome=result['outcome'], launcher_error=result['error'],
                  full_native_runtime_validated=result['native_runtime_validated'])
    output = json.dumps(report, indent=2)
    (args.out / 'verification.json').write_text(output + '\n')
    print(output)
    return int(not all(checks.values()) or result['error'] is not None)


if __name__ == '__main__':
    raise SystemExit(main())
