#!/usr/bin/env python3
"""Validate HNA on saved Spark-DSG exports and the same native replay prefix."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import resource
import sys
import time

from neusymnav.backends.hydra.detail_reader import (
    AssetStore, SavedHydraDetailReader, export_token,
)
from neusymnav.backends.hydra.runtime import HydraGraphRuntime
from neusymnav.backends.hydra.session import HydraSession
from neusymnav.backends.hydra.worker import _graph_summary
from neusymnav.contracts import Taxonomy, loads
from neusymnav.contracts.hydra_graph import HydraCalibration, NativeDetailRequest, NativeNodeRef


def summary_metrics(summary):
    started = time.perf_counter()
    encoded = json.dumps(summary, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    decoded = json.loads(encoded)
    assert decoded == summary
    return {
        'json_bytes': len(encoded), 'sha256': hashlib.sha256(encoded).hexdigest(),
        'encode_decode_ms': (time.perf_counter() - started) * 1000,
    }


def saved_export(manifest_path, assets):
    manifest = json.loads(manifest_path.read_text())
    token = export_token(manifest)
    asset_store = AssetStore(assets)
    from spark_dsg import DynamicSceneGraph

    # The reader checks the manifest and opens a file containing the verified bytes.
    graphs = []

    def tracked_load(path):
        graph = DynamicSceneGraph.load(path)
        graphs.append(graph)
        return graph

    reader = SavedHydraDetailReader(manifest_path, token, asset_store, graph_loader=tracked_load)
    counts = {}
    metrics = {}
    started = time.perf_counter()
    initial = reader.read(NativeDetailRequest(NativeNodeRef(token, 'O(0)', 2), 'attributes'))
    cold_ms = (time.perf_counter() - started) * 1000
    assert graphs, initial
    for layer in (2, 3, 4):
        native = str(next(iter(graphs[0].get_layer(layer).nodes)).id)
        ref = NativeNodeRef(token, native, layer)
        durations = []
        for _ in range(6):
            started = time.perf_counter()
            result = reader.read(NativeDetailRequest(ref, 'attributes'))
            durations.append((time.perf_counter() - started) * 1000)
            assert result.status == 'available', (manifest_path, ref, result)
        metrics[str(layer)] = {'first_ms': durations[0], 'warm_max_ms': max(durations[1:])}
    graph = graphs.pop()
    summary = _graph_summary(graph, graph_revision=token.graph_revision,
                             input_prefix_sha256=token.input_prefix_sha256)
    for raw in summary['nodes']:
        ref = NativeNodeRef(token, raw['native_id'], raw['layer_id'])
        if ref.layer_id in (2, 3, 4):
            counts[ref.layer_id] = counts.get(ref.layer_id, 0) + 1
            attrs = reader.read(NativeDetailRequest(ref, 'attributes'))
            assert attrs.status == 'available', (ref, attrs)
            if ref.layer_id == 2:
                box = reader.read(NativeDetailRequest(ref, 'bbox'))
                assert box.status == 'available' and len(box.value['corners_xyz_m']) == 8
                mesh = reader.read(NativeDetailRequest(ref, 'mesh'))
                assert mesh.status == 'available', (ref, mesh)
                assert len(reader.read_asset(ref, mesh.value).value['xyz']) <= 64
            assert reader.read(NativeDetailRequest(ref, 'feature')).status == 'missing'
    native = {node['native_id']: node['layer_id'] for node in summary['nodes']}
    place_edge = next(edge for edge in summary['edges']
                      if native[edge['source_native_id']] == native[edge['target_native_id']] == 3)
    edge = reader.read(NativeDetailRequest(
        NativeNodeRef(token, place_edge['source_native_id'], 3), 'edge',
        target=NativeNodeRef(token, place_edge['target_native_id'], 3)))
    assert edge.status == 'available' and edge.value['weighted'] and edge.value['weight'] > 0
    reader.close()
    return dict(counts=counts, reads=metrics, cold_open_ms=cold_ms, summary=summary_metrics(summary),
                verified_graph_sha256=manifest['graph_sha256'],
                asset_bytes=asset_store.bytes, asset_evictions=asset_store.evictions)


def selected_prefix(journal_path, count):
    pending = {}
    result = []
    with journal_path.open() as stream:
        for line in stream:
            row = json.loads(line)
            for item in row.get('events', [row]) if row.get('event') == 'batch' else [row]:
                event = item.get('event')
                source = item.get('source')
                if not source:
                    continue
                key = (row['run_id'], source['episode_id'], source['sensor_id'], source['frame_index'])
                if event == 'started' and item.get('selected_frame'):
                    pending[key] = item['selected_frame']
                elif event == 'accepted' and key in pending:
                    result.append((loads(pending.pop(key)), item['input_prefix_sha256']))
                    if len(result) == count:
                        return result
                elif event in ('failed', 'step_rejected'):
                    pending.pop(key, None)
    raise ValueError('journal has insufficient selected and accepted frames')


def replay(frames, command, root, enabled, taxonomy):
    artifacts = root / 'native'
    process_command = (*command, '--artifact-dir', str(artifacts))
    session = HydraSession(frames[0][0].source_key.episode_id, command=process_command,
                           journal_path=root/'journal.jsonl', detail_queries=enabled,
                           detail_asset_root=artifacts/'detail-assets')
    source = frames[0][0]
    calibration = HydraCalibration(source.calibration_id, source.calibration_version,
        source.source_key.sensor_id, 'replay_rgbd', source.K, source.body_T_camera, source.pose_version,
        source.coordinate_convention, source.camera_convention, source.depth_convention, 'HNA selected-prefix replay')
    runtime = HydraGraphRuntime(session, calibration=calibration, taxonomy=taxonomy,
                                detector_profile_id=source.detector_profile_id)
    summaries = []
    queries = []
    mesh_reads = 0
    old_query = None
    try:
        for revision, (frame, expected_prefix) in enumerate(frames, start=1):
            assert session.offer(frame).status == 'queued'
            assert session.wait_for_revision(revision, 30.0), session.stats
            start = time.perf_counter()
            snapshot = session.snapshot()
            copy_ms = (time.perf_counter() - start) * 1000
            assert snapshot.input_prefix_sha256 == expected_prefix
            summaries.append(dict(copy_ms=copy_ms, **summary_metrics(snapshot.graph_summary)))
            if old_query is not None:
                assert old_query.rooms().status == 'stale'
                old_query = None
            if not enabled or (revision % 4 != 0 and revision != len(frames)):
                continue
            place = next((node for node in snapshot.graph_summary['nodes'] if node['layer_id'] == 3), None)
            if place is None:
                continue
            query = runtime.scene_graph_query()
            assert query.read_token.graph_revision == revision
            assert query.read_token.input_prefix_sha256 == expected_prefix
            ref = query.node_ref(place['native_id'])
            started = time.perf_counter()
            result = query.place_detail(ref).value.native
            while result.status == 'pending' and time.perf_counter() - started < 3:
                time.sleep(.002)
                result = query.place_detail(ref).value.native
            assert result.status == 'available' and result.value['gvd_distance_m'] > 0, result
            elapsed = (time.perf_counter() - started) * 1000
            cached = time.perf_counter()
            assert query.place_detail(ref).value.native == result
            queries.append(dict(revision=revision, cold_ms=elapsed,
                                warm_ms=(time.perf_counter() - cached) * 1000))
            old_query = query

            objects = query.objects()
            if objects:
                obj = query.node_ref(objects[0].native_id)
                started = time.perf_counter()
                asset = query.geometry(obj, 'mesh')
                while asset.status == 'pending' and time.perf_counter() - started < 3:
                    time.sleep(.002)
                    asset = query.geometry(obj, 'mesh')
                assert asset.status == 'available', asset
                mesh = query.read_asset(obj, asset.value)
                assert mesh.status == 'available' and 1 <= len(mesh.value['xyz']) <= 64
                mesh_reads += 1
        assert not enabled or queries, 'replay never reached a queryable native place'
        assert not enabled or mesh_reads, 'replay never reached a queryable object mesh'
        stats = session.stats
    finally:
        closed = runtime.close(5.0)
    assert closed['complete'] and closed['returncode'] == 0, closed
    return dict(summaries=summaries, live_queries=queries, mesh_reads=mesh_reads, stats=stats,
                output_bytes=sum(file.stat().st_size for file in root.rglob('*') if file.is_file()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', action='append', type=Path, required=True)
    parser.add_argument('--journal', type=Path)
    parser.add_argument('--frames', type=int, default=12)
    parser.add_argument('--worker-python', type=Path, default=Path(sys.executable))
    parser.add_argument('--config-root', type=Path)
    parser.add_argument('--taxonomy', type=Path, default=Path('configs/taxonomy-v1.json'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    report = {'saved': [saved_export(path, args.out/f'saved-{index}')
                         for index, path in enumerate(args.manifest)]}
    if args.journal:
        if args.config_root is None or not 1 <= args.frames <= 64:
            parser.error('replay requires a config root and a prefix of 1–64 frames')
        frames = selected_prefix(args.journal, args.frames)
        entry = Path(__file__).resolve().parents[1]/'src/neusymnav/backends/hydra/entry.py'
        command = (str(args.worker_python.absolute()), str(entry), '--config-root', str(args.config_root))
        taxonomy = Taxonomy.load(args.taxonomy)
        off = replay(frames, command, args.out/'off', False, taxonomy)
        on = replay(frames, command, args.out/'detail', True, taxonomy)
        parity = [a['sha256'] == b['sha256'] for a, b in zip(off['summaries'], on['summaries'])]
        # Small CPU replay guardrails. These are qualification bounds, not speedup claims.
        off_p95 = off['stats']['service_p95_ms']
        checks = {
            'frame_summary_parity': all(parity),
            'detail_cold_under_50_ms': max(row['cold_ms'] for row in on['live_queries']) <= 50.,
            'frame_p95_within_25_pct_plus_10_ms': on['stats']['service_p95_ms'] <= 1.25 * off_p95 + 10.,
            'extra_worker_rss_at_most_128_mib': on['stats']['worker_rss_bytes'] <=
                off['stats']['worker_rss_bytes'] + 128 * 1024 * 1024,
            'no_detail_transport_failure': not on['stats']['detail']['failed'],
        }
        report.update(off=off, on=on, summary_parity=parity, qualification=checks)
    report['reader_peak_rss_kib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    (args.out/'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if args.journal and not all(report['qualification'].values()):
        raise SystemExit('native replay qualification failed; see report.json')


if __name__ == '__main__':
    main()
