"""Pure scoring of detector output against episode goal instances (phase 2).

Two passes keep memory small: ``match_frame`` turns one frame (masks in
memory) into mask-free rows, ``summarize`` aggregates the rows.

Definitions (fixed in docs/objectnav/phase2-detector-design.md):

* A goal instance is visible in a frame when it covers >= ``min_pixels``.
* Strict hit: a same-category prediction with mask IoU >= 0.5.
  Loose hit: IoU >= 0.1 (B0 needs localisation, not segmentation).
* False positive: a same-category prediction with IoU < 0.1 to every visible
  goal instance of its category AND whose dominant semantic instance is not a
  goal instance of that category (a hit on a barely visible goal is not
  counted against the detector) AND is not an *unlisted* instance of that
  category. Unlisted = an instance the episodes do not list as a goal but whose
  semantic.txt name is used for goal instances of that category elsewhere
  (e.g. a second TV the dataset filtered out). Detecting it is not a detector
  error, but stopping at it fails the episode; it is counted separately.
* Persistent false positive: the same scene instance produces false positives
  in >= 3 different frames (multi-view confirmation cannot remove it).
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np

from .categories import GoalCategories
from .masks import dominant_instance, iou

STRICT_IOU = 0.5
LOOSE_IOU = 0.1
NEAR_M = 3.0
PERSISTENT_FRAMES = 3
DISTANCE_BINS = ((0.0, 1.5), (1.5, 3.0), (3.0, 5.0), (5.0, math.inf))
THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60)


def distance_bin(depth_m: float) -> str:
    for lo, hi in DISTANCE_BINS:
        if lo <= depth_m < hi:
            return '%g-%s m' % (lo, 'inf' if math.isinf(hi) else '%g' % hi)
    return 'unknown'


def match_frame(frame: dict, ids: np.ndarray, gt_masks: Dict[int, np.ndarray], predictions: Sequence[dict],
                categories: GoalCategories, scene_goals: Dict[int, str], names: Dict[int, str],
                unlisted: Optional[Dict[int, str]] = None):
    """One frame -> (gt_rows, pred_rows). ``predictions`` carry decoded ``mask``."""
    visible = [g for g in frame['goals_visible'] if int(g['object_id']) in gt_masks]
    gt_rows = []
    for g in visible:
        gt_rows.append(dict(frame_id=frame['frame_id'], scene=frame['scene'], kind=frame['kind'],
                            episode_uid=frame.get('episode_uid'), episode_category=frame.get('episode_category'),
                            object_id=int(g['object_id']), category=g['category'], pixels=int(g['pixels']),
                            depth_m=float(g['depth_m']), cands=[], near_miss=[], other_labels={}))
    pred_rows = []
    for p in predictions:
        category = categories.goal_category(p['label'])
        dom, share = dominant_instance(ids, p['mask'])
        best = 0.0
        for row in gt_rows:
            overlap = iou(p['mask'], gt_masks[row['object_id']])
            if category == row['category']:
                best = max(best, overlap)
                if overlap > 0:
                    row['cands'].append((float(p['score']), overlap))
            elif overlap >= LOOSE_IOU:
                # what the detector calls this goal object instead (diagnostic only)
                row['other_labels'][p['label']] = max(float(p['score']), row['other_labels'].get(p['label'], 0.0))
                if categories.is_near_miss(row['category'], p['label']):
                    row['near_miss'].append((p['label'], float(p['score']), overlap))
        if category is None:
            continue
        pred_rows.append(dict(frame_id=frame['frame_id'], scene=frame['scene'], category=category,
                              label=p['label'], score=float(p['score']), best_iou=float(best),
                              dominant_id=dom, dominant_share=share,
                              dominant_is_goal=scene_goals.get(dom) == category,
                              dominant_unlisted_same=(unlisted or {}).get(dom) == category,
                              dominant_name=names.get(dom, 'background' if dom == 0 else 'unknown')))
    return gt_rows, pred_rows


def _hit(row: dict, thr: float, need: float) -> bool:
    return any(score >= thr and overlap >= need for score, overlap in row['cands'])


def _is_fp(pred: dict, thr: float) -> bool:
    return (pred['score'] >= thr and pred['best_iou'] < LOOSE_IOU and not pred['dominant_is_goal']
            and not pred.get('dominant_unlisted_same', False))


def _is_unlisted(pred: dict, thr: float) -> bool:
    return (pred['score'] >= thr and pred['best_iou'] < LOOSE_IOU and not pred['dominant_is_goal']
            and pred.get('dominant_unlisted_same', False))


def _ratio(num: float, den: float) -> Optional[float]:
    return None if den == 0 else num / den


def summarize(gt_rows: List[dict], pred_rows: List[dict], *, frames: int, scenes: Sequence[str],
              categories: Sequence[str], thresholds: Sequence[float] = THRESHOLDS) -> dict:
    by_cat_gt: Dict[str, List[dict]] = defaultdict(list)
    for row in gt_rows:
        by_cat_gt[row['category']].append(row)
    by_cat_pred: Dict[str, List[dict]] = defaultdict(list)
    for row in pred_rows:
        by_cat_pred[row['category']].append(row)
    report = dict(schema_version=1, frames=frames, scenes=list(scenes), thresholds=list(thresholds),
                  definitions=dict(strict_iou=STRICT_IOU, loose_iou=LOOSE_IOU, near_m=NEAR_M,
                                   persistent_frames=PERSISTENT_FRAMES), categories={})
    for cat in categories:
        gts, preds = by_cat_gt.get(cat, []), by_cat_pred.get(cat, [])
        instances: Dict[tuple, List[dict]] = defaultdict(list)
        for row in gts:
            if row['depth_m'] <= NEAR_M:
                instances[(row['scene'], row['object_id'])].append(row)
        episodes: Dict[str, List[dict]] = defaultdict(list)
        for row in gts:
            if row['kind'] == 'path' and row['episode_category'] == cat and row['depth_m'] <= NEAR_M:
                episodes[row['episode_uid']].append(row)
        curve = []
        for thr in thresholds:
            above = [p for p in preds if p['score'] >= thr]
            fps = [p for p in above if _is_fp(p, thr)]
            tp_preds = [p for p in above if p['best_iou'] >= STRICT_IOU]
            fp_frames: Dict[tuple, set] = defaultdict(set)
            for p in fps:
                if p['dominant_id']:
                    fp_frames[(p['scene'], p['dominant_id'])].add(p['frame_id'])
            persistent = {k: len(v) for k, v in fp_frames.items() if len(v) >= PERSISTENT_FRAMES}
            bins = {}
            for lo, hi in DISTANCE_BINS:
                rows = [r for r in gts if lo <= r['depth_m'] < hi]
                name = distance_bin(lo)
                bins[name] = dict(visible=len(rows),
                                  recall_loose=_ratio(sum(_hit(r, thr, LOOSE_IOU) for r in rows), len(rows)),
                                  recall_strict=_ratio(sum(_hit(r, thr, STRICT_IOU) for r in rows), len(rows)))
            inst_hits = [sum(_hit(r, thr, LOOSE_IOU) for r in rows) for rows in instances.values()]
            curve.append(dict(
                threshold=thr,
                recall_loose=_ratio(sum(_hit(r, thr, LOOSE_IOU) for r in gts), len(gts)),
                recall_strict=_ratio(sum(_hit(r, thr, STRICT_IOU) for r in gts), len(gts)),
                precision_strict=_ratio(len(tp_preds), len(above)),
                predictions=len(above), false_positives=len(fps),
                unlisted_same_category=sum(1 for p in above if _is_unlisted(p, thr)),
                fp_per_100_frames=100.0 * len(fps) / frames if frames else None,
                persistent_fp_instances=len(persistent),
                persistent_fp_per_scene=len(persistent) / len(scenes) if scenes else None,
                instance_recall_1=_ratio(sum(h >= 1 for h in inst_hits), len(inst_hits)),
                instance_recall_3=_ratio(sum(h >= 3 for h in inst_hits), len(inst_hits)),
                episode_ceiling=_ratio(sum(any(_hit(r, thr, LOOSE_IOU) for r in rows) for rows in episodes.values()),
                                       len(episodes)),
                by_distance=bins))
        ok = [c for c in curve if c['persistent_fp_per_scene'] is not None and c['persistent_fp_per_scene'] <= 1.0]
        chosen = min(ok, key=lambda c: c['threshold']) if ok else None
        fp_names: Dict[str, int] = defaultdict(int)
        if chosen is not None:
            for p in preds:
                if _is_fp(p, chosen['threshold']):
                    fp_names[p['dominant_name']] += 1
        near = defaultdict(int)
        for row in gts:
            for label, _, _ in row['near_miss']:
                near[label] += 1
        # For goal objects MISSED at the runtime threshold 0.25: what the detector said instead.
        instead: Dict[str, int] = defaultdict(int)
        missed = [r for r in gts if not _hit(r, 0.25, LOOSE_IOU)]
        for row in missed:
            for label, score in row.get('other_labels', {}).items():
                if score >= 0.25:
                    instead[label] += 1
        report['categories'][cat] = dict(
            visible_instances_frames=len(gts), instances_within_3m=len(instances),
            path_episodes_with_view_within_3m=len(episodes), curve=curve,
            recommended_threshold=None if chosen is None else chosen['threshold'],
            recommended_rule='lowest threshold with <= 1 persistent false-positive instance per scene',
            top_false_positive_sources=dict(sorted(fp_names.items(), key=lambda kv: -kv[1])[:10]),
            near_miss_labels=dict(near),
            missed_at_0_25=len(missed),
            labels_on_missed_at_0_25=dict(sorted(instead.items(), key=lambda kv: -kv[1])[:10]))
    picks = [c['recommended_threshold'] for c in report['categories'].values() if c['recommended_threshold'] is not None]
    report['global_threshold'] = max(picks) if picks else None
    return report


def markdown(report: dict) -> str:
    out = ['# Phase 2 detector report', '',
           'Frames: %d, scenes: %s' % (report['frames'], ', '.join(report['scenes'])), '',
           '| Category | Rec. threshold | Recall loose | Recall strict | Precision strict | FP/100 frames | Persistent FP/scene | Inst. recall >=1 (<=3 m) | Episode ceiling |',
           '|---|---|---|---|---|---|---|---|---|']
    fmt = lambda v: '—' if v is None else ('%.2f' % v)
    for cat, block in report['categories'].items():
        thr = block['recommended_threshold']
        row = next((c for c in block['curve'] if c['threshold'] == thr), None) if thr is not None else None
        if row is None:
            out.append('| %s | none | | | | | | | |' % cat)
            continue
        out.append('| %s | %.2f | %s | %s | %s | %s | %s | %s | %s |' % (
            cat, thr, fmt(row['recall_loose']), fmt(row['recall_strict']), fmt(row['precision_strict']),
            fmt(row['fp_per_100_frames']), fmt(row['persistent_fp_per_scene']), fmt(row['instance_recall_1']),
            fmt(row['episode_ceiling'])))
    out += ['', 'Global threshold (max of per-category picks): %s' % report.get('global_threshold'), '']
    for cat, block in report['categories'].items():
        out += ['## %s' % cat, '',
                '| Threshold | Recall loose | ' + ' | '.join(b for b in block['curve'][0]['by_distance']) +
                ' | FP/100 | Persistent FP/scene |',
                '|---|---|' + '---|' * len(block['curve'][0]['by_distance']) + '---|---|']
        for c in block['curve']:
            out.append('| %.2f | %s | %s | %s | %s |' % (
                c['threshold'], fmt(c['recall_loose']),
                ' | '.join(fmt(b['recall_loose']) for b in c['by_distance'].values()),
                fmt(c['fp_per_100_frames']), fmt(c['persistent_fp_per_scene'])))
        out += ['', 'Top false-positive sources at the recommended threshold: %s' % (block['top_false_positive_sources'] or '—'),
                'Near-miss labels on goal instances: %s' % (block['near_miss_labels'] or '—'),
                'Goal views missed at 0.25: %d; what the detector said instead (score >= 0.25): %s' % (
                    block.get('missed_at_0_25', 0), block.get('labels_on_missed_at_0_25') or '—'),
                'Detections on unlisted same-category objects at 0.25: %s' % next(
                    (c['unlisted_same_category'] for c in block['curve'] if c['threshold'] == 0.25), '—'), '']
    return '\n'.join(out) + '\n'


def confirmation_table(gt_rows: List[dict], pred_rows: List[dict], *, scenes: Sequence[str],
                       categories: Sequence[str], thresholds: Sequence[float] = (0.25, 0.35, 0.5),
                       min_views: Sequence[int] = (1, 2, 3), min_share: float = 0.3) -> List[dict]:
    """Instance-level view of a B0 confirmation rule.

    A prediction is attributed to the scene instance covering >= ``min_share``
    of its mask. An instance is *confirmed* as category C at threshold t when
    >= N distinct frames predict C on it; with ``vote`` C must also be the most
    frequent goal category predicted on that instance. Confirmed goal instances
    of C are true confirmations; confirmed non-goal, non-unlisted instances are
    wrong confirmations (each one is a place where B0 could STOP wrongly).
    Recall denominator: goal instances visible within NEAR_M in any frame.
    """
    visible: Dict[str, set] = defaultdict(set)
    for row in gt_rows:
        if row['depth_m'] <= NEAR_M:
            visible[row['category']].add((row['scene'], row['object_id']))
    rows = []
    for thr in thresholds:
        frames: Dict[tuple, Dict[str, set]] = defaultdict(lambda: defaultdict(set))
        status: Dict[tuple, Dict[str, str]] = defaultdict(dict)
        for p in pred_rows:
            if p['score'] < thr or not p['dominant_id'] or p['dominant_share'] < min_share:
                continue
            inst = (p['scene'], p['dominant_id'])
            frames[inst][p['category']].add(p['frame_id'])
            status[inst][p['category']] = ('goal' if p['dominant_is_goal'] else
                                           'unlisted' if p.get('dominant_unlisted_same') else 'wrong')
        for n in min_views:
            for vote in (False, True):
                row = dict(threshold=thr, min_views=n, vote=vote, categories={})
                for cat in categories:
                    good = bad = 0
                    for inst, per_cat in frames.items():
                        count = len(per_cat.get(cat, ()))
                        if count < n or (vote and count < max(len(v) for v in per_cat.values())):
                            continue
                        kind = status[inst].get(cat)
                        good += kind == 'goal'
                        bad += kind == 'wrong'
                    row['categories'][cat] = dict(confirmed_goal_instances=good, goal_instances=len(visible[cat]),
                                                  recall=_ratio(good, len(visible[cat])),
                                                  wrong_instances_per_scene=bad / len(scenes) if scenes else None)
                rows.append(row)
    return rows


def confirmation_markdown(rows: List[dict], categories: Sequence[str]) -> str:
    fmt = lambda v: '—' if v is None else ('%.2f' % v)
    out = ['## Instance-level confirmation rule (B0)', '',
           'Cell = confirmed goal instances / goal instances visible within 3 m (recall), then wrong confirmed instances per scene.', '',
           '| Threshold | Min views | Vote | ' + ' | '.join(categories) + ' |',
           '|---|---|---|' + '---|' * len(categories)]
    for r in rows:
        cells = []
        for c in categories:
            b = r['categories'][c]
            cells.append('%d/%d (%s), %s' % (b['confirmed_goal_instances'], b['goal_instances'], fmt(b['recall']),
                                             fmt(b['wrong_instances_per_scene'])))
        out.append('| %.2f | %d | %s | %s |' % (r['threshold'], r['min_views'], 'yes' if r['vote'] else 'no', ' | '.join(cells)))
    return '\n'.join(out) + '\n'
