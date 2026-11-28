#!/usr/bin/env python3
"""Prepare exact accepted Hydra RGB-D and archived receipt masks for offline GT."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from neusymnav.backends.hydra.labels import HydraLabelRasterizer
from neusymnav.contracts.hydra_graph import HydraFrame, HydraReadToken
from neusymnav.contracts.hydra_lineage import NativeObjectBatch
from neusymnav.contracts.observations import Taxonomy
from neusymnav.objectnav.episodes import load_episode_set
from neusymnav.objectnav.detector_eval.categories import GoalCategories


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')


def source_arrays(frame, entries):
    masks, descriptors = [], []
    for receipt, manifest in entries:
        ref, token = receipt['evidence'], receipt['source_token']
        assert frame.source_key.episode_id == token['source']['episode_id']
        assert frame.source_key.frame_index == token['source']['frame_index']
        assert frame.capture_monotonic_ns == token['capture_monotonic_ns'] == ref['capture_monotonic_ns']
        assert frame.source_geometry_hash == token['source_geometry_hash']
        x0, y0, x1, y1 = ref['bbox_xyxy']
        mask = np.zeros(frame.depth_m.shape, dtype=bool)
        with np.load(manifest.parent.parent / ref['asset_key'], allow_pickle=False) as crop:
            assert hashlib.sha256(crop['mask'].tobytes(order='C')).hexdigest() == ref['mask_sha256']
            assert np.array_equal(crop['rgb'], frame.rgb[y0:y1, x0:x1])
            valid = frame.valid_depth[y0:y1, x0:x1]
            assert np.array_equal(crop['valid'], valid)
            assert np.array_equal(crop['depth_m'][valid], frame.depth_m[y0:y1, x0:x1][valid])
            mask[y0:y1, x0:x1] = crop['mask']
        masks.append(mask)
        descriptors.append(dict(detection_id=ref['detection_id'], mask_sha256=ref['mask_sha256']))
    stack = np.stack(masks) if masks else np.zeros((0,) + frame.depth_m.shape, dtype=bool)
    return dict(rgb=frame.rgb, depth=frame.depth_m, valid=frame.valid_depth, masks=stack,
                K=frame.K, pose=frame.world_T_body @ frame.body_T_camera), descriptors


def capture_episode(uid, tap, export, labels, destination, taxonomy):
    import spark_dsg

    journal, graph_path = Path(export['journal_path']), Path(export['graph_path'])
    if not export['complete'] or digest(journal) != export['journal_sha256'] or digest(graph_path) != export['graph_sha256']:
        raise ValueError('native close or hash mismatch: ' + uid)
    manifests = {}
    for path in tap.glob('reasoninggraph/*/revision-*/manifest.json'):
        value = json.loads(path.read_text())
        rev = value['native']['graph_revision']
        if rev in manifests:
            raise ValueError('duplicate revision')
        manifests[rev] = path, value
    cutoff = export['graph_revision']
    if set(manifests) != set(range(1, cutoff + 1)):
        raise ValueError('exact revision evidence is incomplete: ' + uid)
    graph = spark_dsg.DynamicSceneGraph.load(str(graph_path))
    active = ({} if not graph.has_layer(2) else {
        str(node.id): labels.get(int(node.attributes.semantic_label)) for node in graph.get_layer(2).nodes
    })
    groups, seen, live, frames = {}, set(), set(), []
    selected = None
    for line in journal.open():
        row = json.loads(line)
        if row['event'] == 'started':
            selected = row['selected_frame']
        if row['event'] != 'accepted' or not row['accepted']:
            continue
        rev = row['graph_revision']
        manifest, record = manifests[rev]
        token = HydraReadToken(**record['native'])
        if (token.episode_id != export['episode_id'] or token.run_id != export['run_id']
                or token.input_prefix_sha256 != row['input_prefix_sha256']
                or record['vocabulary_id'] != taxonomy.vocabulary_id):
            raise ValueError('native scope or source mismatch')
        batch = NativeObjectBatch.from_wire(row['object_event_journal'], token=token,
                                           timestamp_ns=record['capture_monotonic_ns'])
        for event in batch.events:
            if event.operation == 'create':
                live.add(event.source)
            if event.operation in ('delete', 'merge'):
                live.discard(event.source)
            if event.operation == 'merge':
                groups.pop(event.source, None)
                groups.pop(event.target, None)
            if event.operation == 'reconcile':
                groups.setdefault(event.target, []).extend(groups.pop(event.source, ()))
        votes = record['confirmed_receipts']
        for vote in votes:
            owner = vote['canonical_object']['native_id']
            key = (rev, vote['evidence']['detection_id'])
            if (owner not in live or key in seen or vote['evidence']['link_status'] != 'native_confirmed'
                    or vote['category'] not in taxonomy.categories):
                raise ValueError('invalid exact native receipt')
            seen.add(key)
            groups.setdefault(owner, []).append(dict(revision=rev, detection_id=key[1], category=vote['category']))
        if votes or rev == cutoff:
            frame = HydraFrame.from_json(selected)
            assert frame.source_key.frame_index == record['source']['frame_index']
            arrays, refs = source_arrays(frame, [(vote, manifest) for vote in votes])
            filename = f'{len(frames):05d}.npz'
            path = destination / filename
            np.savez_compressed(path, **arrays)
            frames.append(dict(file=filename, sha256=digest(path), revision=rev, source=record['source'],
                               input_prefix_sha256=token.input_prefix_sha256, receipts=refs))
    if not frames or frames[-1]['revision'] != cutoff or set(active) != live:
        raise ValueError('export endpoint roster or cutoff differs from native journal')
    if frames[-1]['input_prefix_sha256'] != export['input_prefix_sha256']:
        raise ValueError('export input prefix differs from captured cutoff')
    return dict(uid=uid, revision=cutoff, prefix=export['input_prefix_sha256'], frames=frames,
                journal_sha256=export['journal_sha256'], graph_sha256=export['graph_sha256'],
                owners={key: dict(deterministic_category=label, receipts=groups.get(key, []))
                        for key, label in sorted(active.items())})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm', required=True, type=Path)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    episodes = {e.uid: e for e in load_episode_set('hm3d_v2', 'val', args.dataset.resolve())}
    lock = json.loads((args.arm / 'baseline-lock.json').read_text())
    pinned = lock['inputs']['detector']['recipe']
    taxonomy_path = Path(pinned['taxonomy_path'])
    if digest(taxonomy_path) != pinned['taxonomy_sha256']:
        raise ValueError('taxonomy hash differs from run')
    taxonomy = Taxonomy.load(taxonomy_path)
    labels = {number: name for name, number in HydraLabelRasterizer(taxonomy).class_to_label.items()}
    goals = GoalCategories.load(Path(lock['inputs']['detector']['mapping']['path']))
    args.out.mkdir(parents=True, exist_ok=False)
    requests, unavailable = [], []
    for line in (args.arm / 'trajectories.jsonl').open():
        row = json.loads(line)
        uid, spec = row['uid'], episodes[row['uid']]
        policy = row['diagnostics'].get('policy') or {}
        status = (policy.get('semantic_candidates') or {}).get('native_tap') or {}
        closed = status.get('native') or {}
        if not status.get('clean_shutdown') or not closed.get('manifest_path'):
            unavailable.append(dict(uid=uid, reason='native cutoff unavailable'))
            continue
        source = Path(closed['manifest_path'])
        if digest(source) != closed['manifest_sha256']:
            raise ValueError('native manifest checksum mismatch')
        export = json.loads(source.read_text())
        ident = f'episode-{len(requests):04d}'
        destination = args.out / ident
        destination.mkdir()
        case = capture_episode(uid, source.parents[1], export, labels, destination, taxonomy)
        scene = Path(spec.scene_path)
        semantic = scene.with_name(scene.name.replace('.basis.glb', '.semantic.glb'))
        annotation = semantic.with_suffix('.txt')
        dataset = Path(spec.eval_dataset_config)
        target = spec.object_category
        labels_for_goal = goals.labels[target]
        case.update(directory=ident, scene=spec.scene_short,
                    target_category=target if target in labels_for_goal else labels_for_goal[0],
                    depth_bounds=[lock['inputs']['runner_config']['sensor']['primary'][key]
                                  for key in ('depth_min_m', 'depth_max_m')],
                    assets={key: dict(path=str(path), sha256=digest(path)) for key, path in
                            [('scene', scene), ('semantic', semantic), ('annotation', annotation), ('dataset', dataset)]})
        requests.append(case)
    save_json(args.out / 'request.json', dict(schema_version=1, taxonomy=str(taxonomy_path),
              taxonomy_sha256=pinned['taxonomy_sha256'], cases=requests, unavailable=unavailable))


if __name__ == '__main__':
    main()
