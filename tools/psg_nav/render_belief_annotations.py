#!/usr/bin/env python3
"""Render independent HM3D instance GT from accepted live RGB-D poses, offline only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from neusymnav.evaluation.quality_semantic_gt import (
    canonical_optical_to_habitat, extract_instances, parse_annotations, validate_alignment, validate_calibration,
)


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def checked(record, root=None):
    path = Path(record.get('path', record.get('file')))
    if root is not None:
        path = root / path
    if digest(path) != record['sha256']:
        raise ValueError('offline asset digest mismatch: ' + str(path))
    return path


def open_scene(assets, frame):
    import habitat_sim as hs

    height, width = frame['depth'].shape
    hfov = validate_calibration(frame['K'], width, height)
    cfg = hs.SimulatorConfiguration()
    cfg.scene_id = str(assets['scene'])
    cfg.scene_dataset_config_file = str(assets['dataset'])
    cfg.enable_physics = False
    cfg.load_semantic_mesh = True
    cfg.gpu_device_id = -1
    agent = hs.agent.AgentConfiguration()
    specs = []
    for label, kind in (('rgb', hs.SensorType.COLOR), ('depth', hs.SensorType.DEPTH),
                        ('semantic', hs.SensorType.SEMANTIC)):
        spec = hs.CameraSensorSpec()
        spec.uuid, spec.sensor_type = label, kind
        spec.sensor_subtype = hs.SensorSubType.PINHOLE
        spec.resolution, spec.hfov = (height, width), hfov
        spec.position, spec.orientation = [0., 0., 0.], [0., 0., 0.]
        if label == 'depth':
            spec.normalize_depth = False
        specs.append(spec)
    agent.sensor_specifications = specs
    return hs.Simulator(hs.Configuration(cfg, [agent]))


def audit_frames(case, root):
    import habitat_sim as hs
    from habitat_sim.utils.common import quat_from_coeffs
    from scipy.spatial.transform import Rotation

    assets = {label: checked(pin) for label, pin in case['assets'].items()}
    names = parse_annotations(assets['annotation'])
    raw_taxonomy = {'categories': {label.strip().casefold() for label in names.values()}}
    location = root / case['directory']
    audited, visible = {}, []
    reports = []
    with np.load(checked(case['frames'][0], location), allow_pickle=False) as first:
        simulator = open_scene(assets, first)
    try:
        agent = simulator.get_agent(0)
        for record in case['frames']:
            with np.load(checked(record, location), allow_pickle=False) as source:
                pose = canonical_optical_to_habitat(source['pose'])
                state = hs.AgentState()
                state.position = pose[:3, 3].copy()
                state.rotation = quat_from_coeffs(Rotation.from_matrix(pose[:3, :3]).as_quat())
                agent.set_state(state, reset_sensors=True)
                rendered = simulator.get_sensor_observations()
                depth = np.asarray(rendered['depth'])
                depth = np.where(depth > 0., np.clip(depth, *case['depth_bounds']), 0.)
                try:
                    alignment = validate_alignment(source['rgb'], source['depth'], source['valid'],
                                                 np.asarray(rendered['rgb'])[..., :3], depth)
                except ValueError as exc:
                    reports.append(dict(revision=record['revision'], status='unresolved', reason=str(exc)))
                    continue
                objects, excluded = extract_instances(rendered['semantic'], names, raw_taxonomy)
                report = dict(revision=record['revision'], status='aligned', alignment=alignment,
                              recognized=len(objects), excluded=excluded, receipts=[])
                for ref, mask in zip(record['receipts'], source['masks']):
                    contenders = []
                    for item in objects:
                        intersection = np.count_nonzero(mask & item['mask'])
                        if intersection:
                            contenders.append((intersection / np.count_nonzero(mask | item['mask']), item))
                    matches = [(iou, item['id']) for iou, item in contenders if iou >= .5]
                    winner = matches[0][1] if len(matches) == 1 else None
                    score = max((iou for iou, _ in contenders), default=0.)
                    audited[record['revision'], ref['detection_id']] = winner
                    report['receipts'].append(dict(detection_id=ref['detection_id'], instance=winner, best_iou=score))
                reports.append(report)
                if record['revision'] == case['revision']:
                    visible = [(item['id'], item['label']) for item in objects]
    finally:
        simulator.close()
    return audited, visible, reports


def evaluate_case(case, audited, visible, taxonomy):
    vocabulary = set(taxonomy['categories'])
    aliases = taxonomy['aliases']
    groups, claimed, ambiguous = {}, defaultdict(list), set()
    for owner, observation in case['owners'].items():
        votes = observation['receipts']
        if not votes:
            continue
        counts = Counter(v['category'] for v in votes)
        groups[owner] = {label: n / len(votes) for label, n in counts.items()}
        instances = {audited.get((v['revision'], v['detection_id'])) for v in votes}
        if len(instances) != 1 or None in instances:
            ambiguous.add(owner)
            continue
        physical = next(iter(instances))
        claimed[physical].append(owner)
    target = case['target_category']
    ranks = {
        'deterministic': {owner: i for i, owner in enumerate(sorted(k for k, v in case['owners'].items()
                         if v['deterministic_category'] == target), 1)},
        'probabilistic': {owner: i for i, owner in enumerate(
            sorted((k for k, p in groups.items() if p.get(target, 0.) > 0.),
                   key=lambda k: (-groups[k][target], k)), 1)},
    }
    base = dict(scene=case['scene'], episode=case['uid'], revision=case['revision'])
    rows = []
    for instance, label in visible:
        category = aliases.get(label, label)
        owners = claimed[instance]
        owner = owners[0] if len(owners) == 1 and category in vocabulary else None
        status = ('out_of_domain' if category not in vocabulary else 'matched' if owner is not None
                  else 'unmatched')
        row = dict(base, instance=instance, gt_category=category, status=status, native_id=owner,
                   deterministic_category=None, probabilities=None)
        if owner is not None:
            observation = case['owners'][owner]
            ordered = sorted(observation['receipts'], key=lambda vote: (vote['revision'], vote['detection_id']))
            keys = [f"{v['revision']}:{v['detection_id']}" for v in ordered]
            row.update(deterministic_category=observation['deterministic_category'],
                       probabilities=groups[owner], observation_count=len(keys), observation_keys=keys)
        if category == target:
            row.update(target_category=target, retrieval_ranks={name: values.get(owner) for name, values in ranks.items()})
        rows.append(row)
    ambiguous.update(owner for owners in claimed.values() if len(owners) > 1 for owner in owners)
    rows.extend(dict(base, instance=None, gt_category=None, status='unresolved', native_id=owner,
                     deterministic_category=None, probabilities=None) for owner in sorted(ambiguous))
    return rows


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path)
    args = parser.parse_args()
    root = args.request.parent
    request = json.loads(args.request.read_text())
    taxonomy = json.loads(checked(dict(path=request['taxonomy'], sha256=request['taxonomy_sha256'])).read_text())
    rows, audits = [], []
    for case in request['cases']:
        linked, visible, reports = audit_frames(case, root)
        rows.extend(evaluate_case(case, linked, visible, taxonomy))
        audits.append(dict(uid=case['uid'], revision=case['revision'], visible=len(visible), frames=reports))
    save(root / 'annotations.json', dict(schema_version=1, categories=taxonomy['categories'], rows=rows))
    save(root / 'mask-audit.json', dict(cases=audits, unavailable=request['unavailable']))


if __name__ == '__main__':
    main()
