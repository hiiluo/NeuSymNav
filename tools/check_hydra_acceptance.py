#!/usr/bin/env python3
"""Fail-closed H7 checker for Hydra native fixtures, export and A/B evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SHA256 = re.compile(r'^[0-9a-f]{64}$')


def _read(path: Path, errors: list[str], label: str):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict):
            raise ValueError('expected object')
        return value
    except (OSError, ValueError, UnicodeError) as exc:
        errors.append(f'{label}: cannot read valid JSON at {path}: {exc}')
        return {}


def _asset(spec, errors: list[str], label: str, base: Path, *, require_hash: bool = True):
    if not isinstance(spec, dict):
        errors.append(f'{label}: missing asset record')
        return
    raw_path, expected = spec.get('graph_path', spec.get('graph_asset', spec.get('asset_path'))), spec.get('graph_sha256', spec.get('asset_sha256'))
    if not isinstance(raw_path, str) or (require_hash and not SHA256.fullmatch(expected or '')):
        errors.append(f'{label}: invalid graph path or SHA-256')
        return
    path = Path(raw_path)
    if not path.is_absolute():
        path = base / path
    try:
        content = path.read_bytes()
        actual = hashlib.sha256(content).hexdigest()
    except OSError as exc:
        errors.append(f'{label}: graph asset unavailable: {exc}')
        return
    if expected is not None and actual != expected:
        errors.append(f'{label}: graph SHA-256 mismatch')
    if type(spec.get('graph_bytes')) is int and spec['graph_bytes'] != len(content):
        errors.append(f'{label}: graph byte count mismatch')


def _verify_h3(root: Path, errors: list[str]):
    project_root = Path(__file__).resolve().parents[1]
    objects = _read(root/'h3-same-class-objects'/'result.json', errors, 'H3 object gate')
    steps = objects.get('steps')
    if (objects.get('reloaded_objects') != 2 or not isinstance(steps, list) or len(steps) < 8 or
            any(not isinstance(step, dict) or step.get('accepted') is not True or step.get('object_nodes') != 2 for step in steps) or
            objects.get('valid_detection_count', 2) < 2):
        errors.append('H3 object gate: two valid detections and stable native O(0)/O(1) reload evidence are required')
    ids = objects.get('ids')
    if isinstance(steps, list) and steps and isinstance(steps[-1], dict):
        ids = steps[-1].get('ids', ids)
    if ids is not None and ids != ['O(0)', 'O(1)']:
        errors.append('H3 object gate: expected stable native IDs O(0) and O(1)')
    _asset(objects, errors, 'H3 object gate', project_root, require_hash=False)
    for name, expected in (('h3-two-room', 2), ('h3-open-room', 1)):
        room = _read(root/name/'result.json', errors, f'{name} room gate')
        layers = room.get('reloaded_layers')
        if (room.get('room_gate_pass') is not True or room.get('room_nodes') != expected or
                room.get('room_gate_expected') != expected or not isinstance(layers, dict) or
                layers.get('4') != expected):
            errors.append(f'{name} room gate: expected {expected} native rooms after Spark-DSG reload')
        _asset(room, errors, f'{name} room gate', project_root, require_hash=False)


def evaluate_acceptance(run_dir: str | Path, native_evidence_root: str | Path) -> list[str]:
    run = Path(run_dir).resolve()
    evidence = Path(native_evidence_root).resolve()
    errors: list[str] = []
    runtime = _read(run/'acceptance.json', errors, 'runtime/A-B evidence')
    if runtime.get('schema_version') != 1:
        errors.append('runtime/A-B evidence: schema_version must equal 1')
    runtime_record = runtime.get('runtime')
    if not isinstance(runtime_record, dict):
        runtime_record = {}
        errors.append('runtime/A-B evidence: runtime record is missing')
    if runtime_record.get('complete') is not True or runtime_record.get('timeout') is not False:
        errors.append('runtime/A-B evidence: coordinator run must complete without timeout')
    if type(runtime_record.get('native_steps')) is not int or runtime_record['native_steps'] <= 0:
        errors.append('runtime/A-B evidence: at least one accepted native step is required')
    counts = runtime_record.get('node_counts')
    if isinstance(counts, dict) and counts and all(type(value) is int and value >= 0 for value in counts.values()):
        if sum(counts.values()) == 0 and not (isinstance(runtime_record.get('empty_graph_reason'), str)
                                                and runtime_record['empty_graph_reason'].strip()):
            errors.append('runtime/A-B evidence: empty native graph needs an explicit reason')
    else:
        errors.append('runtime/A-B evidence: bounded native node counts are required')
    if runtime_record.get('transform_contract_version') != 'hydra-frame-v1':
        errors.append('runtime/A-B evidence: transform contract version is missing or mismatched')
    for name in ('labelspace_sha256', 'source_sha256', 'navigation_sha256'):
        if not SHA256.fullmatch(runtime_record.get(name) or ''):
            errors.append(f'runtime/A-B evidence: {name} must be a pinned SHA-256')

    manifest = _read(run/'hydra-export-manifest.json', errors, 'Hydra export manifest')
    if manifest.get('schema_version') != 1 or manifest.get('complete') is not True:
        errors.append('Hydra export manifest: complete schema-1 native export is required')
    for key in ('graph_sha256', 'journal_sha256', 'input_prefix_sha256'):
        if not SHA256.fullmatch(manifest.get(key) or ''):
            errors.append(f'Hydra export manifest: {key} is missing or invalid')
    graph_bytes = manifest.get('graph_bytes')
    if type(graph_bytes) is not int or not 0 < graph_bytes <= 128 * 1024**2:
        errors.append('Hydra export manifest: native graph asset must be between 1 byte and 128 MiB')
    _asset(manifest, errors, 'Hydra export manifest', run)
    journal = manifest.get('journal_path')
    if isinstance(journal, str):
        journal_path = Path(journal)
        if not journal_path.is_absolute():
            journal_path = run/journal_path
        try:
            if hashlib.sha256(journal_path.read_bytes()).hexdigest() != manifest.get('journal_sha256'):
                errors.append('Hydra export manifest: journal SHA-256 mismatch')
        except OSError as exc:
            errors.append(f'Hydra export manifest: journal unavailable: {exc}')
    else:
        errors.append('Hydra export manifest: journal_path is missing')
    selected = manifest.get('selected_inputs')
    if not isinstance(selected, list) or not selected or any(
            not isinstance(item, dict) or not isinstance(item.get('source'), dict) or
            not SHA256.fullmatch(item.get('payload_sha256') or '') or
            type(item.get('payload_bytes')) is not int or item['payload_bytes'] <= 0
            for item in (selected if isinstance(selected, list) else [])):
        errors.append('Hydra export manifest: exact selected-input payload evidence is invalid')
    elif manifest.get('graph_revision') != len(selected):
        errors.append('Hydra export manifest: graph revision differs from accepted selected-input count')

    pairs = runtime.get('ab_pairs')
    if not isinstance(pairs, list) or len(pairs) != 3:
        errors.append('A/B evidence: exactly three paired 90-second runs are required')
        pairs = []
    for index, pair in enumerate(pairs):
        label = f'A/B pair {index+1}'
        if not isinstance(pair, dict):
            errors.append(f'{label}: pair record is invalid')
            continue
        baseline, hydra = pair.get('baseline'), pair.get('hydra')
        if not isinstance(baseline, dict) or not isinstance(hydra, dict):
            errors.append(f'{label}: baseline and Hydra records are required')
            continue
        for backend, record in (('baseline', baseline), ('Hydra', hydra)):
            if record.get('complete') is not True or type(record.get('duration_s')) not in (int, float) or record['duration_s'] < 90:
                errors.append(f'{label}: {backend} run must complete for at least 90 seconds')
        for key in ('ordered_input_sha256', 'source_sha256', 'navigation_sha256'):
            if not SHA256.fullmatch(baseline.get(key) or '') or baseline.get(key) != hydra.get(key):
                errors.append(f'{label}: ordered source/config {key} differs between backends')
        if baseline.get('source_sha256') != runtime_record.get('source_sha256'):
            errors.append(f'{label}: source hash differs from the accepted runtime source')
        if baseline.get('navigation_sha256') != runtime_record.get('navigation_sha256'):
            errors.append(f'{label}: navigation hash differs from H0')
        for backend, record in (('baseline', baseline), ('Hydra', hydra)):
            if (type(record.get('translation_m')) not in (int, float) or
                    not math.isfinite(record['translation_m']) or record['translation_m'] < 0):
                errors.append(f'{label}: {backend} translation measurement is invalid')
            fraction = record.get('pending_source_fraction')
            if (type(fraction) not in (int, float) or not math.isfinite(fraction) or
                    not 0 <= fraction <= 1):
                errors.append(f'{label}: {backend} pending-source fraction is invalid')
        if (type(baseline.get('translation_m')) in (int, float) and baseline['translation_m'] > 0 and
                type(hydra.get('translation_m')) in (int, float) and
                hydra['translation_m'] < .9 * baseline['translation_m']):
            errors.append(f'{label}: Hydra translation is below 90% of its baseline')
        if (type(baseline.get('pending_source_fraction')) in (int, float) and
                type(hydra.get('pending_source_fraction')) in (int, float) and
                hydra['pending_source_fraction'] - baseline['pending_source_fraction'] > .05):
            errors.append(f'{label}: pending-source fraction regressed by more than 5 percentage points')

    _verify_h3(evidence, errors)
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--native-evidence-root', type=Path,
        default=Path(__file__).resolve().parents[1]/'.runtime'/'hydra_ws'/'artifacts')
    args = parser.parse_args(argv)
    errors = evaluate_acceptance(args.run_dir, args.native_evidence_root)
    print(json.dumps({'accepted': not errors, 'errors': errors}, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
