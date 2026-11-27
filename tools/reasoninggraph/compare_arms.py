"""Compare two prediction arms against the exact same frozen samples."""
import argparse
import json
from pathlib import Path
try:
    from .score_semantics import score
except ImportError:
    from score_semantics import score


def compare(manifest, oracle, arm_a, arm_b):
    a, b = score(manifest, oracle, arm_a), score(manifest, oracle, arm_b)
    rows_a = {r['id']: r for r in a['rows']}; rows_b = {r['id']: r for r in b['rows']}
    known = [k for k, r in rows_a.items() if r['label'] != 'unknown']
    def correct(row): return int(row['prediction'] == row['label'])
    delta = sum(correct(rows_b[k]) - correct(rows_a[k]) for k in known) / len(known) if known else None
    return {'schema_version': 1, 'manifest_sha256': a['manifest_sha256'], 'oracle_sha256': a['oracle_sha256'], 'arm_a': a, 'arm_b': b, 'paired': {'known_denominator': len(known), 'correct_delta_b_minus_a': delta}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'oracle', 'arm-a', 'arm-b', 'output'): p.add_argument('--' + name, required=True)
    a = p.parse_args()
    values = [json.loads(Path(x).read_text()) for x in (a.manifest, a.oracle, a.arm_a, a.arm_b)]
    Path(a.output).write_text(json.dumps(compare(*values), indent=2, allow_nan=False) + '\n')

if __name__ == '__main__': main()
