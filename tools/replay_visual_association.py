#!/usr/bin/env python3
"""GT-free fixed-cloud replay with complete real appearance extraction.

No detector, projector, simulator or GT reader is invoked. The offline quality
evaluator consumes assigned-memory-predictions.json separately, with all GT.
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import importlib.util
from pathlib import Path
import tempfile

from neusymnav.contracts.observations import AppearanceBatch, DetectionBatch, validate_appearance_batch
from neusymnav.contracts.serialization import dumps, loads
from neusymnav.evaluation.quality_dataset import _validate_document
from neusymnav.evaluation.quality_export import _asset, _canonical, _json, _read, _sha, _snapshot_connection
from neusymnav.objects.association_recipe import AssociationRecipe
from neusymnav.perception.appearance_client import AppearanceWorkerEncoder, attach_features
from neusymnav.runtime.configuration import load_config

# A file-based import also supports importlib loading from tests without adding
# the tools directory to sys.path or making it a runtime package.
_spec = importlib.util.spec_from_file_location('fixed_source_replay', Path(__file__).with_name('replay_association_quality.py'))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)


def _encoder(path):
    config = load_config(path)
    if config.data.get('appearance_mode') != 'openai_clip':
        raise ValueError('visual replay requires the explicit openai_clip appearance profile')
    python, script = config.worker('appearance')
    worker = config.data['worker']
    checkpoint = config.asset(dict(path=worker['checkpoint_path'], sha256=worker['checkpoint_sha256']), 'appearance_checkpoint')
    encoder = AppearanceWorkerEncoder(python, checkpoint,
        checkpoint_sha256=worker['checkpoint_sha256'], model_name=worker['model_name'],
        checkpoint_format=worker.get('checkpoint_format', 'safetensors'),
        preprocessing_id=worker['preprocessing_id'], timeout_s=worker.get('timeout_s', 2.),
        startup_timeout_s=worker.get('startup_timeout_s', 30.),
        max_request_bytes=worker.get('max_request_bytes', 32*1024**2),
        _worker_command=[str(python), str(script), '--worker'])
    return encoder, dict(config_sha256=_sha(_read(Path(path))), worker=copy.deepcopy(worker),
        checked_assets=copy.deepcopy(config.checked_assets))


def _binding(source, metadata, frame):
    return dict(source_asset=metadata['source_asset'], batch_asset=metadata['batch_asset'],
        frame_id=frame['frame_id'], capture_monotonic_ns=source.capture_monotonic_ns,
        clock_domain=source.clock_domain, geometry_hash=source.geometry_hash,
        calibration_id=source.calibration_id, pose_version=source.pose_version,
        rgb_sha256=_sha(source.rgb.tobytes()),
        masks=[dict(detection_id=obj['id'], **obj['mask']) for obj in frame['objects']])


def _cached(cache, index, binding):
    entry = cache['document']['frames'][index]
    if entry['binding'] != binding:
        raise ValueError('cached appearance source/mask/timestamp binding mismatch')
    path = Path(entry['path'])
    if path.name != str(path) or path.suffix != '.json':
        raise ValueError('unsafe cached appearance path')
    raw = _read(cache['root']/path)
    if _sha(raw) != entry['sha256']:
        raise ValueError('cached appearance checksum mismatch')
    return loads(raw)


def _features(inputs, batches, metadata, encoder, recipe, cache_path, stage):
    cache = None
    if cache_path is not None:
        cache_root = Path(cache_path).resolve()
        document = _json(_read(cache_root/'manifest.json'))
        if document.get('schema_version') != 1 or document.get('encoder_recipe') != recipe or len(document.get('frames', [])) != len(inputs):
            raise ValueError('cached appearance recipe/frame count mismatch')
        cache = dict(root=cache_root, document=document)
    directory = stage/'features'
    directory.mkdir()
    manifest = dict(schema_version=1, encoder_recipe=recipe, frames=[])
    enriched, first, count = [], None, 0
    for index, ((source, observations, frame), batch, provenance) in enumerate(zip(inputs, batches, metadata)):
        binding = _binding(source, provenance, frame)
        features = (_cached(cache, index, binding) if cache is not None else encoder.encode(source, batch))
        validate_appearance_batch(source, batch, features)
        if set(features.features) != {detection.detection_id for detection in batch.detections}:
            raise ValueError('complete visual replay requires features for every original detection')
        for feature in features.features.values():
            if first is None:
                first = feature
            else:
                first.require_compatible(feature)
        count += len(features.features)
        projected_ids = {item.detection_id for item in observations}
        projected_features = replace(features, features={key:value for key,value in features.features.items() if key in projected_ids})
        attached = attach_features(observations, projected_features)
        if any(item.appearance is None for item in attached):
            raise ValueError('complete visual replay requires every projected appearance feature')
        enriched.append((source, attached, frame))
        raw = (dumps(features)+'\n').encode()
        filename = f'{index:04d}.json'
        (directory/filename).write_bytes(raw)
        manifest['frames'].append(dict(binding=binding, path=filename, sha256=_sha(raw), features=len(features.features)))
    if first is None:
        raise ValueError('visual replay has no appearance features')
    manifest.update(feature_space=first.space_id, feature_dimension=int(first.vector.size),
        extracted_features=count, encoder_metadata=copy.deepcopy(cache['document']['encoder_metadata']) if cache else dict(encoder.space_metadata or {}))
    if not manifest['encoder_metadata']:
        raise ValueError('appearance encoder must report actual model/transform/runtime metadata')
    if cache and (manifest['feature_space'] != cache['document'].get('feature_space') or manifest['feature_dimension'] != cache['document'].get('feature_dimension')):
        raise ValueError('cached appearance feature space mismatch')
    (directory/'manifest.json').write_text(_canonical(manifest)+'\n')
    return enriched, manifest


def _derived(document, frames, diagnostics, *, assigned):
    frames = copy.deepcopy(frames)
    if assigned:
        for frame in frames:
            frame['objects'] = [obj for obj in frame['objects'] if 'identity' in obj]
    result = dict(schema_version=1, binding=copy.deepcopy(document['binding']),
        provenance=dict(kind=document['provenance']['kind'],
            description='GT-free fixed-cloud appearance replay; original frame and mask sources retained.',
            scope='assigned-memory' if assigned else 'all-projected-memory',
            association_recipe=diagnostics['recipe'], appearance_enabled=diagnostics['visual'],
            unresolved_observations=diagnostics['unresolved_observations']),
        identity_semantics='online' if assigned else diagnostics['identity_semantics'],
        score_floor=document['score_floor'], max_detections=document['max_detections'],
        final_aliases={}, frames=frames)
    _validate_document(result, prediction=True)
    return result


def _run_mode(config, inputs, document, masks, stage, output, name, recipe, visual):
    frames, diagnostics = _base._run(config, inputs, name=name, recipe=recipe, visual=visual)
    directory = stage/name
    directory.mkdir()
    for relative, raw in masks.items():
        path = directory/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    assignments = {row['frame_id']: {item['detection_id']:item['online_identity'] for item in row['assignments']}
                   for row in diagnostics['per_frame']}
    exclusions, partition, totals = [], {}, {}
    for _, observations, original in inputs:
        endpoints = assignments[original['frame_id']]
        for obj in original['objects']:
            identity = endpoints.get(obj['id'])
            if identity is None:
                exclusions.append(dict(frame_id=original['frame_id'], detection_id=obj['id'],
                    reason='unresolved_association' if obj['id'] in endpoints else 'no_original_projected_observation'))
            else:
                partition.setdefault(identity, []).append([original['frame_id'], obj['id']])
    for row in diagnostics['per_frame']:
        for key, value in row['association_diagnostics'].items():
            if type(value) in (int, float):
                totals[key] = totals.get(key, 0)+value
    result = dict(assigned_observations=sum(len(values) for values in partition.values()),
        unresolved_observations=diagnostics['unresolved_observations'],
        generated_identities=diagnostics['generated_identities'], association_totals=totals,
        partition=list(partition.values()), exclusions=exclusions,
        total_association_elapsed_ns=diagnostics['total_association_elapsed_ns'])
    for assigned, filename, label in [(False,'predictions.json','predictions'),
                                      (True,'assigned-memory-predictions.json','assigned_predictions')]:
        raw = (_canonical(_derived(document, frames, diagnostics, assigned=assigned))+'\n').encode()
        (directory/filename).write_bytes(raw)
        result[label] = str(output/name/filename)
        result[label+'_sha256'] = _sha(raw)
    diagnostics.update(assigned_observations=result['assigned_observations'], exclusions=exclusions,
                       partition=result['partition'], association_totals=totals)
    (directory/'diagnostics.json').write_text(_canonical(diagnostics)+'\n')
    result['diagnostics'] = str(output/name/'diagnostics.json')
    return result


def replay_visual_association(objects, *, predictions, appearance_config, out, feature_cache=None):
    """Extract/cache real features and replay four modes; deliberately no GT inlet."""
    root, prediction_path, output = Path(objects).resolve(), Path(predictions).absolute(), Path(out).absolute()
    if output.resolve().is_relative_to(root) or output.resolve().is_relative_to(prediction_path.parent.resolve()):
        raise ValueError('output must be outside both source inputs')
    if output.is_symlink() or output.exists():
        raise FileExistsError('visual replay output must be a new directory')
    raw = _read(prediction_path)
    document = _json(raw)
    _validate_document(document, prediction=True)
    with _snapshot_connection(root) as connection:
        config, inputs, hashes, masks, digest = _base._inputs(root, prediction_path, document, connection)
        batches = [loads(_asset(root, connection, metadata['batch_asset']))
                   for metadata in document['provenance']['source_metadata']]
    if any(not isinstance(batch, DetectionBatch) for batch in batches):
        raise ValueError('original typed DetectionBatch required')
    projected = sum(len(items) for _,items,_ in inputs)
    if not projected:
        raise ValueError('visual replay requires projected observations')
    detector = sum(len(frame['objects']) for _,_,frame in inputs)
    encoder, recipe = _encoder(appearance_config)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix='visual-replay-', dir=output.parent) as temporary:
            stage = Path(temporary)
            enriched, feature_manifest = _features(inputs, batches, document['provenance']['source_metadata'],
                encoder, recipe, feature_cache, stage)
            summary = dict(schema_version=1, frames=len(inputs), detector_outputs=detector,
                projected_observations=projected, projection_losses=detector-projected,
                extracted_features=feature_manifest['extracted_features'], feature_space=feature_manifest['feature_space'],
                appearance_cache=str(output/'features'), appearance_cache_manifest_sha256=_sha(_read(stage/'features/manifest.json')),
                source_ledger=str(root), source_predictions=str(prediction_path),
                input_predictions_sha256=_sha(raw), ledger_logical_sha256=digest,
                verified_input_assets=hashes, input_source_metadata=copy.deepcopy(document['provenance']['source_metadata']),
                runs={}, limitations=['GT never read here; evaluate assigned-memory derivatives separately retaining every GT frame/object.',
                    'Detector metrics retain all original detector outputs; memory metrics use assigned projected observations only.',
                    'Original projected clouds preserved; appearance attached offline before matching, not a reconstruction of live attachment timing.',
                    'Association timing excludes appearance/decoding/output and is not native throughput.'])
            for name, recipe_value, visual in [('legacy_geometry', AssociationRecipe(), False),
                ('conceptgraphs_spatial', AssociationRecipe(mode='conceptgraphs'), False),
                ('legacy_geometry_appearance', AssociationRecipe(), True),
                ('conceptgraphs_visual', AssociationRecipe(mode='conceptgraphs'), True)]:
                summary['runs'][name] = _run_mode(config, enriched if visual else inputs, document, masks,
                    stage, output, name, recipe_value, visual)
            (stage/'replay-manifest.json').write_text(_canonical(summary)+'\n')
            if output.exists() or output.is_symlink():
                raise FileExistsError('replay output appeared during preparation')
            stage.rename(output)
    finally:
        encoder.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('objects','predictions','appearance-config','out'):
        parser.add_argument('--'+flag, required=True)
    parser.add_argument('--feature-cache', help='Previously verified features/ directory; bindings and recipe rechecked')
    args = parser.parse_args()
    print(_canonical(replay_visual_association(args.objects, predictions=args.predictions,
        appearance_config=args.appearance_config, out=args.out, feature_cache=args.feature_cache)))


if __name__ == '__main__':
    main()
