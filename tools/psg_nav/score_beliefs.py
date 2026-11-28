#!/usr/bin/env python3
"""Score offline, independently matched categorical beliefs (schema version 1).

Each row is one visible GT instance at an exact scene/episode/revision cutoff.
Ranks map retrieval method names to one-based ranks, or null for no hit. Missing
rank fields mean the retrieval experiment was not recorded, not a failed hit.
Optional observation_keys are ordered, unique contribution identifiers; repeated
rows permit a prefix-continuity diagnostic, not proof of correct vote content.
No assumption is made that rows at different revisions are independent samples.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

EPSILON = 1e-12
STATUSES = {'matched', 'unmatched', 'unresolved', 'out_of_domain'}
REQUIRED = {'scene', 'episode', 'revision', 'instance', 'gt_category', 'status',
            'native_id', 'deterministic_category', 'probabilities'}
OPTIONAL = {'observation_count', 'target_category', 'retrieval_ranks', 'observation_keys'}


def _ratio(n, d):
    return n / d if d else None


def _string(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'schema_version', 'categories', 'rows'} or type(payload['schema_version']) is not int or payload['schema_version'] != 1:
        raise ValueError('expected schema version 1 with categories and rows')
    categories, rows = payload['categories'], payload['rows']
    if not isinstance(categories, list) or not categories or any(not _string(c) for c in categories) or len(set(categories)) != len(categories):
        raise ValueError('categories must be unique nonempty canonical strings')
    if not isinstance(rows, list):
        raise ValueError('rows must be a list')
    domain = set(categories)
    seen_gt, seen_native = set(), set()
    for row in rows:
        if not isinstance(row, dict) or not REQUIRED <= row.keys() or row.keys() - REQUIRED - OPTIONAL:
            raise ValueError('row fields do not match schema')
        if not _string(row['scene']) or not _string(row['episode']) or type(row['revision']) is not int or row['revision'] < 0:
            raise ValueError('invalid scope identity')
        status = row['status']
        if not _string(status) or status not in STATUSES:
            raise ValueError('invalid status')
        for field in ('instance', 'native_id'):
            if row[field] is not None and not _string(row[field]):
                raise ValueError('invalid identity')
        scope = (row['scene'], row['episode'], row['revision'])
        for field, seen in (('instance', seen_gt), ('native_id', seen_native)):
            if row[field] is not None:
                key = (*scope, row[field])
                if key in seen:
                    raise ValueError('duplicate assignment')
                seen.add(key)
        if status == 'matched' and (row['instance'] is None or row['native_id'] is None):
            raise ValueError('matched rows require both identities')
        if status != 'matched' and row['probabilities'] is not None:
            raise ValueError('belief requires a matched instance')
        if status == 'unmatched' and row['native_id'] is not None:
            raise ValueError('unmatched row cannot assign native identity')
        gt = row['gt_category']
        if status in ('matched', 'unmatched') and (row['instance'] is None or not _string(gt) or gt not in domain):
            raise ValueError('eligible rows require in-domain GT and instance')
        if status == 'out_of_domain' and (not _string(gt) or gt in domain):
            raise ValueError('out_of_domain requires an external category')
        if status == 'unresolved' and gt is not None and (not _string(gt) or gt not in domain):
            raise ValueError('invalid unresolved category')
        if row['deterministic_category'] is not None and (not _string(row['deterministic_category']) or row['deterministic_category'] not in domain):
            raise ValueError('invalid deterministic category')
        if status != 'matched' and row['deterministic_category'] is not None:
            raise ValueError('deterministic output requires a match')
        probs = row['probabilities']
        if probs is not None:
            if not isinstance(probs, dict) or not probs or any(k not in domain or isinstance(v, bool) or not isinstance(v, (float, int)) or not 0 <= v <= 1 or not math.isfinite(v) for k, v in probs.items()) or not math.isclose(sum(probs.values()), 1.0, rel_tol=0, abs_tol=1e-9):
                raise ValueError('invalid probability distribution')
        if 'observation_count' in row and (type(row['observation_count']) is not int or row['observation_count'] < 0):
            raise ValueError('invalid observation count')
        if 'target_category' in row and (not _string(row['target_category']) or row['target_category'] not in domain or (status in ('matched', 'unmatched') and row['target_category'] != gt)):
            raise ValueError('invalid target category for instance')
        if 'observation_keys' in row:
            keys = row['observation_keys']
            if status != 'matched' or not isinstance(keys, list) or any(not _string(k) for k in keys) or len(set(keys)) != len(keys) or ('observation_count' in row and row['observation_count'] != len(keys)):
                raise ValueError('invalid ordered observation keys')
        if 'retrieval_ranks' in row:
            ranks = row['retrieval_ranks']
            if 'target_category' not in row or not isinstance(ranks, dict) or not ranks or any(not _string(k) or (v is not None and (type(v) is not int or v < 1)) for k, v in ranks.items()):
                raise ValueError('invalid retrieval ranks')
    return categories, rows


def score(payload):
    categories, rows = _validate(payload)
    eligible = [r for r in rows if r['status'] in ('matched', 'unmatched')]
    matched = [r for r in eligible if r['status'] == 'matched']
    available = [r for r in matched if r['probabilities'] is not None]
    n, a = len(eligible), len(available)
    hits = Counter()
    brier = clipped = raw = 0.0
    zero = 0
    bins = [{'lower': i / 10, 'upper': (i + 1) / 10, 'count': 0, 'confidence': None, 'accuracy': None} for i in range(10)]
    bin_conf, bin_correct = [0.0] * 10, [0] * 10
    per_class = {c: {'eligible': 0, 'available': 0, 'top1_correct': 0} for c in categories}
    for r in eligible:
        per_class[r['gt_category']]['eligible'] += 1
    for r in available:
        p = r['probabilities']
        order = sorted(categories, key=lambda c: (-p.get(c, 0), c))
        gt = r['gt_category']
        hit = order[0] == gt
        hits[1] += hit
        hits[3] += gt in order[:3]
        per_class[gt]['available'] += 1
        per_class[gt]['top1_correct'] += hit
        truth = p.get(gt, 0)
        zero += truth == 0
        if truth:
            raw -= math.log(truth)
        clipped -= math.log(max(EPSILON, truth))
        brier += sum((p.get(c, 0) - (c == gt)) ** 2 for c in categories)
        confidence = p.get(order[0], 0)
        i = min(9, int(confidence * 10))
        bins[i]['count'] += 1
        bin_conf[i] += confidence
        bin_correct[i] += hit
    ece = 0.0
    for i, bin_ in enumerate(bins):
        count = bin_['count']
        if count:
            bin_['confidence'] = bin_conf[i] / count
            bin_['accuracy'] = bin_correct[i] / count
            ece += count * abs(bin_['accuracy'] - bin_['confidence'])
    for value in per_class.values():
        value['top1_all_visible'] = _ratio(value['top1_correct'], value['eligible'])
        value['top1_available'] = _ratio(value['top1_correct'], value['available'])
    det = [r for r in matched if r['deterministic_category'] is not None]
    correct = sum(r['deterministic_category'] == r['gt_category'] for r in det)
    methods = sorted({method for r in eligible for method in r.get('retrieval_ranks', {})})
    retrieval = {}
    for method in methods:
        recorded = [r for r in eligible if method in r.get('retrieval_ranks', {})]
        linked = [r for r in recorded if r['status'] == 'matched']
        metrics = {}
        for k in (1, 3):
            hits_all = sum(r['retrieval_ranks'][method] is not None and r['retrieval_ranks'][method] <= k for r in recorded)
            hits_linked = sum(r['retrieval_ranks'][method] is not None and r['retrieval_ranks'][method] <= k for r in linked)
            metrics[f'recall_at_{k}'] = {'hits': hits_all, 'all_visible': _ratio(hits_all, n), 'recorded': _ratio(hits_all, len(recorded)), 'linked': _ratio(hits_linked, len(matched)), 'linked_recorded': _ratio(hits_linked, len(linked))}
        retrieval[method] = {'eligible_visible': n, 'recorded': len(recorded), 'coverage': _ratio(len(recorded), n), 'linked': len(linked), **metrics}
    histories = {}
    for row in rows:
        if 'observation_keys' in row:
            key = (row['scene'], row['episode'], row['instance'])
            histories.setdefault(key, []).append(row)
    comparisons = violations = 0
    for history in histories.values():
        history.sort(key=lambda r: r['revision'])
        for earlier, later in zip(history, history[1:]):
            comparisons += 1
            previous, current = earlier['observation_keys'], later['observation_keys']
            violations += current[:len(previous)] != previous
    counts = Counter(r['status'] for r in rows)
    return {
        'schema_version': 1,
        'counts': {'rows': len(rows), **{s: counts[s] for s in sorted(STATUSES)}, 'eligible_visible': n, 'available': a, 'unavailable_distribution': len(matched) - a},
        'belief': {
            **{f'top{k}': {'correct': hits[k], 'all_visible': _ratio(hits[k], n), 'available': _ratio(hits[k], a)} for k in (1, 3)},
            'nll': {'denominator': a, 'raw_mean': None if not a or zero else raw / a, 'raw_infinite': bool(zero), 'zero_truth_count': zero, 'epsilon': EPSILON, 'clipped_mean': _ratio(clipped, a)},
            'brier': _ratio(brier, a),
            'ece': {'value': _ratio(ece, a), 'bins': bins},
            'per_class': per_class,
        },
        'deterministic': {'correct': correct, 'available': len(det), 'coverage': _ratio(len(det), n), 'accuracy_all_visible': _ratio(correct, n), 'accuracy_available': _ratio(correct, len(det))},
        'retrieval': {'available': bool(methods), 'methods': retrieval},
        'persistence': {'available': bool(comparisons), 'comparisons': comparisons, 'prefix_violations': violations, 'reason': None if comparisons else 'no repeated rows with ordered observation keys'},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        result = score(json.loads(args.input.read_text(encoding='utf-8')))
        output = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n'
        if args.out:
            args.out.write_text(output, encoding='utf-8')
        else:
            print(output, end='')
    except (ValueError, OSError) as exc:
        parser.exit(2, f'error: {exc}\n')


if __name__ == '__main__':
    main()
