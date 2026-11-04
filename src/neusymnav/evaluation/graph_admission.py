"""Offline graph presence evaluation against scoped, fixed, frame-level GT.

Input schema graph-admission-v1: provenance has frames_sha256, poses_sha256,
detector_sha256, recipe_sha256 and gt_sha256. Frames are capture-time ordered;
each has id, scene, time_s, gt and pred. GT rows have persistent scene-local id,
xyxy box, label and visibility. Predictions have persistent id, xyxy box, label
and scope (inside or unknown), decided independently of the prediction match.
GT rows are precisely the predeclared observable annotation scope; omitted GT is
not inferred. Unknown predictions are excluded from both TP and FP. Hashes are
pinned identifiers, not proof that the producer supplied truthful provenance.
The IoU threshold is inclusive and matching maximizes cardinality then IoU.
"""
from collections import defaultdict
import math
import re

import numpy as np
from scipy.optimize import linear_sum_assignment


def _box(value):
    if not isinstance(value, list) or len(value) != 4 or any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in value):
        raise ValueError('invalid box')
    x1, y1, x2, y2 = value
    if x2 <= x1 or y2 <= y1:
        raise ValueError('empty box')
    return value


def _iou(a, b):
    w = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    return inter / ((a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter)


def _ratio(a, b):
    return a / b if b else None


def evaluate(data):
    """Return observation-level metrics and object-level capture-time confirmation."""
    if not isinstance(data, dict) or data.get('schema') != 'graph-admission-v1':
        raise ValueError('unsupported schema')
    provenance = data.get('provenance', {})
    for key in ('frames_sha256', 'poses_sha256', 'detector_sha256', 'recipe_sha256', 'gt_sha256'):
        if not isinstance(provenance.get(key), str) or not re.fullmatch('[0-9a-f]{64}', provenance[key]):
            raise ValueError('missing or invalid provenance hash: ' + key)
    threshold = data.get('iou_threshold')
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError('invalid IoU threshold')
    frames = data.get('frames')
    if not isinstance(frames, list) or not frames:
        raise ValueError('frames required')
    seen_frames, last_time, first, confirmed, labels = set(), {}, {}, {}, {}
    tp = fp = fn = unknown = duplicates = merges = in_scope = label_correct = 0
    ious = []
    node_predictions, node_edges, edge_first = set(), defaultdict(int), {}
    support = defaultdict(lambda: {'gt_observations': 0, 'matched': 0})
    for frame in frames:
        scene, frame_id, time = frame.get('scene'), frame.get('id'), frame.get('time_s')
        if not isinstance(scene, str) or not scene or not isinstance(frame_id, str) or not frame_id or (scene, frame_id) in seen_frames:
            raise ValueError('invalid or repeated frame')
        if isinstance(time, bool) or not isinstance(time, (int, float)) or not math.isfinite(time) or time < 0 or time < last_time.get(scene, 0):
            raise ValueError('invalid capture time')
        seen_frames.add((scene, frame_id)); last_time[scene] = time
        gt, predictions = frame.get('gt'), frame.get('pred')
        if not isinstance(gt, list) or not isinstance(predictions, list):
            raise ValueError('gt and pred lists required')
        for rows in (gt, predictions):
            ids = set()
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id'] or row['id'] in ids or not isinstance(row.get('label'), str) or not row['label']:
                    raise ValueError('invalid or repeated object')
                ids.add(row['id']); _box(row.get('box'))
        for row in gt:
            if not isinstance(row.get('visibility'), str) or not row['visibility']:
                raise ValueError('visibility required')
            key = (scene, row['id'])
            if key in labels and labels[key] != row['label']:
                raise ValueError('GT label changes for identity')
            labels[key] = row['label']; first.setdefault(key, time)
            support[(scene, row['label'], row['visibility'])]['gt_observations'] += 1
        if any(p.get('scope') not in ('inside', 'unknown') for p in predictions):
            raise ValueError('prediction scope required')
        unknown += sum(p['scope'] == 'unknown' for p in predictions)
        pred = [p for p in predictions if p['scope'] == 'inside']
        in_scope += len(pred)
        node_predictions.update((scene, p['id']) for p in pred)
        scores = np.array([[_iou(p['box'], g['box']) for g in gt] for p in pred], dtype=float).reshape(len(pred), len(gt))
        eligible = scores >= threshold
        for i, p in enumerate(pred):
            for j, g in enumerate(gt):
                if eligible[i, j]:
                    edge = ((scene, p['id']), (scene, g['id']))
                    node_edges[edge] += 1
                    edge_first.setdefault(edge, time)
        # A cardinality bonus larger than the maximum possible IoU sum avoids
        # sacrificing a match to obtain a higher overlap on another pair.
        pairs = []
        if len(pred) and len(gt):
            rows, cols = linear_sum_assignment(-(eligible * (min(len(pred), len(gt)) + 1 + scores)))
            pairs = [(int(i), int(j)) for i, j in zip(rows, cols) if eligible[i, j]]
        matched_p = {i for i, _ in pairs}
        tp += len(pairs); fp += len(pred)-len(pairs); fn += len(gt)-len(pairs)
        duplicates += sum(bool(eligible[i].any()) for i in range(len(pred)) if i not in matched_p)
        merges += sum(int(row.sum()) >= 2 for row in eligible)
        for i, j in pairs:
            p, g = pred[i], gt[j]
            label_correct += p['label'] == g['label']; ious.append(float(scores[i, j]))
            support[(scene, g['label'], g['visibility'])]['matched'] += 1
    node_pred, node_gt = sorted(node_predictions), sorted(first)
    weights = np.zeros((len(node_pred), len(node_gt)), dtype=float)
    for i, p in enumerate(node_pred):
        for j, g in enumerate(node_gt):
            weights[i, j] = node_edges.get((p, g), 0)
    node_tp = 0
    if len(node_pred) and len(node_gt):
        # Lexicographic: maximum matched identities, then shared observations.
        valid = weights > 0
        bonus = weights.sum() + 1
        rows, cols = linear_sum_assignment(-(valid * (bonus + weights)))
        for i, j in zip(rows, cols):
            if valid[i, j]:
                node_tp += 1
                confirmed[node_gt[j]] = edge_first[(node_pred[i], node_gt[j])]
    node_fp, node_fn = len(node_pred)-node_tp, len(node_gt)-node_tp
    precision, recall = _ratio(tp, tp+fp), _ratio(tp, tp+fn)
    latencies = [confirmed[k]-t for k, t in first.items() if k in confirmed]
    return {'schema': 'graph-admission-report-v1', 'provenance': provenance, 'iou_threshold': threshold,
            'nodes': {'tp': node_tp, 'fp': node_fp, 'fn': node_fn, 'precision': _ratio(node_tp, len(node_pred)), 'recall': _ratio(node_tp, len(node_gt)), 'f1': _ratio(2*node_tp, 2*node_tp+node_fp+node_fn)},
            'presence': {'tp': tp, 'fp': fp, 'fn': fn, 'unknown': unknown, 'precision': precision, 'recall': recall, 'f1': _ratio(2*tp, 2*tp+fp+fn)},
            'duplicates': {'count': duplicates, 'denominator': in_scope, 'rate': _ratio(duplicates, in_scope)},
            'potential_false_merges': {'count': merges, 'denominator': in_scope, 'rate': _ratio(merges, in_scope)},
            'confirmation': {'eligible_objects': len(first), 'confirmed': len(latencies), 'unconfirmed': len(first)-len(latencies), 'median_s': float(np.median(latencies)) if latencies else None, 'p95_s': float(np.percentile(latencies, 95)) if latencies else None},
            'label': {'correct': int(label_correct), 'total': tp, 'accuracy': _ratio(label_correct, tp)},
            'geometry': {'matched_mean_iou': float(np.mean(ious)) if ious else None, 'matched_count': len(ious)},
            'support': [{'scene': s, 'class': c, 'visibility': v, **value} for (s, c, v), value in sorted(support.items())],
            'unsupported': {'false_merge_rate': 'overlap with multiple GT boxes is only a potential merge, not identity evidence', 'idf1_assa': 'requires identity protocol and complete temporal GT', 'flicker': 'requires explicit lifecycle and visibility protocol', 'room_assignment': 'requires scoped room GT', 'memory_time_cost': 'requires measured run telemetry'}}


def project_visible_box(points, source, *, min_points=5, depth_tolerance_m=.1):
    """Project measured points consistent with current axial depth; return xyxy."""
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
        raise ValueError('invalid world cloud')
    camera = (points - source.T_world_camera[:3, 3]) @ source.T_world_camera[:3, :3]
    camera = camera[camera[:, 2] > 0]
    if not len(camera): return None
    pixels = camera @ source.K.T
    xy = np.floor(pixels[:, :2] / pixels[:, 2, None]).astype(int)
    h, w = source.depth_m.shape
    mask = (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
    xy, camera = xy[mask], camera[mask]
    if not len(xy): return None
    x, y = xy[:, 0], xy[:, 1]
    mask = source.valid_depth[y, x] & (np.abs(source.depth_m[y, x] - camera[:, 2]) <= depth_tolerance_m)
    xy = xy[mask]
    if len(xy) < min_points: return None
    return [int(xy[:, 0].min()), int(xy[:, 1].min()), int(xy[:, 0].max()) + 1, int(xy[:, 1].max()) + 1]


def replay_owner(source_ledger, predictions_path, destination, *, label_oracle=None, batch_oracle=None):
    """Offline owner replay, optionally replacing matched detection labels only.

    The synthetic clock advances to each retained capture time. It does not
    change the original ledger or prove the events were fresh in the real run.
    """
    import json
    from dataclasses import replace
    from pathlib import Path
    from tools.replay_association_quality import _inputs
    from neusymnav.contracts.serialization import loads
    from neusymnav.evaluation.quality_dataset import _validate_document
    from neusymnav.evaluation.quality_export import _asset, _json, _read, _sha, _snapshot_connection
    from neusymnav.objects.store import ObjectOwner
    from neusymnav.objects.admission import AdmissionPolicy, committed_evidence_summary, evaluate_admission
    from neusymnav.verification.ledger import VerificationOwner

    if label_oracle is not None and batch_oracle is not None:
        raise ValueError('choose one isolated oracle')
    root, source, dest = Path(source_ledger).resolve(), Path(predictions_path).resolve(), Path(destination).absolute()
    if dest.exists() or dest.is_symlink():
        raise FileExistsError('replay destination must not exist')
    if dest.resolve().is_relative_to(root) or dest.resolve().is_relative_to(source.parent):
        raise ValueError('destination must be outside source directories')
    raw = _read(source); document = _json(raw)
    _validate_document(document, prediction=True)
    with _snapshot_connection(root) as connection:
        config, inputs, assets, _, logical_digest = _inputs(root, source, document, connection)
        batches = [loads(_asset(root, connection, meta['batch_asset'])) for meta in document['provenance']['source_metadata']]
    features = [item.appearance for _, items, _ in inputs for item in items if item.appearance is not None]
    for feature in features[1:]:
        features[0].require_compatible(feature)
    if any(inputs[i][0].capture_monotonic_ns < inputs[i-1][0].capture_monotonic_ns for i in range(1, len(inputs))):
        raise ValueError('capture order must be monotonic')
    dest.mkdir(parents=True)
    current = [0]
    clock = lambda: current[0]
    frames = []
    prior = None
    policy = AdmissionPolicy()
    owner = ObjectOwner(dest / 'owner', **config, now_ns=clock,
                        association_recipe={'mode': 'conceptgraphs'},
                        appearance_mode='openai_clip' if features else 'off')
    verifier = None
    try:
        verifier = VerificationOwner(owner, clock_domain=config['clock_domain'], now_ns=clock)
        for (observation, items, frame), batch in zip(inputs, batches):
            current[0] = observation.capture_monotonic_ns
            labels={} if label_oracle is None else label_oracle.get(frame['frame_id'],{})
            if set(labels)-{d.detection_id for d in batch.detections}:
                raise ValueError('oracle refers to detection absent from committed batch')
            if labels:
                # The matched mask, projection, score and image feature stay intact.
                batch=replace(batch,detections=tuple(replace(d,raw_label=labels[d.detection_id],category=labels[d.detection_id])
                    if d.detection_id in labels else d for d in batch.detections))
                items=tuple(replace(item,raw_label=labels[item.detection_id],category=labels[item.detection_id])
                    if item.detection_id in labels else item for item in items)
            if batch_oracle is not None:
                batch,items=batch_oracle(observation,batch,items,frame)
            commit = owner.commit(observation, batch, items)
            verifier.consume(commit)
            summary = committed_evidence_summary(owner, policy=policy)
            admission = evaluate_admission(owner.snapshot(), verifier.snapshot(), summary, prior, policy)
            prior = admission
            projected = []
            for oid, obj in owner.snapshot().objects.items():
                if obj.lifecycle in {'retired', 'merged'} or obj.points_world is None: continue
                box = project_visible_box(obj.points_world, observation)
                if box is None: continue
                row = owner.ledger.connection.execute(
                    "SELECT MAX(json_extract(data, '$.score')) FROM views WHERE object_id=?", (oid,)).fetchone()
                projected.append({'id': oid, 'box': box, 'label': obj.category or obj.raw_label,
                                  'max_detected_score': row[0]})
            frames.append({'frame_id': frame['frame_id'], 'capture_monotonic_ns': current[0],
                           'projected_objects': projected,
                           'object_revision': admission.object_revision,
                           'decisions': {oid: {'state': decision.state, 'availability': decision.availability,
                                               'reason_codes': list(decision.reason_codes)}
                                         for oid, decision in admission.decisions.items()}})
    finally:
        if verifier is not None: verifier.close()
        owner.close()
    report = {'schema': 'offline-admission-replay-v1', 'semantics': 'counterfactual simulated capture time; not original runtime freshness or graph projection',
              'original_prediction_sha256': _sha(raw), 'ledger_logical_sha256': logical_digest,
              'verified_assets': assets, 'policy_hash': policy.policy_hash, 'frames': frames,
              'feature_count': len(features), 'feature_space': features[0].space_id if features else None,
              'limitations': ['Original online freshness not reproduced.', 'Only features embedded in typed observations are replayed; later asynchronous attachments are not reconstructed.', 'Projection is an observed-depth-consistent point-cloud bounding-box proxy, not a complete visibility proof; no GT evaluation.', 'No control or runtime performance claim.']}
    if label_oracle is not None:
        report['oracle']='matched_label_only'
        report['label_overrides']=sum(len(labels) for labels in label_oracle.values())
    if batch_oracle is not None:report['oracle']='mask_and_proposal_only'
    (dest / 'replay.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report
