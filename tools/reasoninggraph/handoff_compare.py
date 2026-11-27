#!/usr/bin/env python3
"""Compare the opt-in evidence sidecar on identical accepted Habitat inputs."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time

import numpy as np

from neusymnav.backends.hydra.runtime import HydraGraphRuntime
from neusymnav.backends.hydra.session import HydraSession
from neusymnav.contracts import Taxonomy, loads
from neusymnav.contracts.hydra_graph import HydraCalibration
from neusymnav.recording.replay import ReplayReader
from neusymnav.runtime.launcher import preflight
from tools.probe_hydra_detail import selected_prefix


def inputs(source, count):
    accepted = selected_prefix(source / 'hydra/journal.jsonl', count)
    keys = {frame.source_key for frame, _ in accepted}
    frames = {}
    for obs in ReplayReader(source / 'keyframes/recording').source_frames():
        if obs.key in keys:
            frames[obs.key] = obs
            if len(frames) == len(keys):
                break
    uri = (source / 'runtime.sqlite').resolve().as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True)
    try:
        result = []
        for frame, prefix in accepted:
            payload, = db.execute('SELECT result FROM frames WHERE idx=?',
                                  (frame.source_key.frame_index,)).fetchone()
            result.append((frames[frame.source_key], loads(payload), prefix))
    finally:
        db.close()
    return accepted[0][0], result


def arm(root, command, calibration, source, batches, taxonomy, enabled):
    artifacts = root / 'native'
    session = HydraSession(source.source_key.episode_id,
        command=(*command, '--artifact-dir', str(artifacts)), journal_path=root / 'journal.jsonl',
        object_event_journal=True, detail_queries=False)
    runtime = HydraGraphRuntime(session, calibration=calibration, taxonomy=taxonomy,
                                detector_profile_id=source.detector_profile_id, reasoninggraph_enabled=enabled)
    runtime.start_reasoninggraph(root, None)
    rows = []
    try:
        for revision, (obs, batch, prefix) in enumerate(batches, 1):
            started = time.perf_counter()
            if runtime.offer(obs, batch).status != 'queued':
                raise ValueError('native replay did not queue an input')
            offer_ms = (time.perf_counter() - started) * 1000
            if not session.wait_for_revision(revision, 20.):
                raise RuntimeError('timed out on native revision')
            snapshot = session.snapshot()
            if snapshot.input_prefix_sha256 != prefix:
                raise ValueError('replayed native prefix differs from the selected live prefix')
            graph = json.dumps(snapshot.graph_summary, sort_keys=True, allow_nan=False)
            rows.append(dict(frame=obs.key.frame_index, prefix=prefix,
                             graph_sha256=sha256(graph.encode()).hexdigest(), offer_ms=offer_ms))
            time.sleep(max(0., .5 - (time.perf_counter() - started)))
        stats = session.stats
    finally:
        closed = runtime.close(5.)
    return dict(rows=rows, service_p95_ms=stats['service_p95_ms'], accepted=stats['accepted'],
                worker_rss_bytes=stats['worker_rss_bytes'], complete=closed['complete'],
                evidence=closed.get('reasoninggraph'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'config', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    verified = preflight(args.config)
    original = json.loads((args.source / 'summary.json').read_text())
    if not verified['ready'] or verified['config_sha256'] != original['config_sha256']:
        raise ValueError('provide the pinned, preflight-ready source config')
    assets = verified['assets']
    native = json.loads(args.config.read_text())['scene_graph']['hydra']
    cal = dict(native['calibration'])
    for key in ('K', 'body_T_camera'):
        cal[key] = np.asarray(cal[key], dtype=np.float64)
    calibration = HydraCalibration(**cal)
    source, batches = inputs(args.source, 18)
    taxonomy = Taxonomy.load(assets['taxonomy'])
    command = ('/bin/bash', 'src/neusymnav/backends/hydra/child.sh', assets['hydra_setup'],
               *assets['hydra'], '--config-root', native['config_root'])
    args.out.mkdir(parents=True, exist_ok=False)
    off = arm(args.out / 'off', command, calibration, source, batches, taxonomy, False)
    on = arm(args.out / 'on', command, calibration, source, batches, taxonomy, True)
    fields = ('frame', 'prefix', 'graph_sha256')
    comparable = all(all(a[k] == b[k] for k in fields) for a, b in zip(off['rows'], on['rows']))
    evidence = on['evidence'] or {}
    checks = dict(matched_prefixes_and_graphs=comparable and off['accepted'] == on['accepted'] == len(batches),
                  shutdown=off['complete'] and on['complete'] and evidence.get('clean_shutdown', False),
                  evidence_published=evidence.get('published', 0) > 0 and evidence.get('errors') == 0,
                  replay_reference_budget=on['service_p95_ms'] <= 1.25 * off['service_p95_ms'] + 10.)
    report = dict(scope='matched native replay, 0.5 s minimum interval', checks=checks, off=off, on=on)
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(checks))
    return int(not all(checks.values()))


if __name__ == '__main__':
    raise SystemExit(main())
