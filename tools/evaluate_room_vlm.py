#!/usr/bin/env python3
"""Compare one local RoomVlmBackend across text, geometry-view, and KSS cases.

The script reads an existing Hydra publication and journal. It creates the
same frozen text requests for every condition, selects up to the same number
of 448-pixel-bounded RGB views for the two image conditions, then runs all
conditions through one warmed persistent backend. References are read only
after inference and are never included in model requests.

Example::

    .venv/bin/python tools/evaluate_room_vlm.py \\
        --run runs/handoff-hydra-occupancy-history-00770-20261112 \\
        --config configs/room-vlm-qwen3.local.json \\
        --reference-json /path/to/reviewed-room-labels.json \\
        --out-dir runs/room-vlm-eval-00770

Reference JSON uses ``{"schema_version":1,"labels":{qualified_room_id:
[canonical_label, ...]}}``. Empty label lists and omitted room IDs are
unannotated. Room IDs should be the exact qualified IDs in this report.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.contracts.observations import Taxonomy  # noqa: E402
from neusymnav.contracts.room_semantics import ROOM_LABELS, validate_room_label  # noqa: E402
from neusymnav.rooms.debug_context import build_debug_jobs  # noqa: E402
from neusymnav.rooms.slm_backend import RoomSlmBackendConfig  # noqa: E402
from neusymnav.runtime.ui_transport import decode_publication  # noqa: E402


VARIANTS = ('text', 'text+geometry', 'text+kss')
VIEW_METHODS = {'text+geometry': 'geometry', 'text+kss': 'kss'}
MAX_SELECTOR_VIEWS = 3
MAX_VIEW_EDGE = 448
MAX_VIEW_BYTES = 2 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, 'to_dict') and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return str(value)


def load_reference_labels(path: Path) -> dict[str, tuple[str, ...]]:
    """Read explicit canonical labels keyed by exact qualified room ID."""
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise ValueError('reference JSON must have schema_version: 1')
    labels = value.get('labels')
    if not isinstance(labels, dict):
        raise ValueError('reference JSON must contain a labels object keyed by qualified room ID')
    normalized: dict[str, tuple[str, ...]] = {}
    for room_id, room_labels in labels.items():
        if not isinstance(room_id, str) or not room_id.strip():
            raise ValueError('reference room IDs must be nonempty strings')
        if not isinstance(room_labels, list) or any(label not in ROOM_LABELS for label in room_labels):
            raise ValueError(f'reference labels for {room_id} must be a list of canonical room labels')
        if len(set(room_labels)) != len(room_labels):
            raise ValueError(f'reference labels for {room_id} must be distinct')
        if room_labels:
            normalized[room_id] = tuple(sorted(room_labels))
    return normalized


def rotating_variant_order(round_index: int, room_index: int,
                           variants: Sequence[str] = VARIANTS) -> tuple[str, ...]:
    """Rotate condition order by repeat and room to spread order effects."""
    values = tuple(variants)
    if not values or len(set(values)) != len(values):
        raise ValueError('variants must be a nonempty sequence of distinct names')
    if type(round_index) is not int or round_index < 0 or type(room_index) is not int or room_index < 0:
        raise ValueError('round_index and room_index must be nonnegative integers')
    offset = (round_index + room_index) % len(values)
    return values[offset:] + values[:offset]


def score_annotated_first_round(rows: Sequence[Mapping[str, Any]],
                                reference_labels: Mapping[str, Sequence[str]]) -> dict:
    """Score one selected output per annotated room; repeats are not samples."""
    annotations = {room: tuple(labels) for room, labels in reference_labels.items() if labels}
    first_round: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if row.get('round') != 0:
            continue
        room_id = row.get('room_id')
        if room_id not in annotations:
            continue
        if room_id in first_round:
            raise ValueError(f'more than one first-round output for annotated room {room_id}')
        first_round[room_id] = row
    matched = sorted(first_round)
    supported = [row for row in first_round.values()
                 if row.get('status') == 'available'
                 and row.get('label') in ROOM_LABELS - {'unknown'}]
    correct = sum(row.get('label') in annotations[row['room_id']] for row in supported)
    return {
        'annotation_room_count': len(annotations),
        'matched_room_count': len(matched),
        'supported_count': len(supported),
        'correct_supported_count': correct,
        'coverage': len(supported) / len(matched) if matched else None,
        'selective_accuracy': correct / len(supported) if supported else None,
        'unmatched_annotation_room_ids': sorted(set(annotations) - set(matched)),
    }


def annotated_case_rows(rows: Sequence[Mapping[str, Any]],
                        reference_labels: Mapping[str, Sequence[str]]) -> list[dict]:
    """Expose only first-round annotated predictions beside their references."""
    values = []
    seen = set()
    for row in rows:
        room_id = row.get('room_id')
        if row.get('round') != 0 or room_id not in reference_labels:
            continue
        if room_id in seen:
            raise ValueError(f'more than one first-round output for annotated room {room_id}')
        seen.add(room_id)
        labels = tuple(reference_labels[room_id])
        status = row.get('status')
        label = row.get('label')
        supported = status == 'available' and label in ROOM_LABELS - {'unknown'}
        values.append({
            'room_id': room_id,
            'reference_labels': list(labels),
            'prediction_status': status,
            'prediction_label': label,
            'supported': supported,
            'correct_if_supported': bool(supported and label in labels),
        })
    return sorted(values, key=lambda row: row['room_id'])


def unique_image_dimensions(view_records: Mapping[str, Mapping[str, Sequence[Mapping[str, Any]]]]) -> list[list[int]]:
    """Return JSON-safe unique dimensions from condition/room view records."""
    dimensions = {
        (record['image_width'], record['image_height'])
        for rooms in view_records.values()
        for records in rooms.values()
        for record in records
    }
    return [list(pair) for pair in sorted(dimensions)]


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read JPEG SOF dimensions without decoding the image pixels."""
    if not isinstance(data, bytes) or len(data) < 4 or data[:2] != b'\xff\xd8':
        raise ValueError('selected room view is not a JPEG')
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                   0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    offset = 2
    while offset < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            continue
        if offset + 2 > len(data):
            break
        segment_length = int.from_bytes(data[offset:offset + 2], 'big')
        if segment_length < 2 or offset + segment_length > len(data):
            break
        if marker in sof_markers:
            if segment_length < 7:
                break
            height = int.from_bytes(data[offset + 3:offset + 5], 'big')
            width = int.from_bytes(data[offset + 5:offset + 7], 'big')
            if width <= 0 or height <= 0:
                break
            return width, height
        offset += segment_length
        if marker == 0xDA:  # Start of scan; a valid SOF must have appeared first.
            break
    raise ValueError('selected JPEG has no valid frame dimensions')


def _safe_component(value: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9_.-]+', '_', value).strip('._')
    return cleaned[:48] or 'room'


def write_view_assets(views: Sequence[Any], *, variant: str, room_id: str,
                      output_dir: Path) -> list[dict]:
    """Persist the exact JPEG bytes passed to the backend and bind their manifests."""
    records = []
    for index, view in enumerate(views):
        jpeg = getattr(view, 'jpeg', None)
        view_id = getattr(view, 'view_id', None)
        if not isinstance(jpeg, bytes) or not jpeg or len(jpeg) > MAX_VIEW_BYTES:
            raise ValueError(f'{variant} selected an invalid or oversized JPEG for {room_id}')
        digest = hashlib.sha256(jpeg).hexdigest()
        if view_id != digest:
            raise ValueError(f'{variant} view ID does not bind JPEG bytes for {room_id}')
        width, height = jpeg_dimensions(jpeg)
        if width > MAX_VIEW_EDGE or height > MAX_VIEW_EDGE:
            raise ValueError(f'{variant} view exceeds the shared {MAX_VIEW_EDGE}px edge budget')
        if view.room_id != room_id:
            raise ValueError(f'{variant} selector returned a view for a different room')
        raw_manifest = view.manifest()
        if not isinstance(raw_manifest, dict):
            raise ValueError('room view manifest must be a dictionary')
        manifest = _jsonable(raw_manifest)
        if (manifest.get('image_width', width) != width
                or manifest.get('image_height', height) != height):
            raise ValueError('room view dimensions differ from its JPEG manifest')
        rel = Path('views') / _safe_component(variant) / hashlib.sha256(room_id.encode()).hexdigest()[:16]
        rel /= f'{index:02d}-{view_id[:16]}.jpg'
        target = output_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(jpeg)
        records.append({
            'view_id': view_id,
            'jpeg_path': str(rel),
            'jpeg_sha256': digest,
            'jpeg_bytes': len(jpeg),
            'image_width': width,
            'image_height': height,
            'frame_index': view.frame_index,
            'graph_revision': view.graph_revision,
            'manifest': manifest,
        })
    return records


def _load_source(run_dir: Path, taxonomy_path: Path):
    publication_path = run_dir / 'ui' / 'publication.json'
    journal_path = run_dir / 'hydra' / 'journal.jsonl'
    for path in (publication_path, journal_path, taxonomy_path):
        if not path.is_file():
            raise FileNotFoundError(f'required benchmark input not found: {path}')
    publication = decode_publication(publication_path.read_bytes())
    graph = publication.sources.hydra_graph
    if graph is None:
        raise ValueError('UI publication contains no Hydra graph')
    if graph.status != 'available' or graph.stale or graph.replay_required:
        raise ValueError('UI publication Hydra graph is not current and available')
    taxonomy = Taxonomy.load(taxonomy_path)
    jobs = build_debug_jobs(graph, taxonomy, 0)
    if not jobs:
        raise ValueError('Hydra graph produced no room-label debug requests')
    return publication_path, journal_path, graph, jobs


def _request_summary(request) -> dict:
    context = request.context
    return {
        'request_id': request.request_id,
        'qualified_room_id': request.key.room_id,
        'graph_revision': request.key.graph_revision,
        'input_prefix_sha256': request.key.input_prefix_sha256,
        'geometry_hash': request.key.geometry_hash,
        'context_hash': request.key.context_hash,
        'geometry_status': context.geometry_status,
        'membership_status': context.membership_status,
        'inference_block_reason': request.inference_block_reason,
        'object_count': context.distinct_object_count,
        'truncated': context.truncated,
        'objects': [
            {'native_id': item.native_id, 'category': item.category,
             'membership_status': item.membership_status,
             'association_status': item.association_status}
            for item in context.objects
        ],
        'source_manifest': _jsonable(request.source_manifest),
    }


def _metric_timing(metrics: Mapping[str, Any]) -> dict:
    native = metrics.get('native_timings')
    usage = metrics.get('native_usage')
    native = native if isinstance(native, Mapping) else {}
    return {
        'latency_ms': metrics.get('latency_ms'),
        'startup_ms': metrics.get('startup_ms'),
        'server_reused': metrics.get('server_reused'),
        'prompt_tokens': metrics.get('prompt_tokens'),
        'native_timings': _jsonable(native) if native else None,
        'native_usage': _jsonable(usage) if isinstance(usage, Mapping) else usage,
        'cache_n': native.get('cache_n'),
    }


def _run_case(backend, request, views: tuple, variant: str, round_index: int,
              order_index: int) -> dict:
    row = {'round': round_index, 'order_index': order_index, 'variant': variant,
           'room_id': request.key.room_id, 'request_id': request.request_id,
           'view_ids': [view.view_id for view in views], 'view_count': len(views)}
    if variant != 'text' and not views:
        row.update(status='skipped', label=None, reason='no_accepted_room_views',
                   inference_wall_ms=None, validation_wall_ms=None, backend_metrics={})
        return row
    started = time.perf_counter_ns()
    try:
        proposal = backend.infer(request, views=views)
        inference_wall_ms = (time.perf_counter_ns() - started) / 1_000_000
        validate_started = time.perf_counter_ns()
        result = validate_room_label(proposal, request.context,
                                     allowed_view_ids=tuple(view.view_id for view in views))
        validation_wall_ms = (time.perf_counter_ns() - validate_started) / 1_000_000
        metrics = _jsonable(dict(backend.last_metrics))
        row.update(status=result.status, label=result.label, alternatives=list(result.alternatives),
                   supporting_object_ids=list(result.supporting_object_ids),
                   supporting_view_ids=list(getattr(result, 'supporting_view_ids', ())),
                   reason=result.reason, result=result.to_dict(),
                   inference_wall_ms=inference_wall_ms,
                   validation_wall_ms=validation_wall_ms,
                   backend_metrics=metrics, timing=_metric_timing(metrics))
    except Exception as exc:  # retain the attempt as a failed benchmark outcome
        metrics = _jsonable(dict(getattr(backend, 'last_metrics', {})))
        row.update(status='execution_error', label=None, reason=f'{type(exc).__name__}: {exc}',
                   inference_wall_ms=(time.perf_counter_ns() - started) / 1_000_000,
                   validation_wall_ms=None, backend_metrics=metrics,
                   timing=_metric_timing(metrics))
    return row


def run_benchmark(*, run_dir: Path, config_path: Path, taxonomy_path: Path,
                  output_dir: Path, reference_path: Path | None = None,
                  repeat: int = 1, view_limit: int = 2) -> dict:
    """Run the three conditions with one backend and return a JSON-safe report."""
    run_dir, config_path = Path(run_dir), Path(config_path)
    taxonomy_path, output_dir = Path(taxonomy_path), Path(output_dir)
    if type(repeat) is not int or repeat < 1:
        raise ValueError('repeat must be a positive integer')
    if type(view_limit) is not int or not 1 <= view_limit <= MAX_SELECTOR_VIEWS:
        raise ValueError(f'view_limit must be from 1 to {MAX_SELECTOR_VIEWS}')
    if not config_path.is_file():
        raise FileNotFoundError(f'VLM config not found: {config_path}')
    publication_path, journal_path, graph, jobs = _load_source(run_dir, taxonomy_path)
    requests = {job.request.key.room_id: job.request for job in jobs}
    room_ids = tuple(sorted(requests))

    from neusymnav.rooms.room_views import select_room_views_batch
    views_by_variant = {}
    for variant, method in VIEW_METHODS.items():
        views_by_variant[variant] = select_room_views_batch(
            journal_path, graph, room_ids, method=method, limit=view_limit)

    output_dir.mkdir(parents=True, exist_ok=True)
    # Save exact input images before loading a model; reports can then be
    # inspected independently of a later inference failure.
    view_records = {variant: {} for variant in VIEW_METHODS}
    for variant in VIEW_METHODS:
        selected_by_room = views_by_variant[variant]
        for room_id in room_ids:
            selected = tuple(selected_by_room.get(room_id, ()))
            view_records[variant][room_id] = write_view_assets(
                selected, variant=variant, room_id=room_id, output_dir=output_dir)
            if len(selected) > view_limit:
                raise ValueError(f'{variant} selector exceeded the shared view count budget')

    config = RoomSlmBackendConfig.from_json(config_path)
    if not config.enabled:
        raise ValueError('VLM config must explicitly set enabled=true for an offline benchmark')
    from neusymnav.rooms.vlm_backend import RoomVlmBackend
    backend = RoomVlmBackend(config)
    warmup = None
    warmup_error = None
    rows = []
    order_index = 0
    try:
        try:
            warmup = _jsonable(backend.warm())
        except Exception as exc:
            warmup_error = f'{type(exc).__name__}: {exc}'
        if warmup_error is None:
            for round_index in range(repeat):
                for room_index, room_id in enumerate(room_ids):
                    request = requests[room_id]
                    order = rotating_variant_order(round_index, room_index)
                    for variant in order:
                        selected = () if variant == 'text' else tuple(
                            views_by_variant[variant].get(room_id, ()))
                        rows.append(_run_case(backend, request, selected, variant,
                                              round_index, order_index))
                        order_index += 1
    finally:
        try:
            shutdown = _jsonable(backend.close(timeout_s=3.0))
        except Exception as exc:
            shutdown = {'error': f'{type(exc).__name__}: {exc}'}

    # Read independent labels only after model execution has finished.
    references = {} if reference_path is None else load_reference_labels(reference_path)
    scores = {}
    annotated_outputs = {}
    for variant in VARIANTS:
        variant_rows = [row for row in rows if row['variant'] == variant]
        scores[variant] = score_annotated_first_round(variant_rows, references)
        annotated_outputs[variant] = annotated_case_rows(variant_rows, references)
    report = {
        'schema_version': 1,
        'kind': 'room_vlm_three_condition_benchmark',
        'source': {
            'run_dir': str(run_dir.resolve()),
            'publication_path': str(publication_path.resolve()),
            'publication_sha256': sha256_file(publication_path),
            'journal_path': str(journal_path.resolve()),
            'journal_sha256': sha256_file(journal_path),
            'episode_id': graph.episode_id,
            'run_id': graph.run_id,
            'graph_revision': graph.graph_revision,
            'input_prefix_sha256': graph.input_prefix_sha256,
            'taxonomy_path': str(taxonomy_path.resolve()),
            'taxonomy_sha256': sha256_file(taxonomy_path),
        },
        'model': {
            'config_path': str(config_path.resolve()),
            'config_sha256': sha256_file(config_path),
            'model_id': config.model_id,
            'model_manifest_hash': config.model_manifest_hash,
            'model_sha256': config.model_sha256,
            'runtime_sha256': config.runtime_sha256,
            'mmproj_sha256': config.mmproj_sha256,
            'prompt_policy': config.prompt_policy,
            'threads': config.threads,
            'effective_threads': config.effective_threads,
            'gpu_device': config.gpu_device,
            'prompt_cache_per_inference': False,
            'warmup_static_prefix_cache': True,
        },
        'protocol': {
            'conditions': list(VARIANTS),
            'backend_instances': 1,
            'warmups': 1,
            'repeat_rounds': repeat,
            'condition_order': 'deterministic rotation by round and room index',
            'max_image_views_per_condition': view_limit,
            'max_image_edge_px': MAX_VIEW_EDGE,
            'max_image_bytes': MAX_VIEW_BYTES,
            'observed_image_dimensions_wh': unique_image_dimensions(view_records),
            'reference_labels_passed_to_model': False,
        },
        'warmup': {'metrics': warmup, 'error': warmup_error},
        'cases': {
            'requests': {room_id: _request_summary(requests[room_id]) for room_id in room_ids},
            'selected_views': view_records,
            'results': rows,
        },
        'reference': {
            'path': None if reference_path is None else str(Path(reference_path).resolve()),
            'sha256': None if reference_path is None else sha256_file(Path(reference_path)),
            'annotated_room_ids': sorted(references),
            'labels': {room_id: list(labels) for room_id, labels in sorted(references.items())},
            'scoring_round': 0,
            'scores_by_condition': scores,
            'annotated_outputs_by_condition': annotated_outputs,
        },
        'shutdown': shutdown,
        'limitations': [
            'Room-view room attribution is a nearest-place estimate with the selector purity gate; it is not room ground truth.',
            'Geometry and KSS use the same JPEG size cap, encoding, and per-condition view-count budget; selected frame counts may be lower when evidence is unavailable.',
            'Quality scoring uses only explicitly annotated qualified room IDs and only round 0; repeated calls are not independent room samples.',
            'Wall latency is per call. Runtime RSS/VRAM/resource peaks are reported only when backend metrics provide them.',
        ],
    }
    return _jsonable(report)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--run', required=True, type=Path,
        help='one run directory with ui/publication.json and hydra/journal.jsonl')
    parser.add_argument('--config', required=True, type=Path,
        help='enabled local RoomVlmBackend config; no remote fallback is used')
    parser.add_argument('--taxonomy', type=Path, default=ROOT / 'configs/taxonomy-v1.json')
    parser.add_argument('--reference-json', type=Path,
        help='optional JSON: {"schema_version":1,"labels":{"qualified-room-id":["bedroom"]}}')
    parser.add_argument('--repeat', type=int, default=1,
        help='number of calls per room and condition; only round 0 is quality-scored')
    parser.add_argument('--view-limit', type=int, default=2,
        help='same maximum views for geometry and KSS conditions (1..3)')
    parser.add_argument('--out-dir', required=True, type=Path,
        help='new or reusable output directory for report.json and exact JPEG inputs')
    args = parser.parse_args(argv)
    report = run_benchmark(run_dir=args.run, config_path=args.config,
        taxonomy_path=args.taxonomy, reference_path=args.reference_json,
        output_dir=args.out_dir, repeat=args.repeat, view_limit=args.view_limit)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output = args.out_dir / 'report.json'
    output.write_text(json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n',
                      encoding='utf-8')
    print(json.dumps({'report': str(output.resolve()),
        'rooms': len(report['cases']['requests']), 'calls': len(report['cases']['results']),
        'warmup_error': report['warmup']['error']}, sort_keys=True))
    return 0 if report['warmup']['error'] is None else 2


if __name__ == '__main__':
    raise SystemExit(main())
