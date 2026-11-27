#!/usr/bin/env python3
"""Run a fixed-denominator image-space left-of pilot on sealed ReplayReader frames."""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import time

from neusymnav.contracts.hydra_evidence import ObservationEvidence
from neusymnav.contracts.hydra_graph import HydraReadToken
from neusymnav.contracts.observations import FrameKey
from neusymnav.contracts.reasoninggraph import DetectionGeometry, GraphReadToken
from neusymnav.reasoninggraph.evidence import evidence_matches_token
from neusymnav.reasoninggraph.pair_selection import select_pairs
from neusymnav.reasoninggraph.relation_image import PROMPT_POLICIES, ask_image_left_of, marked_pair_jpeg
from neusymnav.recording.replay import ReplayReader
from neusymnav.rooms.slm_backend import RoomSlmBackendConfig
from neusymnav.rooms.vlm_backend import RoomVlmBackend


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def write(path, payload):
    path.write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')


def token_and_detections(record):
    raw = record['token']
    token = GraphReadToken(**{**raw, 'native': HydraReadToken(**raw['native']),
                              'source': FrameKey(**raw['source'])})
    items = []
    for row in record['evidence']:
        ref = row['evidence']
        evidence = ObservationEvidence(**{**ref, 'source': FrameKey(**ref['source'])})
        items.append(DetectionGeometry(**{**row, 'evidence': evidence}))
    return token, items


def reviewed_endpoints(args, report_sha256):
    if args.review is None:
        return None
    payload = args.review.read_bytes()
    if sha(payload) != args.review_sha256:
        raise ValueError('unexpected review digest')
    review = json.loads(payload)
    if review['report_sha256'] != report_sha256:
        raise ValueError('review names a different probe report')
    endpoints = {}
    for row in review['labels']:
        if row['status'] == 'matched':
            key = row['revision'], row['detection_id']
            if key in endpoints:
                raise ValueError('duplicate reviewed endpoint')
            endpoints[key] = row['native_id']
    return endpoints


def bound_endpoints(record, token, reviewed):
    if reviewed is None:
        return None
    endpoints = {}
    for link in record['links']:
        detection = link['detection_id']
        native_id = reviewed.get((token.native.graph_revision, detection))
        endpoint = link['endpoint']
        if (native_id is not None and link['status'] == 'geometric_candidate'
                and endpoint is not None and endpoint['native_id'] == native_id and endpoint['layer_id'] == 2
                and endpoint['token'] == record['token']['native'] and link['token'] == record['token']
                and native_id in record['native_endpoints']):
            endpoints[detection] = native_id
    return endpoints


def prepared_cases(args):
    payload = args.report.read_bytes()
    if sha(payload) != args.report_sha256:
        raise ValueError('unexpected probe report digest')
    reviewed = reviewed_endpoints(args, args.report_sha256)
    records = {}
    for row in json.loads(payload)['records']:
        if row['exact_class_raster']:
            token, items = token_and_detections(row)
            if token.source in records or token.native.graph_revision != row['revision']:
                raise ValueError('duplicate or inconsistent replay revision')
            records[token.source] = token, items, bound_endpoints(row, token, reviewed)
    cases = []
    for frame in ReplayReader(args.recording).source_frames():
        if frame.key not in records:
            continue
        token, items, endpoints = records.pop(frame.key)
        if (frame.capture_monotonic_ns, frame.clock_domain, frame.calibration_id,
                frame.geometry_hash, frame.pose_version) != (
                token.capture_monotonic_ns, token.clock_domain, token.calibration_id,
                token.source_geometry_hash, token.pose_version):
            raise ValueError('recording provenance differs from accepted evidence')
        for item in items:
            ref = item.evidence
            x0, y0, x1, y1 = ref.bbox_xyxy
            if (not evidence_matches_token(item, token)
                    or sha(frame.rgb[y0:y1, x0:x1].tobytes()) != ref.rgb_sha256):
                raise ValueError('evidence does not match the sealed frame')
        height, width = frame.rgb.shape[:2]
        if endpoints is not None:
            items = [item for item in items if item.evidence.detection_id in endpoints]
        for pair in select_pairs(items, width=width, height=height, max_pairs=128):
            a, b = pair.subject_xyxy, pair.object_xyxy
            if pair.subject > pair.object or max(b[0] - a[2], a[0] - b[2]) < 8:
                continue
            if min(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]) < 20:
                continue
            if endpoints is not None and endpoints[pair.subject] == endpoints[pair.object]:
                continue
            verdict = 'yes' if a[2] < b[0] else 'no'
            swapped = replace(pair, subject=pair.object, object=pair.subject,
                              subject_xyxy=b, object_xyxy=a)
            cases.extend((token, ordered, expected, marked_pair_jpeg(frame.rgb, ordered),
                          None if endpoints is None else (endpoints[ordered.subject], endpoints[ordered.object]))
                         for ordered, expected in ((pair, verdict),
                                                   (swapped, 'no' if verdict == 'yes' else 'yes')))
            break
        if len(cases) == 2 * args.frames:
            return cases
    raise ValueError(f'insufficient verified disjoint pairs for {args.frames} frames')


def evaluate(args):
    cases = prepared_cases(args)
    args.out.mkdir(parents=True, exist_ok=False)
    frozen = []
    for i, (token, pair, expected, jpeg, endpoints) in enumerate(cases, 1):
        filename = f'case-{i:02d}.jpg'
        (args.out / filename).write_bytes(jpeg)
        frozen.append(dict(case=i, token=asdict(token), pair=asdict(pair), expected=expected,
                           image=filename, image_sha256=sha(jpeg)))
        if endpoints is not None:
            frozen[-1]['native_endpoints'] = dict(zip(('subject', 'object'), endpoints))
    frozen_inputs = dict(schema_version=1, report_sha256=args.report_sha256, review_sha256=args.review_sha256,
                         recording_manifest_sha256=sha((args.recording / 'manifest.json').read_bytes()),
                         input_cases=frozen)
    if args.geometry_only:
        write(args.out / 'inputs.json', frozen_inputs)
        write(args.out / 'summary.json', dict(schema_version=1, scope='image_space_left_of_disjoint_boxes',
              results=[dict(case=row['case'], verdict=row['expected'], native_endpoints=row['native_endpoints'])
                       for row in frozen]))
        return 0
    config = RoomSlmBackendConfig.from_json(args.config)
    write(args.out / 'inputs.json', dict(**frozen_inputs,
          config_sha256=sha(args.config.read_bytes()), model_id=config.model_id,
          model_sha256=config.model_sha256, mmproj_sha256=config.mmproj_sha256,
          runtime_sha256=config.runtime_sha256, prompt_policy=args.prompt_policy))
    backend = RoomVlmBackend(config)
    rows = []
    try:
        for row in frozen:
            jpeg = (args.out / row['image']).read_bytes()
            if sha(jpeg) != row['image_sha256']:
                raise ValueError('marked image changed after preparation')
            started = time.perf_counter()
            try:
                result = ask_image_left_of(backend.complete_visual, jpeg, prompt_policy=args.prompt_policy)
                rows.append(dict(case=row['case'], status='answered', **asdict(result)))
            except (OSError, RuntimeError, KeyError, IndexError, TypeError, ValueError) as exc:
                rows.append(dict(case=row['case'], status='error', error=type(exc).__name__,
                                 reason=str(exc)[:256]))
            rows[-1]['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 2)
            print(f"case {row['case']}: {rows[-1].get('verdict', rows[-1]['status'])} "
                  f"({rows[-1]['elapsed_ms']} ms)", flush=True)
    finally:
        closed = backend.close()
    correct = [row.get('verdict') == fixture['expected'] for row, fixture in zip(rows, frozen)]
    errors = sum(row['status'] == 'error' for row in rows)
    write(args.out / 'summary.json', dict(schema_version=1, scope='image_space_left_of_on_disjoint_markers',
          tests=len(frozen), correct=sum(correct), insufficient=sum(row.get('verdict') == 'insufficient'
          for row in rows), both_directions_correct=sum(a and b for a, b in zip(correct[::2], correct[1::2])),
          errors=errors, shutdown=closed, results=rows))
    return int(errors > 0 or not closed['clean_shutdown']
               or (args.review is not None and not all(correct)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('report', 'recording', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--report-sha256', required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--review-sha256')
    parser.add_argument('--geometry-only', action='store_true')
    parser.add_argument('--frames', type=int, choices=range(1, 9), default=4)
    parser.add_argument('--prompt-policy', choices=PROMPT_POLICIES, default='yes-no-v1')
    args = parser.parse_args()
    if (args.review is None) != (args.review_sha256 is None):
        parser.error('--review and --review-sha256 must be supplied together')
    if args.geometry_only and args.review is None:
        parser.error('--geometry-only requires a pinned review')
    if not args.geometry_only and args.config is None:
        parser.error('model evaluation requires --config')
    return evaluate(args)


if __name__ == '__main__':
    raise SystemExit(main())
