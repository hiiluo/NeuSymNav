"""Offline, scoped diagnostic oracles. Never import into the control path."""
from collections import Counter
from copy import deepcopy
from statistics import mean, stdev
import math

import numpy as np
from scipy.optimize import linear_sum_assignment

from neusymnav.evaluation.graph_admission import _iou


def oracle_frame(gt, pred, threshold=.5):
    """One-to-one geometry-only matches; no unmatched row or mask is removed.

    Oracle ID is an evaluation namespace, not a canonical runtime object ID.
    """
    if not 0 < threshold <= 1:
        raise ValueError('invalid IoU threshold')
    scores = np.array([[_iou(p['box'], g['box']) for g in gt] for p in pred]).reshape(len(pred), len(gt))
    eligible = scores >= threshold
    pairs = []
    if len(pred) and len(gt):
        rows, cols = linear_sum_assignment(-(eligible * (min(len(pred), len(gt)) + 1 + scores)))
        pairs = [(int(i), int(j)) for i, j in zip(rows, cols) if eligible[i, j]]
    labels, identities = deepcopy(pred), deepcopy(pred)
    for i, j in pairs:
        labels[i]['label'] = gt[j]['label']
        identities[i]['id'] = 'oracle:' + gt[j]['id']
    return {'matches': len(pairs), 'fn': len(gt)-len(pairs), 'unmatched_predictions': len(pred)-len(pairs),
            'pairs': pairs, 'label': labels, 'identity': identities}


def promotion(rows):
    """Validate frozen proposed paired gates; missing evidence never passes."""
    required = ('scene', 'start', 'exhaustive', 'heldout', 'b_ids', 'r_ids', 'c_ids', 'b_precision', 'r_precision', 'b_false_merges', 'r_false_merges', 'b_free', 'r_free', 'reobserve_fraction', 'b_p95', 'r_p95', 'safety_ok', 'resources_ok')
    if not rows or any(any(k not in r or r[k] is None for k in required) for r in rows):
        return {'status': 'unavailable', 'reason': 'missing paired evidence'}
    keys = {(r['scene'], r['start']) for r in rows}
    if len(keys) != len(rows) or len(rows) < 9 or len({r['scene'] for r in rows}) < 3 or any(sum(r['scene'] == scene for r in rows) < 3 for scene in {r['scene'] for r in rows}) or not all(r['exhaustive'] is True and r['heldout'] is True for r in rows):
        return {'status': 'unavailable', 'reason': 'requires exhaustive GT and at least nine distinct pairs from three held-out scenes'}
    numeric = ('b_ids', 'r_ids', 'c_ids', 'b_precision', 'r_precision', 'b_false_merges', 'r_false_merges', 'b_free', 'r_free', 'reobserve_fraction', 'b_p95', 'r_p95')
    if any(any(isinstance(r[k], bool) or not isinstance(r[k], (int, float)) or not math.isfinite(r[k]) or r[k] < 0 for k in numeric) or r['b_free'] <= 0 or r['b_p95'] <= 0 or r['b_precision'] > 1 or r['r_precision'] > 1 or r['reobserve_fraction'] > 1 for r in rows):
        return {'status': 'unavailable', 'reason': 'invalid baseline denominator'}
    b = mean(r['b_ids'] for r in rows); gain = mean(r['r_ids']-r['b_ids'] for r in rows)
    gates = {'identity_gain': gain >= 1 and gain >= .2*b,
             'precision': mean(r['r_precision']-r['b_precision'] for r in rows) >= -.02,
             'false_merge': sum(r['r_false_merges'] for r in rows) <= sum(r['b_false_merges'] for r in rows),
             'free_area': all(r['r_free'] >= .9*r['b_free'] for r in rows),
             'reobserve_time': all(r['reobserve_fraction'] <= .2 for r in rows),
             'latency': all(r['r_p95'] <= 1.1*r['b_p95'] for r in rows),
             'safety_resources': all(r['safety_ok'] is True and r['resources_ok'] is True for r in rows),
             'control_c': mean(r['r_ids']-r['c_ids'] for r in rows) > 0}
    return {'status': 'passed' if all(gates.values()) else 'not_passed', 'gates': gates,
            'paired_identity_differences': [r['r_ids']-r['b_ids'] for r in rows],
            'paired_difference_sd': stdev(r['r_ids']-r['b_ids'] for r in rows),
            'uncertainty': 'Paired sample SD is descriptive; nine pairs do not establish broad generalization.'}


def evaluate_retained(gt_doc, prediction_doc, replay):
    if gt_doc['binding'] != prediction_doc['binding']:
        raise ValueError('GT and prediction binding mismatch')
    gt_frames = gt_doc['frames']; pred_by = {f['frame_id']: f for f in prediction_doc['frames']}
    replay_by = {f['frame_id']: f for f in replay['frames']}
    if len(pred_by) != len(prediction_doc['frames']) or len(replay_by) != len(replay['frames']):
        raise ValueError('duplicate frame')
    counts = {stage: Counter() for stage in ('detections', 'projected_off', 'projected_policy')}
    ids = {stage: set() for stage in counts}
    edges = {stage: Counter() for stage in counts}
    confusion = Counter(); edge_pred = {}; edge_gt = {}
    for frame in gt_frames:
        fid = frame['frame_id']; pframe = pred_by[fid]; rf = replay_by[fid]
        for key in ('capture_monotonic_ns', 'source_sha256', 'geometry_hash', 'height', 'width'):
            if frame[key] != pframe[key]: raise ValueError('frame binding mismatch: ' + key)
        if frame['capture_monotonic_ns'] != rf['capture_monotonic_ns'] or not frame['annotated'] or pframe['status'] != 'complete':
            raise ValueError('replay frame mismatch or incomplete')
        gt = [{'id': o['id'], 'label': o['label'], 'box': o['bbox']} for o in frame['objects']]
        detections = [{'id': o.get('identity') or ('unassigned:' + fid + ':' + o['id']), 'label': o['label'], 'box': o['bbox'], 'mask': o['mask']} for o in pframe['objects']]
        projected = rf['projected_objects']
        selected = [p for p in projected if rf['decisions'].get(p['id'], {}).get('state') == 'admitted']
        for stage, pred in (('detections', detections), ('projected_off', projected), ('projected_policy', selected)):
            result = oracle_frame(gt, pred)
            c = counts[stage]; c['gt_observations'] += len(gt); c['predictions'] += len(pred); c['matched_observations'] += result['matches']; c['unmatched_predictions_unknown_scope'] += result['unmatched_predictions']; c['unmatched_gt'] += result['fn']
            for i, j in result['pairs']:
                ids[stage].add(gt[j]['id']); edges[stage][(pred[i]['id'], gt[j]['id'])] += 1; c['label_correct'] += pred[i]['label'] == gt[j]['label']
                if stage == 'detections':
                    confusion[(pred[i]['label'], gt[j]['label'])] += 1
                    edge_pred.setdefault(pred[i]['id'], set()).add(gt[j]['id'])
                    edge_gt.setdefault(gt[j]['id'], set()).add(pred[i]['id'])
    for stage, links in edges.items():
        ps = sorted({p for p, _ in links}); gs = sorted({g for _, g in links})
        weights = np.array([[links[p, g] for g in gs] for p in ps]).reshape(len(ps), len(gs))
        if len(ps) and len(gs):
            valid = weights > 0
            rr, cc = linear_sum_assignment(-(valid * (weights.sum() + 1) + weights))
            counts[stage]['global_one_to_one_identities'] = int(sum(valid[i, j] for i, j in zip(rr, cc)))
        else:
            counts[stage]['global_one_to_one_identities'] = 0
    all_ids = {o['id'] for f in gt_frames for o in f['objects']}
    return {'schema': 'active-perception-retained-diagnostic-v1', 'frames': len(gt_frames), 'gt_identities': len(all_ids),
            'stages': {k: {**v, 'matched_gt_identities': len(ids[k])} for k, v in counts.items()},
            'detection_label_confusions': [{'predicted': a, 'gt': b, 'count': n} for (a,b), n in sorted(confusion.items()) if a != b],
            'detection_identity_diagnostics': {'pred_ids_matching_multiple_gt': sum(len(v)>1 for v in edge_pred.values()), 'gt_ids_matching_multiple_pred': sum(len(v)>1 for v in edge_gt.values())},
            'oracle_label': {'matched_label_correct_before': counts['detections']['label_correct'], 'matched_label_correct_after': counts['detections']['matched_observations'], 'note': 'post hoc replacement; geometry and matching unchanged; no pipeline rerun'},
            'oracle_id': {'global_one_to_one_before': counts['detections']['global_one_to_one_identities'], 'global_one_to_one_after': len(ids['detections']), 'note': 'post hoc matched IDs only; unmatched predictions retained; no association rerun'},
            'oracle_mask': {'status': 'unavailable', 'reason': 'requires GT-mask proposals, real projection/association and re-extraction of appearance from same RGB/mask recipe'},
            'precision': None, 'promotion': promotion([]),
            'limitations': ['Partial taxonomy and >=100 pixel GT; unmatched predictions have unknown scope, not certified FP.', 'Stages are independently matched; counts do not prove causal attrition.', 'Projected off/policy replay uses simulated capture clock; async appearance attachments are not reconstructed.', 'Oracles are diagnostic interventions, not deployable performance and their gains cannot be added.', 'Single development scene; no held-out scene or exhaustive GT.']}
