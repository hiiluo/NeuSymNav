#!/usr/bin/env python3
"""Score exact-revision native links against independent instance annotations."""
import argparse
import hashlib
import json
from pathlib import Path


def _rows(report):
    if report.get('schema_version') != 1:
        raise ValueError('expected a v1 evidence report')
    candidates = {}
    seen_revisions = set()
    for record in report['records']:
        revision = record['revision']
        if type(revision) is not int or revision < 1 or revision in seen_revisions:
            raise ValueError('invalid or duplicate native revision')
        seen_revisions.add(revision)
        endpoints = frozenset(record['native_endpoints'])
        for link in record['links']:
            key = revision, link['detection_id']
            if key in candidates:
                raise ValueError('duplicate detector instance within native revision')
            endpoint = link['endpoint']
            native_id = None if endpoint is None else endpoint['native_id']
            if ((link['status'] == 'geometric_candidate') != (native_id is not None)
                    or (native_id is not None and native_id not in endpoints)):
                raise ValueError('evidence endpoint is not in native revision')
            candidates[key] = (native_id, endpoints)
    return candidates


def score_links(report, labels):
    rows = _rows(report)
    annotations = {}
    for label in labels:
        key = label['revision'], label['detection_id']
        if key not in rows:
            raise ValueError('annotation names unknown detection')
        if key in annotations:
            raise ValueError('duplicate annotation')
        status, native_id = label['status'], label['native_id']
        if status == 'matched':
            if native_id not in rows[key][1]:
                raise ValueError('annotation endpoint is not in native revision')
        elif status not in {'no_endpoint', 'unresolved'} or native_id is not None:
            raise ValueError('invalid annotation status or endpoint')
        annotations[key] = status, native_id

    proposed = correct = incorrect = unresolved = labeled = matched = 0
    for key, (native_id, _) in rows.items():
        status, expected = annotations.get(key, ('unresolved', None))
        labeled += status != 'unresolved'
        matched += status == 'matched'
        if native_id is None:
            continue
        proposed += 1
        if status == 'unresolved':
            unresolved += 1
        elif status == 'matched' and native_id == expected:
            correct += 1
        else:
            incorrect += 1
    adjudicated = correct + incorrect
    return dict(pairs=len(rows), labeled=labeled, proposed=proposed, correct_proposed=correct,
                false_proposed=incorrect, unresolved_proposed=unresolved,
                annotation_coverage=labeled/len(rows) if rows else None,
                false_link_rate_adjudicated=incorrect/adjudicated if adjudicated else None,
                false_link_rate_bounds=[incorrect/proposed, (incorrect+unresolved)/proposed] if proposed else None,
                correct_match_coverage=correct/matched if matched else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    parser.add_argument('--annotations', type=Path, help='omit to create a blank annotation template')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    report = json.loads(raw)
    if args.annotations:
        annotation = json.loads(args.annotations.read_bytes())
        if annotation.get('schema_version') != 1 or annotation.get('report_sha256') != checksum:
            raise ValueError('annotations do not match the frozen report')
        result = {'schema_version': 1, 'report_sha256': checksum,
                  **score_links(report, annotation['labels'])}
    else:
        result = {'schema_version': 1, 'report_sha256': checksum, 'labels': [
            dict(revision=revision, detection_id=detection, status='unresolved', native_id=None)
            for revision, detection in sorted(_rows(report))]}
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write('\n')


if __name__ == '__main__':
    main()
