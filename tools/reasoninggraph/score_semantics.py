"""Offline directed-pair evaluator; annotations never enter inference inputs."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _index(rows, required, optional=()):
    if not isinstance(rows, list):
        raise ValueError('rows must be a list')
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not set(required) <= row.keys() or row.keys() - set(required) - set(optional):
            raise ValueError('invalid row fields')
        key = row['id']
        if not isinstance(key, str) or not key or key in result:
            raise ValueError('invalid or duplicate id')
        result[key] = row
    return result


def _ratio(a, b):
    return a / b if b else None


def score(manifest, oracle, arm):
    if set(manifest) != {'schema_version', 'samples'} or manifest['schema_version'] != 1:
        raise ValueError('invalid manifest')
    samples = _index(manifest['samples'], ('id', 'scene', 'subject', 'object', 'predicate', 'input_sha256'))
    if not samples:
        raise ValueError('empty manifest')
    for row in samples.values():
        if any(not isinstance(v, str) or not v for v in row.values()) or row['subject'] == row['object'] or len(row['input_sha256']) != 64 or any(c not in '0123456789abcdef' for c in row['input_sha256']):
            raise ValueError('invalid sample identity')
    if set(oracle) != {'manifest_sha256', 'labels'} or set(arm) != {'manifest_sha256', 'arm', 'predictions'} or not isinstance(arm['arm'], str) or not arm['arm']:
        raise ValueError('invalid oracle or arm')
    pin = digest(manifest)
    if oracle['manifest_sha256'] != pin or arm['manifest_sha256'] != pin:
        raise ValueError('manifest mismatch')
    labels = _index(oracle['labels'], ('id', 'label'))
    predictions = _index(arm['predictions'], ('id', 'input_sha256', 'prediction'))
    if set(labels) != set(samples) or not set(predictions) <= set(samples):
        raise ValueError('sample set mismatch')
    if any(r['label'] not in {'positive', 'negative', 'unknown'} for r in labels.values()):
        raise ValueError('invalid reference')
    for key, row in predictions.items():
        if row['input_sha256'] != samples[key]['input_sha256'] or row['prediction'] not in {'positive', 'negative', 'unknown', 'abstain', 'error'}:
            raise ValueError('invalid prediction or input mismatch')
    rows = [{'id': key, 'predicate': sample['predicate'], 'label': labels[key]['label'], 'prediction': predictions[key]['prediction'] if key in predictions else 'missing'} for key, sample in samples.items()]
    counts, metrics = _summarize(rows)
    per_predicate = {p: dict(zip(('counts', 'metrics'), _summarize([r for r in rows if r['predicate'] == p]))) for p in sorted({r['predicate'] for r in rows})}
    f1s = [v['metrics']['f1'] for v in per_predicate.values() if v['metrics']['f1'] is not None]
    metrics['macro_f1'] = sum(f1s) / len(f1s) if f1s else None
    return {'schema_version': 1, 'manifest_sha256': pin, 'oracle_sha256': digest(oracle), 'arm': arm['arm'], 'counts': counts, 'metrics': metrics, 'per_predicate': per_predicate, 'rows': rows}


def _summarize(rows):
    c = Counter({k: 0 for k in ('total', 'known', 'unknown_reference', 'answered_known', 'abstain', 'unknown_prediction', 'error', 'missing', 'tp', 'fp', 'fn', 'tn')})
    positives = 0
    for r in rows:
        c['total'] += 1
        label, pred = r['label'], r['prediction']
        if pred in {'abstain', 'error', 'missing'}: c[pred] += 1
        if pred == 'unknown': c['unknown_prediction'] += 1
        if label == 'unknown':
            c['unknown_reference'] += 1
            continue
        c['known'] += 1
        positives += label == 'positive'
        if pred in {'positive', 'negative'}:
            c['answered_known'] += 1
            c[{('positive', 'positive'): 'tp', ('negative', 'positive'): 'fp', ('positive', 'negative'): 'fn', ('negative', 'negative'): 'tn'}[(label, pred)]] += 1
    precision = _ratio(c['tp'], c['tp'] + c['fp'])
    recall = _ratio(c['tp'], c['tp'] + c['fn'])
    f1 = _ratio(2*c['tp'], 2*c['tp'] + c['fp'] + c['fn'])
    return dict(c), {'coverage': _ratio(c['answered_known'], c['known']), 'conditional_accuracy': _ratio(c['tp'] + c['tn'], c['answered_known']), 'precision': precision, 'recall': recall, 'f1': f1, 'end_to_end_recall': _ratio(c['tp'], positives), 'unknown_prediction_rate': _ratio(c['unknown_prediction'], c['total']), 'abstention_rate': _ratio(c['abstain'], c['total']), 'error_rate': _ratio(c['error'], c['total']), 'missing_rate': _ratio(c['missing'], c['total'])}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', required=True); p.add_argument('--oracle', required=True); p.add_argument('--arm', required=True); p.add_argument('--output', required=True)
    a = p.parse_args()
    values = [json.loads(Path(x).read_text()) for x in (a.manifest, a.oracle, a.arm)]
    Path(a.output).write_text(json.dumps(score(*values), indent=2, allow_nan=False) + '\n')

if __name__ == '__main__': main()
