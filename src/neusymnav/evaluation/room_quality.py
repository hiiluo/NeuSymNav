"""Offline observed-support room geometry metrics.

Human room annotations are evaluator inputs only. This module is not imported
by runtime code and never turns room labels into native geometry or IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping

from ..contracts._base import digest, finite, integer, text


@dataclass(frozen=True)
class RoomSupportSnapshot:
    episode_id: str
    run_id: str
    graph_revision: int
    frame_convention: str
    observed_support: Mapping[str, tuple[float, float, float]]
    support_domain: str
    room_assignments: Mapping[str, str | None]
    unassigned: tuple[str, ...]
    source_hashes: Mapping[str, str]

    def __post_init__(self):
        text(self.episode_id, 'episode_id'); text(self.run_id, 'run_id')
        integer(self.graph_revision, 'graph_revision')
        if self.frame_convention != 'canonical_z_up_m_v1':
            raise ValueError('unsupported room support frame convention')
        if self.support_domain not in {'place_points', 'surface_points', 'floor_cells'}:
            raise ValueError('unsupported room support domain')
        support = {}
        for support_id, point in self.observed_support.items():
            text(support_id, 'support id')
            point = tuple(finite(value, 'support coordinate') for value in point)
            if len(point) != 3:
                raise ValueError('observed support points must be XYZ')
            support[support_id] = point
        assignments = {}
        for support_id, room_id in self.room_assignments.items():
            text(support_id, 'assignment support id')
            if support_id not in support:
                raise ValueError('room assignment references support absent from observed support')
            if room_id is not None:
                text(room_id, 'room id')
            assignments[support_id] = room_id
        unassigned = tuple(self.unassigned)
        if any(not isinstance(item, str) or item not in support for item in unassigned):
            raise ValueError('unassigned support must reference observed support IDs')
        if set(unassigned) != {key for key, room_id in assignments.items() if room_id is None}:
            raise ValueError('unassigned list must match null room assignments')
        hashes = {}
        for name, value in self.source_hashes.items():
            text(name, 'source hash name'); digest(value, f'source_hashes.{name}')
            hashes[name] = value
        if not hashes:
            raise ValueError('at least one source SHA-256 is required')
        object.__setattr__(self, 'observed_support', MappingProxyType(support))
        object.__setattr__(self, 'room_assignments', MappingProxyType(assignments))
        object.__setattr__(self, 'unassigned', unassigned)
        object.__setattr__(self, 'source_hashes', MappingProxyType(hashes))


@dataclass(frozen=True)
class RoomQualityReport:
    status: str
    protocol: str
    support_count: int
    annotation_coverage: float | None
    metrics: Mapping[str, float | int | None]
    unavailable: Mapping[str, str]
    reasons: tuple[str, ...]

    def __post_init__(self):
        if self.status not in {'available', 'unavailable'}:
            raise ValueError('invalid report status')
        object.__setattr__(self, 'metrics', MappingProxyType(dict(self.metrics)))
        object.__setattr__(self, 'unavailable', MappingProxyType(dict(self.unavailable)))
        object.__setattr__(self, 'reasons', tuple(self.reasons))

    def to_dict(self):
        return {'schema_version': 1, 'status': self.status, 'protocol': self.protocol,
                'support_count': self.support_count, 'annotation_coverage': self.annotation_coverage,
                'metrics': dict(self.metrics), 'unavailable': dict(self.unavailable),
                'reasons': list(self.reasons)}


_METRIC_NAMES = ('adjusted_rand_index', 'pairwise_precision', 'pairwise_recall', 'pairwise_f1',
                 'purity', 'best_match_mean_iou', 'merge_count', 'split_count',
                 'boundary_f1_020m', 'boundary_f1_010m', 'boundary_f1_030m',
                 'temporal_geometry_consistency', 'room_id_churn')


def _unavailable(protocol, reason, *, support_count=0, coverage=None):
    metrics = {name: None for name in _METRIC_NAMES}
    reasons = {name: reason for name in _METRIC_NAMES}
    return RoomQualityReport('unavailable', protocol, support_count, coverage,
        metrics, reasons, (reason,))


def evaluate_room_geometry(pred: RoomSupportSnapshot, annotation: Mapping | None, *,
                           protocol: str) -> RoomQualityReport:
    """Score partitions only on independently annotated shared support IDs."""
    if not isinstance(pred, RoomSupportSnapshot):
        raise TypeError('pred must be RoomSupportSnapshot')
    text(protocol, 'protocol')
    if annotation is None:
        return _unavailable(protocol, 'annotation_missing')
    if not isinstance(annotation, Mapping):
        raise TypeError('annotation must be a mapping or None')
    required = {'schema_version', 'annotation_version', 'support_domain',
                'annotated', 'assignments', 'provenance', 'episode_id', 'run_id',
                'graph_revision', 'graph_sha256'}
    if set(annotation) != required:
        raise ValueError('room annotation fields mismatch')
    if type(annotation['schema_version']) is not int or annotation['schema_version'] != 1:
        raise ValueError('unsupported room annotation schema')
    text(annotation['annotation_version'], 'annotation_version')
    text(annotation['provenance'], 'provenance')
    if (annotation['episode_id'] != pred.episode_id or annotation['run_id'] != pred.run_id
            or type(annotation['graph_revision']) is not int
            or annotation['graph_revision'] != pred.graph_revision):
        return _unavailable(protocol, 'annotation_graph_revision_mismatch')
    digest(annotation['graph_sha256'], 'annotation graph_sha256')
    if annotation['graph_sha256'] != pred.source_hashes.get('graph'):
        return _unavailable(protocol, 'annotation_graph_hash_mismatch')
    if type(annotation['annotated']) is not bool:
        raise ValueError('annotated must be bool')
    if not annotation['annotated']:
        return _unavailable(protocol, 'annotation_not_complete')
    if annotation['support_domain'] != pred.support_domain:
        return _unavailable(protocol, 'support_domain_mismatch')
    gt = annotation['assignments']
    if not isinstance(gt, Mapping):
        raise ValueError('annotation assignments must be a mapping')
    for support_id, room_id in gt.items():
        text(support_id, 'annotation support id')
        if room_id is not None:
            text(room_id, 'annotation room ID')
    shared = sorted(set(gt) & set(pred.room_assignments))
    compared = [(pred.room_assignments[key], gt[key]) for key in shared
                if pred.room_assignments[key] is not None and gt[key] is not None]
    coverage = len(compared) / max(1, len(gt))
    if not compared:
        return _unavailable(protocol, 'no_common_annotated_support', coverage=coverage)

    from collections import Counter
    pred_labels = sorted({left for left, _ in compared})
    gt_labels = sorted({right for _, right in compared})
    counts = Counter(compared)
    table = [[counts[(p, g)] for g in gt_labels] for p in pred_labels]
    n = len(compared)
    row_sums = [sum(row) for row in table]
    col_sums = [sum(table[i][j] for i in range(len(table))) for j in range(len(gt_labels))]
    choose2 = lambda value: value * (value - 1) / 2
    index = sum(choose2(cell) for row in table for cell in row)
    row_pairs, col_pairs = sum(map(choose2, row_sums)), sum(map(choose2, col_sums))
    total_pairs = choose2(n)
    expected = row_pairs * col_pairs / total_pairs if total_pairs else 0.
    maximum = .5 * (row_pairs + col_pairs)
    ari = 1.0 if not total_pairs else (
        1.0 if maximum == expected and index == expected else
        (index - expected) / (maximum - expected) if maximum != expected else 0.)
    tp = index; fp = row_pairs - tp; fn = col_pairs - tp
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    pairwise_f1 = (2 * precision * recall / (precision + recall)
                   if precision is not None and recall is not None and precision + recall else None)
    purity = sum(max(row, default=0) for row in table) / n
    from scipy.optimize import linear_sum_assignment
    import numpy as np
    iou = np.zeros((len(pred_labels), len(gt_labels)), dtype=float)
    for i, row in enumerate(table):
        for j, intersection in enumerate(row):
            union = row_sums[i] + col_sums[j] - intersection
            iou[i, j] = intersection / union if union else 0.
    pred_idx, gt_idx = linear_sum_assignment(-iou)
    best_match = float(iou[pred_idx, gt_idx].mean()) if len(pred_idx) else None
    merge_count = sum(sum(value > 0 for value in row) > 1 for row in table)
    split_count = sum(sum(table[i][j] > 0 for i in range(len(pred_labels))) > 1
                      for j in range(len(gt_labels)))
    metrics = {'adjusted_rand_index': float(ari), 'pairwise_precision': precision,
        'pairwise_recall': recall, 'pairwise_f1': pairwise_f1, 'purity': float(purity),
        'best_match_mean_iou': best_match, 'merge_count': int(merge_count),
        'split_count': int(split_count), 'boundary_f1_020m': None,
        'boundary_f1_010m': None, 'boundary_f1_030m': None,
        'temporal_geometry_consistency': None, 'room_id_churn': None}
    unavailable = {name: 'point support does not define a room boundary'
                   for name in ('boundary_f1_020m', 'boundary_f1_010m', 'boundary_f1_030m')}
    unavailable['temporal_geometry_consistency'] = 'single graph revision has no temporal sequence'
    unavailable['room_id_churn'] = 'requires at least two accepted graph revisions'
    return RoomQualityReport('available', protocol, n, coverage, metrics,
        unavailable, ('observed_support_only',))
