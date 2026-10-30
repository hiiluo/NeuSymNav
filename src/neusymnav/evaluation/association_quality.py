"""Offline identity metrics and diagnostics from annotated spatial observations.

Inputs contain visible GT only, ordered by annotated source frame. Labels and
confidence never select matches. Pairwise scores are conditional on geometric
matches and must not replace end-to-end IDF1 (which includes every FP and miss).
No runtime module or simulator semantic ground truth is imported here.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import math
from numbers import Real

from .instance_metrics import match_instances
from .metrics import ratio, unavailable


def _string(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    return value


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f'{name} must be a finite number')
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f'{name} must be a finite number') from exc
    if not math.isfinite(normalized):
        raise ValueError(f'{name} must be a finite number')
    return normalized


def _sequence(value, name):
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f'{name} must be a sequence')
    return value


def _box(value):
    values = _sequence(value, 'bbox')
    if len(values) != 4:
        raise ValueError('bbox must have four coordinates')
    x1, y1, x2, y2 = (_number(x, 'bbox coordinate') for x in values)
    area = (x2-x1)*(y2-y1)
    if x2 <= x1 or y2 <= y1 or not math.isfinite(area) or area <= 0:
        raise ValueError('bbox requires finite positive area and ordered bounds')
    return x1, y1, x2, y2


def _iou(first, second):
    intersection = max(0., min(first[2], second[2])-max(first[0], second[0])) * max(
        0., min(first[3], second[3])-max(first[1], second[1]))
    # Scaling before addition avoids overflow for otherwise finite box areas.
    area1 = (first[2]-first[0])*(first[3]-first[1])
    area2 = (second[2]-second[0])*(second[3]-second[1])
    union = area1 + area2 - intersection
    if math.isfinite(union):
        return intersection/union
    scale = max(area1, area2)
    exponent = math.frexp(scale)[1]
    a,b,i = (math.ldexp(value,-exponent) for value in (area1,area2,intersection))
    return i/(a+b-i)


def _aliases(value):
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError('final aliases must be a mapping')
    aliases = {_string(key, 'alias source'): _string(target, 'alias target')
               for key, target in value.items()}
    resolved = {}
    # Validate the whole mapping, including components unused by observations.
    # A terminal may be absent from observations; final IDs can have no own view.
    for source in aliases:
        path, visited = [], set()
        current = source
        while current in aliases and current not in resolved:
            if current in visited:
                raise ValueError('final alias mapping contains a cycle')
            visited.add(current)
            path.append(current)
            current = aliases[current]
        terminal = resolved.get(current, current)
        for node in path:
            resolved[node] = terminal
    return resolved


def _prepare(frames, threshold):
    prepared, frame_ids, observation_ids = [], set(), set()
    missing_identity = False
    duplicates = 0
    for frame in _sequence(frames, 'frames'):
        if not isinstance(frame, Mapping):
            raise ValueError('frame must be a mapping')
        key = _string(frame.get('frame_id'), 'frame_id')
        if key in frame_ids:
            raise ValueError('frame IDs must be unique')
        frame_ids.add(key)
        groups = {}
        for kind in ('gt', 'pred'):
            items, ids, identities = [], set(), set()
            for item in _sequence(frame.get(kind), kind):
                if not isinstance(item, Mapping):
                    raise ValueError(f'{kind} observation must be a mapping')
                identity = _string(item.get('id'), f'{kind} id')
                if identity in ids or (kind == 'pred' and identity in observation_ids):
                    raise ValueError(f'{kind} observation IDs must be unique')
                ids.add(identity)
                if not isinstance(item.get('label'), str):
                    raise ValueError('label must be a string')
                normalized = dict(id=identity, bbox=_box(item.get('bbox')))
                if kind == 'pred':
                    observation_ids.add(identity)
                    score = _number(item.get('score'), 'score')
                    if not 0 <= score <= 1:
                        raise ValueError('score must be in [0, 1]')
                    track = item.get('identity')
                    if track is None:
                        missing_identity = True
                    else:
                        track = _string(track, 'predicted identity')
                        if track in identities:
                            raise ValueError('predicted identities within a frame must be unique')
                        identities.add(track)
                    normalized['identity'] = track
                items.append(normalized)
            groups[kind] = items
        gt, pred = groups['gt'], groups['pred']
        scores = [[_iou(p['bbox'], g['bbox']) for g in gt] for p in pred]
        matching = match_instances([p['id'] for p in pred], [g['id'] for g in gt],
                                  scores, minimum_score=threshold)
        duplicates += len(matching.duplicate_prediction_ids)
        prepared.append(dict(frame_id=key, gt=[g['id'] for g in gt], pred=pred,
                             eligible=[(p['id'], g['id']) for i, p in enumerate(pred)
                                       for j, g in enumerate(gt) if scores[i][j] >= threshold],
                             matches=[(m.predicted_id, m.ground_truth_id) for m in matching.matches]))
    return prepared, missing_identity, duplicates


def _count(value, support, scope):
    return dict(value=value, support=support, support_name=scope, reason=None)


def _choose2(value):
    return value*(value-1)//2


def _global_idf1(prepared, aliases):
    """Assign trajectories using all eligible pair/frame opportunities.

    TrackEval Identity.eval_sequence accumulates threshold-eligible spatial
    pair counts before global assignment, rather than pruning them with local
    matching: https://github.com/JonathonLuiten/TrackEval/blob/master/trackeval/metrics/identity.py
    Minimizing its global IDFP+IDFN costs is equivalent to maximizing these
    counts, since total predicted/GT observations are fixed. Final alias
    collisions contribute at most one opportunity per canonical-ID/GT/frame;
    every underlying prediction observation still counts in the denominator.
    """
    opportunities = Counter()
    predicted_ids, gt_ids = {}, {}
    total_predicted = total_gt = 0
    for frame in prepared:
        observations = {p['id']: aliases.get(p['identity'], p['identity']) for p in frame['pred']}
        predicted_ids.update(dict.fromkeys(observations.values()))
        gt_ids.update(dict.fromkeys(frame['gt']))
        total_predicted += len(frame['pred'])
        total_gt += len(frame['gt'])
        opportunities.update({(observations[observation], gt) for observation, gt in frame['eligible']})
    assignment = match_instances(list(predicted_ids), list(gt_ids),
        [[opportunities[predicted, gt] for gt in gt_ids] for predicted in predicted_ids],
        minimum_score=1.)
    idtp = sum(int(match.score) for match in assignment.matches)
    idfp, idfn = total_predicted-idtp, total_gt-idtp
    return dict(ratio(2*idtp, total_predicted+total_gt,
                     denominator_name='2*IDTP + IDFP + IDFN'),
                idtp=idtp, idfp=idfp, idfn=idfn)


def _evaluate(prepared, aliases, revisit_gap, duplicate_rate):
    matched_pairs, history = [], {}
    switches = fragments = transitions = revisits = recovered = 0
    canonical = lambda identity: aliases.get(identity, identity)
    for index, frame in enumerate(prepared):
        observations = {p['id']: canonical(p['identity']) for p in frame['pred']}
        pairs = [(observations[observation], gt) for observation, gt in frame['matches']]
        matched_pairs.extend(pairs)
        matched_by_gt = {gt: identity for identity, gt in pairs}
        for gt in frame['gt']:
            current = matched_by_gt.get(gt)
            previous = history.get(gt)
            contiguous = previous is not None and previous['seen'] == index-1
            if not contiguous:
                if previous is not None and index-previous['seen']-1 >= revisit_gap and previous['visible_match'] is not None:
                    revisits += 1
                    recovered += current is not None and current == previous['visible_match']
                previous = dict(last_match=None, missed=False)
            if current is not None:
                if previous['last_match'] is not None:
                    transitions += 1
                    switches += current != previous['last_match']
                    fragments += previous['missed']
                previous.update(last_match=current, missed=False)
            elif previous['last_match'] is not None:
                previous['missed'] = True
            previous.update(seen=index, visible_match=current)
            history[gt] = previous
    idf1 = _global_idf1(prepared, aliases)
    pred_counts = Counter(p for p, _ in matched_pairs)
    gt_counts = Counter(g for _, g in matched_pairs)
    pair_counts = Counter(matched_pairs)
    correct = sum(_choose2(count) for count in pair_counts.values())
    predicted_same = sum(_choose2(count) for count in pred_counts.values())
    actual_same = sum(_choose2(count) for count in gt_counts.values())
    return dict(available=True, reason=None, idf1=idf1,
        pairwise_precision=ratio(correct, predicted_same, denominator_name='same-predicted-identity pairs of geometrically matched observations'),
        pairwise_recall=ratio(correct, actual_same, denominator_name='same-GT-identity pairs of geometrically matched observations'),
        false_merge_pairs=_count(predicted_same-correct, predicted_same, 'predicted-same matched-observation pairs'),
        split_pairs=_count(actual_same-correct, actual_same, 'GT-same matched-observation pairs'),
        id_switches=_count(switches, transitions, 'successive matched observations within continuous GT visibility episodes'),
        fragments=_count(fragments, transitions, 'successive matched observations within continuous GT visibility episodes'),
        duplicate_rate=dict(duplicate_rate),
        revisit_recovery=ratio(recovered, revisits, denominator_name='first reappearances after sufficient annotated absence whose last pre-absence visible observation was matched'))


def evaluate_association(frames, *, iou_threshold=0.5, revisit_gap_frames=2,
                         final_aliases=None) -> dict:
    """Evaluate online IDs and, when supplied, final canonical IDs separately.

    ``frames`` is a sequence ordered by annotated source time. Each contains
    ``frame_id``, visible ``gt`` instances, and ``pred`` observations. Boxes are
    [x1,y1,x2,y2] in a common frame; GT ``id`` persists over time, prediction
    ``id`` is globally unique, and prediction ``identity`` persists over time.
    Missing identity makes identity metrics unavailable, retaining detection
    support. An explicitly empty alias mapping requests final metrics unchanged.
    """
    threshold = _number(iou_threshold, 'iou_threshold')
    if not 0 < threshold <= 1:
        raise ValueError('iou_threshold must be in (0, 1]')
    if type(revisit_gap_frames) is not int or revisit_gap_frames < 1:
        raise ValueError('revisit_gap_frames must be a positive integer')
    aliases = _aliases(final_aliases)
    prepared, missing, duplicates = _prepare(frames, threshold)
    prediction_count = sum(len(frame['pred']) for frame in prepared)
    duplicate_rate = ratio(duplicates, prediction_count,
                           denominator_name='all predicted observation instances')
    reason = 'missing predicted identity; detection-only observations cannot establish association' if missing else None
    online = dict(available=False, **unavailable(reason)) if missing else _evaluate(prepared, {}, revisit_gap_frames, duplicate_rate)
    final_reason = reason if missing else 'final aliases not supplied; online identities only'
    final = dict(available=False, **unavailable(final_reason)) if missing or aliases is None else _evaluate(prepared, aliases, revisit_gap_frames, duplicate_rate)
    optional_reason = 'official HOTA/AssA algorithm not implemented; these diagnostics are not HOTA/AssA'
    return dict(available=not missing, reason=reason,
        protocol=dict(matching='label-independent maximum-total-IoU Hungarian bbox matching',
            idf1_matching='all threshold-eligible spatial track/GT pairs accumulated by frame, then global maximum-count one-to-one trajectory assignment; no local matching pruning',
            iou_threshold=threshold, revisit_gap_frames=revisit_gap_frames,
            pairwise_scope='conditional on geometrically matched observations only; misses and FPs remain in IDF1',
            id_switch_policy='compare successive matched observations within continuous GT visibility; visible detection misses retain last matched identity; any annotated GT absence resets comparison',
            fragment_policy='matched-to-unmatched-to-matched within continuous GT visibility; any annotated GT absence resets fragment state',
            revisit_policy='annotated absence count, not source frame index difference; test first reappearance only; last visible observation before absence must be matched; first reappearance miss is a failure',
            alias_policy='online IDs untouched; final aliases transitively resolve all components; cycles rejected including unused; unseen terminal IDs allowed; simultaneous collapsed observations retained'),
        support=dict(frames=len(prepared), gt_observations=sum(len(frame['gt']) for frame in prepared),
            predicted_observations=prediction_count, matched_observations=sum(len(frame['matches']) for frame in prepared),
            unique_gt_ids=len({gt for frame in prepared for gt in frame['gt']}),
            unique_online_ids=len({p['identity'] for frame in prepared for p in frame['pred'] if p['identity'] is not None}),
            duplicate_predictions=duplicates),
        duplicate_rate=duplicate_rate, online=online, final_canonicalized=final,
        hota=unavailable(optional_reason), assa=unavailable(optional_reason))
