#!/usr/bin/env python3
"""Fold durable owner events from an isolated Hydra worker on a sealed prefix."""
import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys

from neusymnav.backends.hydra.session import HydraSession
from neusymnav.reasoninggraph.native_lineage import NativeObjectLineage
from tools.probe_hydra_detail import selected_prefix


def file_sha(path):
    with path.open('rb') as stream:
        return sha256_from_stream(stream)


def sha256_from_stream(stream):
    result = sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        result.update(block)
    return result.hexdigest()


def run(args):
    frames = selected_prefix(args.journal, args.frames)
    args.out.mkdir(parents=True, exist_ok=False)
    recorded = args.out / 'journal.jsonl'
    command = (sys.executable, 'src/neusymnav/backends/hydra/entry.py',
               '--config-root', str(args.config_root), '--artifact-dir', str(args.out / 'native'))
    session = HydraSession(frames[0][0].source_key.episode_id, command=command, journal_path=recorded,
                           object_event_journal=True)
    lineage = NativeObjectLineage()
    rows = []
    room_stability = None
    try:
        for revision, (frame, prefix) in enumerate(frames, 1):
            if session.offer(frame).status != 'queued' or not session.wait_for_revision(revision, 30):
                raise RuntimeError(f'native worker did not accept revision {revision}')
            token = session.current_read_token()
            if token is None or token.graph_revision != revision or token.input_prefix_sha256 != prefix:
                raise RuntimeError('accepted native publication differs from selected prefix')
            if token.build_sha256 != args.build_sha256:
                raise RuntimeError('worker did not load the pinned experimental binding')
            batch = session.object_event_batch(token)
            state = session.snapshot()
            if state.graph_revision != revision or state.input_prefix_sha256 != prefix or not state.graph_summary:
                raise RuntimeError('native object projection differs from the batch token')
            if args.expect_room_stability:
                if state.room_stability is None or state.room_stability.get('enabled') is not True:
                    raise RuntimeError('room stability is missing in the native publication')
                room_stability = {key: value for key, value in state.room_stability.items()
                                  if key != 'last_decision'}
            observed = [node['native_id'] for node in state.graph_summary['nodes'] if node['layer_id'] == 2]
            view = lineage.apply(token, batch, observed)
            if view is None:
                raise RuntimeError(f'lineage unavailable at revision {revision}: {lineage.failure}')
            if session.object_lineage(token) != view:
                raise RuntimeError('session lineage differs from the independent fold')
            rows.append(dict(token=asdict(token), epoch=view.epoch, object_ids=list(view.objects),
                             events=[asdict(event) for event in batch.events]))
    finally:
        shutdown = session.close(5)
    if not shutdown['complete'] or shutdown['returncode'] != 0:
        raise RuntimeError('worker did not close cleanly')
    accepted = []
    with recorded.open() as stream:
        for line in stream:
            item = json.loads(line)
            if item.get('event') == 'accepted':
                accepted.append(item)
    if len(accepted) != len(rows) or any(
            event.get('object_event_token') != row['token']
            or event.get('object_event_journal', {}).get('native', {}).get('events') != row['events']
            for event, row in zip(accepted, rows)):
        raise RuntimeError('durable event journal differs from the folded native sequence')
    counts = Counter(f"{event['owner']}:{event['operation']}" for row in rows for event in row['events'])
    report = dict(revisions=len(rows), counts=dict(counts), original_journal_sha256=file_sha(args.journal),
                  accepted_journal_sha256=file_sha(recorded), native_build_sha256=args.build_sha256,
                  room_stability=room_stability,
                  per_revision=rows)
    (args.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'per_revision'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('journal', 'config-root', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--build-sha256', required=True)
    parser.add_argument('--expect-room-stability', action='store_true')
    parser.add_argument('--frames', type=int, choices=range(1, 65), default=18, metavar='1..64')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
