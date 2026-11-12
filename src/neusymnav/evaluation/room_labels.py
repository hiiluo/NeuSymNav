"""Conservative, versioned symbolic comparator for room-label proposals."""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import statistics

from ..contracts.room_semantics import RoomLabelProposal
from ..contracts.room_semantics import ROOM_LABELS
from ..rooms.requests import RoomLabelRequest


RULE_BASELINE_VERSION = 'room-label-rules-v1'
RULE_GROUPS = {
    'bathroom': frozenset({'toilet', 'bathtub'}),
    'bedroom': frozenset({'bed'}),
    'kitchen': frozenset({'oven', 'fridge', 'microwave'}),
    'living_room': frozenset({'sofa'}),
}


def evaluate_room_label_pilot(rows, *, model_version: str) -> dict:
    """Score one selected context per annotated physical room.

    Input rows join frozen annotations and prediction records. Historical
    revisions may be included with ``selected=False``; they contribute only
    to distinct-context flip counts, never to the sample denominator.
    """
    if not isinstance(model_version, str) or not model_version.strip():
        raise ValueError('model_version is required')
    rows = list(rows)
    by_room = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            raise TypeError('evaluation rows must be objects')
        room = row.get('physical_room_id')
        scene = row.get('scene_id')
        context = row.get('context_hash')
        if not all(isinstance(value, str) and value for value in (room, scene, context)):
            raise ValueError('physical room, scene and context identity are required')
        labels = row.get('reference_labels')
        if not isinstance(labels, list) or any(label not in ROOM_LABELS for label in labels):
            raise ValueError('reference_labels must be a list of canonical labels')
        if len(set(labels)) != len(labels):
            raise ValueError('reference labels must be distinct')
        by_room[room].append(row)

    selected = []
    skipped = Counter()
    revision_prediction_count = 0
    flips = 0
    geometry_unavailable = 0
    invalid_count = 0
    latencies = []
    rss_values = []
    for room, candidates in sorted(by_room.items()):
        contexts = {}
        for row in candidates:
            contexts.setdefault(row['context_hash'], row)
        ordered = [contexts[key] for key in sorted(contexts)]
        revision_prediction_count += len(ordered)
        labels_seen = [row.get('label', 'unknown') for row in ordered]
        flips += sum(a != b for a, b in zip(labels_seen, labels_seen[1:]))
        chosen = [row for row in candidates if row.get('selected', True)]
        if len(chosen) != 1:
            raise ValueError(f'physical room {room} must have exactly one selected context')
        row = chosen[0]
        if row.get('geometry_status') != 'available':
            geometry_unavailable += 1
        if not row.get('eligible', False):
            skipped[row.get('skip_reason') or 'not_eligible'] += 1
            continue
        if not row['reference_labels']:
            skipped[row.get('skip_reason') or 'missing_human_reference'] += 1
            continue
        selected.append(row)
        if row.get('status') == 'invalid':
            invalid_count += 1
        value = row.get('latency_ms')
        if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
            latencies.append(float(value))
        value = row.get('peak_rss_bytes')
        if isinstance(value, int) and value >= 0:
            rss_values.append(value)

    eligible_semantic = [row for row in selected if row.get('geometry_status') == 'available']
    supported = [row for row in eligible_semantic
        if row.get('status') in {'available', 'proposed'}
        and row.get('label') in ROOM_LABELS and row.get('label') != 'unknown']
    confusion = {label: {} for label in sorted(ROOM_LABELS)}
    per_label = {}
    for row in supported:
        pred = row['label']
        for truth in row['reference_labels']:
            confusion[truth][pred] = confusion[truth].get(pred, 0) + 1
    for label in sorted(ROOM_LABELS - {'unknown'}):
        tp = sum(1 for row in supported if label in row['reference_labels'] and row['label'] == label)
        fp = sum(1 for row in supported if label not in row['reference_labels'] and row['label'] == label)
        fn = sum(1 for row in eligible_semantic if label in row['reference_labels'] and row not in supported)
        fn += sum(1 for row in supported if label in row['reference_labels'] and row['label'] != label)
        denom = 2 * tp + fp + fn
        if denom:
            per_label[label] = {'precision': tp / (tp + fp) if tp + fp else 0.0,
                'recall': tp / (tp + fn) if tp + fn else 0.0,
                'f1': 2 * tp / denom}
    macro_f1 = statistics.mean(value['f1'] for value in per_label.values()) if per_label else None
    correct = sum(row['label'] in row['reference_labels'] for row in supported)
    hallucinated = 0
    support_total = 0
    for row in supported:
        support = row.get('supporting_object_ids', [])
        assigned = row.get('assigned_object_ids')
        if not isinstance(support, list):
            raise ValueError('supporting_object_ids must be a list')
        support_total += len(support)
        if assigned is not None:
            if not isinstance(assigned, list):
                raise ValueError('assigned_object_ids must be a list')
            hallucinated += sum(value not in assigned for value in support)
    scene_counts = Counter(row['scene_id'] for row in selected)
    p50 = statistics.median(latencies) if latencies else None
    p95 = sorted(latencies)[max(0, math.ceil(.95 * len(latencies)) - 1)] if latencies else None
    return {'schema_version': 1, 'model_version': model_version,
        'physical_room_count': len(selected), 'scored_room_count': len(eligible_semantic),
        'supported_count': len(supported), 'abstention_count': len(eligible_semantic)-len(supported),
        'coverage': len(supported)/len(eligible_semantic) if eligible_semantic else None,
        'selective_accuracy': correct/len(supported) if supported else None,
        'labelset_supported_macro_f1': macro_f1, 'per_label': per_label,
        'confusion': confusion, 'multi_label_reference_count': sum(len(x['reference_labels'])>1 for x in eligible_semantic),
        'invalid_count': invalid_count,
        'invalid_rate': invalid_count/len(selected) if selected else None,
        'hallucinated_support_count': hallucinated,
        'hallucinated_support_rate': hallucinated/support_total if support_total else None,
        'revision_prediction_count': revision_prediction_count, 'flip_count': flips,
        'geometry_unavailable_count': geometry_unavailable,
        'skipped_reasons': dict(sorted(skipped.items())),
        'per_scene': {scene:{'physical_room_count':count} for scene,count in sorted(scene_counts.items())},
        'latency_ms': {'p50':p50,'p95':p95,'max':max(latencies) if latencies else None},
        'peak_rss_bytes_max': max(rss_values) if rss_values else None}


def rule_baseline(request: RoomLabelRequest) -> RoomLabelProposal:
    if not isinstance(request, RoomLabelRequest):
        raise TypeError('request must be RoomLabelRequest')
    blocked = request.inference_block_reason
    if blocked:
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
            request.key.context_hash, 'unknown', (), (), 'insufficient_evidence', blocked,
            None, None)
    labels = {}
    for row in request.context.objects:
        if row.membership_status != 'assigned':
            continue
        for label, categories in RULE_GROUPS.items():
            if row.category in categories:
                labels.setdefault(label, []).append(row.native_id)
    if not labels:
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
            request.key.context_hash, 'unknown', (), (), 'insufficient_evidence',
            'no_explicit_room_anchor', None, None)
    if len(labels) > 1:
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
            request.key.context_hash, 'unknown', (), (), 'unknown',
            'contradictory_room_anchors:' + ','.join(sorted(labels)), None, None)
    label, ids = next(iter(sorted(labels.items())))
    return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
        request.key.context_hash, label, (), tuple(sorted(set(ids))[:8]), 'proposed',
        f'explicit_object_anchor:{label}:{RULE_BASELINE_VERSION}', None, None)
