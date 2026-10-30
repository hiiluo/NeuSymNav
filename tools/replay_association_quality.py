#!/usr/bin/env python3
"""Replay fixed committed clouds through association, without any GT inlet.

Only the original source-ordered selection is accepted. Predictions supply the
retained frame scope and masks; original canonical identity fields are ignored.
All source assets are verified through the read-only committed-ledger reader.
Timing covers advance_time/ingest only; it is not native pipeline throughput.
"""
from __future__ import annotations

import argparse
import copy
import io
from pathlib import Path
import tempfile
import time

import numpy as np

from neusymnav.contracts.observations import (
    DetectionBatch, ObjectObservation, Observation, validate_object_observations,
)
from neusymnav.contracts.serialization import loads
from neusymnav.evaluation.quality_dataset import _validate_document
from neusymnav.evaluation.quality_export import (
    _asset, _canonical, _json, _metadata, _read, _sha, _snapshot_connection,
)
from neusymnav.objects.association import AssociationEngine, AssociationObservation
from neusymnav.objects.association_recipe import AssociationRecipe


def _require_match(actual, expected, message):
    if any(actual.get(key) != value for key, value in expected.items()):
        raise ValueError(message)


def _mask_bytes(predictions, reference):
    """Read only a regular relative exported mask, rejecting parent symlinks."""
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        raise ValueError('exported mask reference required')
    relative = Path(reference['path'])
    if (relative.is_absolute() or len(relative.parts) < 2 or relative.parts[0] != 'masks'
            or '..' in relative.parts):
        raise ValueError('mask must be relative to the exported masks directory')
    path = predictions.parent
    for part in relative.parts:
        path = path/part
        if path.is_symlink():
            raise ValueError('symlink mask paths are forbidden')
    raw = _read(path)
    if _sha(raw) != reference['sha256']:
        raise ValueError('exported mask checksum mismatch')
    return raw


def _inputs(root, prediction_path, document, connection):
    """Validate the complete original selection before creating any output."""
    if connection.execute('PRAGMA user_version').fetchone()[0] != 1:
        raise ValueError('unsupported ledger schema')
    config_raw, checkpoint_raw = _metadata(connection, 'config'), _metadata(connection, 'checkpoint')
    config = _json(config_raw)
    if document['binding']['episode_id'] != config['episode_id']:
        raise ValueError('prediction source episode mismatch')
    frames = document['frames']
    if not 1 <= len(frames) <= 1000:
        raise ValueError('replay requires 1..1000 retained source frames')
    provenance = document['provenance']
    selection = provenance.get('selection', {})
    total = connection.execute('SELECT count(*) FROM batches').fetchone()[0]
    _require_match(selection, dict(policy='first_committed_batches_in_source_order',
        selected_batches=len(frames), total_committed_batches=total), 'prediction selection provenance mismatch')
    if type(selection.get('limit')) is not int or selection['limit'] < len(frames):
        raise ValueError('prediction selection provenance limit mismatch')
    rows = connection.execute(
        "SELECT * FROM batches ORDER BY json_extract(data, '$.source.frame_index'),batch_key LIMIT ?",
        (len(frames),)).fetchall()
    logical_digest = _sha(_canonical(dict(config=config_raw, checkpoint=checkpoint_raw,
        batches=[dict(row) for row in rows])).encode())
    if provenance.get('ledger_logical_sha256') != logical_digest:
        raise ValueError('prediction source ledger logical checksum mismatch')
    source_metadata = provenance.get('source_metadata')
    if not isinstance(source_metadata, list) or len(source_metadata) != len(frames):
        raise ValueError('prediction source provenance missing')
    result, assets, mask_files = [], {}, {}
    for ordinal, (frame, metadata, row) in enumerate(zip(frames, source_metadata, rows)):
        data = _json(row['data'])
        source_raw = _asset(root, connection, row['source_asset'])
        batch_raw = _asset(root, connection, row['batch_asset'])
        source, batch = loads(source_raw), loads(batch_raw)
        if not isinstance(source, Observation) or not isinstance(batch, DetectionBatch):
            raise ValueError('typed Observation and DetectionBatch assets required')
        expected = dict(source=dict(episode_id=source.key.episode_id, sensor_id=source.key.sensor_id,
            frame_index=source.key.frame_index), capture_monotonic_ns=source.capture_monotonic_ns,
            clock_domain=source.clock_domain, geometry_hash=source.geometry_hash,
            calibration_id=source.calibration_id, pose_version=source.pose_version,
            detector_profile_id=config['detector_profile_id'], vocabulary_id=batch.vocabulary_id,
            source_asset=row['source_asset'], batch_asset=row['batch_asset'])
        _require_match(data, expected, 'committed source provenance mismatch')
        _require_match(metadata, dict(expected, frame_id=f'{source.key.sensor_id}:{source.key.frame_index}',
            sim_time_s=source.sim_time_s, coordinate_convention=source.coordinate_convention,
            depth_convention=source.depth_convention, completion=batch.completion,
            cap_reached=batch.cap_reached), 'prediction source provenance mismatch')
        if (source.key.episode_id != config['episode_id'] or source.key.sensor_id != config['primary_sensor_id']
                or source.clock_domain != config['clock_domain'] or batch.vocabulary_id != config['vocabulary_id']):
            raise ValueError('source/profile/vocabulary mismatch')
        key = [source.key.episode_id, source.key.sensor_id, source.key.frame_index,
               config['detector_profile_id'], batch.vocabulary_id]
        if row['batch_key'] != _canonical(key):
            raise ValueError('committed source batch key mismatch')
        height, width = source.rgb.shape[:2]
        _require_match(frame, dict(frame_id=metadata['frame_id'], frame_index=source.key.frame_index,
            capture_monotonic_ns=source.capture_monotonic_ns, source_sha256=row['source_asset'],
            geometry_hash=source.geometry_hash, height=height, width=width), 'exact source frame binding mismatch')
        status = batch.completion
        if status == 'unknown' or batch.cap_reached or (status == 'failed' and batch.detections):
            status = 'partial'
        if frame['status'] != status or data.get('completion') != batch.completion or data.get('cap_reached') != batch.cap_reached:
            raise ValueError('committed source completion mismatch')
        ids = [d.detection_id for d in batch.detections]
        if [obj.get('id') for obj in frame['objects']] != ids or set(data.get('detections', {})) != set(ids):
            raise ValueError('frame-local detection support/order mismatch')
        views = connection.execute('SELECT v.event_id,v.data FROM views v JOIN events e ON e.event_id=v.event_id '
            'WHERE e.batch_key=?', (row['batch_key'],)).fetchall()
        by_event = {view['event_id']: view for view in views}
        ordered_events = data.get('projected_event_ids', [])
        if len(set(ordered_events)) != len(ordered_events) or set(by_event) != set(ordered_events):
            raise ValueError('projected observation support mismatch')
        observations = []
        for event_id in ordered_events:
            view = _json(by_event[event_id]['data'])
            _require_match(view, expected, 'projected source provenance mismatch')
            raw = _asset(root, connection, view['observation_asset'])
            item = loads(raw)
            if not isinstance(item, ObjectObservation):
                raise ValueError('typed ObjectObservation asset required')
            _require_match(view, dict(detection_id=item.detection_id, evidence_kind=item.evidence_kind,
                raw_label=item.raw_label, category=item.category, score=item.score,
                camera_position=list(item.camera_position)), 'projected observation provenance mismatch')
            observations.append(item)
            assets[view['observation_asset']] = _sha(raw)
        validate_object_observations(source, batch, tuple(observations))
        if len({item.detection_id for item in observations}) != len(observations):
            raise ValueError('one projected observation per detection required')
        for obj, detection in zip(frame['objects'], batch.detections):
            if set(obj)-{'id','label','score','bbox','mask','identity'}:
                raise ValueError('unsupported prediction detection fields')
            refs = data['detections'][detection.detection_id]
            raw = _asset(root, connection, refs['mask_asset'])
            mask = np.load(io.BytesIO(raw), allow_pickle=False)
            if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or not np.array_equal(mask, detection.mask):
                raise ValueError('committed source mask mismatch')
            y, x = np.nonzero(mask)
            box = [int(x.min()), int(y.min()), int(x.max())+1, int(y.max())+1]
            _require_match(obj, dict(label=detection.category or detection.raw_label, score=detection.score,
                bbox=box), 'prediction detection content mismatch')
            if refs.get('crop_bbox_xyxy') != box or _mask_bytes(prediction_path, obj.get('mask')) != raw:
                raise ValueError('exported prediction mask/source mismatch')
            relative = obj['mask']['path']
            if relative in mask_files and mask_files[relative] != raw:
                raise ValueError('conflicting mask path')
            mask_files[relative] = raw
            assets[refs['mask_asset']] = _sha(raw)
        assets.update({row['source_asset']: _sha(source_raw), row['batch_asset']: _sha(batch_raw)})
        result.append((source, tuple(observations), frame))
    return config, result, assets, mask_files, logical_digest


def _run(config, inputs, *, name, recipe, visual):
    engine = AssociationEngine(config['episode_id'], association_mode='geometry_appearance' if visual else 'geometry',
                               association_recipe=recipe)
    identity_map, frames, diagnostics = {}, [], []
    elapsed_ns, unresolved, ambiguous = 0, 0, 0
    for source, observations, original in inputs:
        adapted = tuple(AssociationObservation(source.key.episode_id, source.key.frame_index,
            item.detection_id, config['floor_id'], item.evidence_kind, item.category or item.raw_label,
            item.score, item.points_world, item.camera_position, source_geometry_sha256=item.geometry_hash,
            visual_embedding=item.appearance.vector if visual and item.appearance is not None else None)
            for item in observations)
        started = time.perf_counter_ns()
        engine.advance_time(source.capture_monotonic_ns/1e9)
        assigned = engine.ingest(adapted, now_s=source.capture_monotonic_ns/1e9)
        batch_ns = time.perf_counter_ns()-started
        elapsed_ns += batch_ns
        endpoints = {}
        assignments = []
        for item, object_id in zip(observations, assigned.object_ids):
            if object_id is not None and object_id not in identity_map:
                identity_map[object_id] = f'replay:{name}:{len(identity_map)+1:06d}'
            identity = None if object_id is None else identity_map[object_id]
            endpoints[item.detection_id] = identity
            assignments.append(dict(detection_id=item.detection_id, evidence_kind=item.evidence_kind,
                engine_object_id=object_id, online_identity=identity, final_identity=identity))
        frame = copy.deepcopy(original)
        frame['objects'] = [dict({key: value for key, value in obj.items() if key != 'identity'},
            **({'identity': endpoints[obj['id']]} if endpoints[obj['id']] is not None else {}))
            for obj in original['objects'] if obj['id'] in endpoints]
        frames.append(frame)
        unresolved += sum(value is None for value in endpoints.values())
        ambiguous += len(assigned.ambiguous_indices)
        diagnostics.append(dict(frame_id=frame['frame_id'], capture_monotonic_ns=source.capture_monotonic_ns,
            projected_observations=len(observations), detector_outputs=len(original['objects']),
            projection_losses=len(original['objects'])-len(observations),
            assignments=assignments, ambiguous_indices=list(assigned.ambiguous_indices),
            association_diagnostics=dict(assigned.diagnostics), elapsed_ns=batch_ns,
            cumulative_elapsed_ns=elapsed_ns, active_tracks=len(assigned.tracks),
            fused_cloud_points=sum(track.point_count for track in assigned.tracks.values()),
            largest_fused_cloud_points=max((track.point_count for track in assigned.tracks.values()), default=0),
            fused_cloud_cap_points_per_object=4096, input_cloud_points=sum(len(o.points_world) for o in observations)))
    return frames, dict(name=name, association_mode=engine.association_mode, recipe=recipe.durable_dict(),
        visual=visual, identity_semantics='none' if unresolved else 'online',
        online_and_final_equal=True, final_aliases={}, unresolved_observations=unresolved,
        ambiguous_observations=ambiguous, generated_identities=len(identity_map),
        identity_unavailable_reason='unresolved projected observations; no IDs fabricated' if unresolved else None,
        total_association_elapsed_ns=elapsed_ns, per_frame=diagnostics)


def replay_association_quality(objects, *, predictions, out):
    """Write derived memory predictions; this API deliberately accepts no GT."""
    root, prediction_path, output = Path(objects).resolve(), Path(predictions).absolute(), Path(out).absolute()
    if output.resolve().is_relative_to(root) or output.resolve().is_relative_to(prediction_path.parent.resolve()):
        raise ValueError('output must be outside both source inputs')
    if output.is_symlink() or output.exists():
        raise FileExistsError('replay output must be a new directory')
    prediction_raw = _read(prediction_path)
    document = _json(prediction_raw)
    _validate_document(document, prediction=True)
    with _snapshot_connection(root) as connection:
        config, inputs, asset_hashes, masks, logical_digest = _inputs(root, prediction_path, document, connection)
    features = [item.appearance for _, items, _ in inputs for item in items if item.appearance is not None]
    for feature in features[1:]:
        features[0].require_compatible(feature)
    projected = sum(len(items) for _, items, _ in inputs)
    detector = sum(len(frame['objects']) for _, _, frame in inputs)
    visual_available = bool(features)
    modes = [('legacy_geometry', AssociationRecipe(), False),
             ('conceptgraphs_spatial', AssociationRecipe(mode='conceptgraphs'), False)]
    if visual_available:
        modes += [('legacy_geometry_appearance', AssociationRecipe(), True),
                  ('conceptgraphs_visual', AssociationRecipe(mode='conceptgraphs'), True)]
    summary = dict(schema_version=1, frames=len(inputs), detector_outputs=detector,
        projected_observations=projected, projection_losses=detector-projected,
        scope='all retained frames; detections with original typed ObjectObservation assets only',
        visual_comparison=dict(available=visual_available, original_features=len(features),
            feature_space=None if not features else features[0].space_id,
            reason=None if features else 'No appearance features in the original committed ObjectObservation assets; no encoder invoked.'),
        input_predictions_sha256=_sha(prediction_raw), ledger_logical_sha256=logical_digest,
        verified_input_assets=asset_hashes, input_source_metadata=copy.deepcopy(document['provenance']['source_metadata']),
        source_ledger=str(root), source_predictions=str(prediction_path), runs={},
        limitations=['No ground truth read by replay; quality metrics require separate offline evaluation.',
            'Online endpoints recorded before later assignments; no post-hoc merging or aliases.',
            'Cumulative association wall time excludes asset decoding/output and is not native throughput.',
            'Original detections lacking projection excluded from memory scope; every source frame retained.',
            'Only original ObjectObservation appearance is used; later attachment timing is not reconstructed.'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='association-replay-', dir=output.parent) as temporary:
        stage = Path(temporary)
        for name, recipe, visual in modes:
            frames, diagnostics = _run(config, inputs, name=name, recipe=recipe, visual=visual)
            directory = stage/name
            directory.mkdir()
            for relative, raw in masks.items():
                path = directory/relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            derived = dict(schema_version=1, binding=copy.deepcopy(document['binding']),
                provenance=dict(kind=document['provenance']['kind'],
                    description='Fixed-input read-only association replay; projected-memory scope; every original frame retained.',
                    association_recipe=recipe.durable_dict(), appearance_enabled=visual,
                    scope=summary['scope'], unresolved_observations=diagnostics['unresolved_observations'],
                    identity_unavailable_reason=diagnostics['identity_unavailable_reason'],
                    online_and_final_equal=True, original_detector_outputs=detector,
                    projected_observations=projected, projection_losses=detector-projected),
                identity_semantics=diagnostics['identity_semantics'], score_floor=document['score_floor'],
                max_detections=document['max_detections'], final_aliases={}, frames=frames)
            _validate_document(derived, prediction=True)
            raw = (_canonical(derived)+'\n').encode()
            (directory/'predictions.json').write_bytes(raw)
            (directory/'diagnostics.json').write_text(_canonical(diagnostics)+'\n')
            summary['runs'][name] = dict(predictions=str(output/name/'predictions.json'),
                predictions_sha256=_sha(raw), diagnostics=str(output/name/'diagnostics.json'),
                unresolved_observations=diagnostics['unresolved_observations'],
                ambiguous_observations=diagnostics['ambiguous_observations'],
                identity_semantics=diagnostics['identity_semantics'],
                total_association_elapsed_ns=diagnostics['total_association_elapsed_ns'])
        (stage/'replay-manifest.json').write_text(_canonical(summary)+'\n')
        if output.exists() or output.is_symlink():
            raise FileExistsError('replay output appeared during preparation')
        stage.rename(output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', required=True, help='Closed original committed object ledger directory')
    parser.add_argument('--predictions', required=True, help='Original read-only quality-export predictions.json')
    parser.add_argument('--out', required=True, help='New output directory outside the inputs')
    args = parser.parse_args()
    print(_canonical(replay_association_quality(args.objects, predictions=args.predictions, out=args.out)))


if __name__ == '__main__':
    main()
