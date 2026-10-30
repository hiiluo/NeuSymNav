"""Real source validation and matching; only expensive model inference is doubled."""
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from neusymnav.contracts.observations import AppearanceBatch, AppearanceFeature
from neusymnav.contracts.serialization import loads
from test_association_replay import prepared
from test_quality_export import file_hashes


@pytest.fixture
def replay_module(monkeypatch):
    path = Path(__file__).resolve().parents[1]/'tools/replay_visual_association.py'
    spec = importlib.util.spec_from_file_location('visual_replay', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Encoder:
        space_metadata = {'model_name': 'test-real-source-double', 'transform': 'fixture'}
        def encode(self, source, batch):
            # Inference sees original RGB and exact original typed masks.
            assert source.rgb.shape == (32,32,3)
            assert batch.source == source.key
            return AppearanceBatch(source.key, source.geometry_hash, {
                detection.detection_id: AppearanceFeature('fixture-space', np.array([1.,0.]))
                for detection in batch.detections})
        def close(self):
            pass

    monkeypatch.setattr(module, '_encoder', lambda config: (Encoder(), {'fixture': 'pinned'}))
    return module


def test_visual_replay_retains_source_features_and_assigned_scope(tmp_path, replay_module):
    root, predictions = prepared(tmp_path)
    before = file_hashes(root), file_hashes(predictions.parent)
    result = replay_module.replay_visual_association(root, predictions=predictions,
        appearance_config='fixture', out=tmp_path/'visual')
    assert (file_hashes(root), file_hashes(predictions.parent)) == before
    assert (result['frames'], result['detector_outputs'], result['projected_observations'],
            result['extracted_features']) == (2,2,2,2)
    assert set(result['runs']) == {'legacy_geometry','conceptgraphs_spatial',
        'legacy_geometry_appearance','conceptgraphs_visual'}
    assert result['runs']['conceptgraphs_visual']['association_totals']['visual_pairs'] == 1
    assert result['runs']['conceptgraphs_visual']['association_totals']['fallback_rows'] == 0
    for run in result['runs'].values():
        doc = json.loads(Path(run['assigned_predictions']).read_text())
        assert len(doc['frames']) == 2
        assert [len(frame['objects']) for frame in doc['frames']] == [1,1]
        assert run['assigned_observations'] == 2
    cache = json.loads((tmp_path/'visual/features/manifest.json').read_text())
    assert cache['frames'][0]['binding']['capture_monotonic_ns'] == 1_000_000_000
    feature = loads((tmp_path/'visual/features'/cache['frames'][0]['path']).read_bytes())
    assert set(feature.features) == {'0'}
    assert feature.features['0'].space_id == 'fixture-space'
    # Cache reuse preserves vectors/partitions without inference or any GT inlet.
    def fail_encode(*args):
        raise AssertionError('cache must bypass inference')
    encoder, recipe = replay_module._encoder('fixture')
    encoder.encode = fail_encode
    replay_module._encoder = lambda config: (encoder, recipe)
    repeated = replay_module.replay_visual_association(root, predictions=predictions,
        appearance_config='fixture', feature_cache=tmp_path/'visual/features', out=tmp_path/'cached')
    for mode in result['runs']:
        assert repeated['runs'][mode]['partition'] == result['runs'][mode]['partition']


@pytest.mark.parametrize('failure', ['missing','wrong-source','wrong-geometry'])
def test_visual_missing_or_misbound_features_fail_closed(tmp_path, replay_module, failure):
    root, predictions = prepared(tmp_path)
    encoder, recipe = replay_module._encoder('fixture')
    original = encoder.encode
    def encode(source, batch):
        value = original(source, batch)
        if failure == 'missing':
            return replace(value, features={})
        if failure == 'wrong-source':
            return replace(value, source=replace(value.source, frame_index=999))
        return replace(value, geometry_hash='0'*64)
    encoder.encode = encode
    replay_module._encoder = lambda config: (encoder, recipe)
    with pytest.raises(ValueError, match='feature|appearance'):
        replay_module.replay_visual_association(root, predictions=predictions,
            appearance_config='fixture', out=tmp_path/'visual')
    assert not (tmp_path/'visual').exists()


def test_visual_replay_original_identities_and_unprojected_detections_are_not_matching_inputs(tmp_path, replay_module):
    root, predictions = prepared(tmp_path, invalid_depth=True)
    doc = json.loads(predictions.read_text())
    for frame in doc['frames']:
        frame['objects'][0]['identity'] = 'untrusted-original-id'
    predictions.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='projected'):
        replay_module.replay_visual_association(root, predictions=predictions,
            appearance_config='fixture', out=tmp_path/'visual')


def test_original_identity_changes_do_not_change_visual_partition(tmp_path, replay_module):
    root, predictions = prepared(tmp_path)
    first = replay_module.replay_visual_association(root, predictions=predictions,
        appearance_config='fixture', out=tmp_path/'first')
    doc = json.loads(predictions.read_text())
    doc['final_aliases'] = {'arbitrary-alias': 'untrusted-id'}
    for frame in doc['frames']:
        frame['objects'][0]['identity'] = 'untrusted-id'
    predictions.write_text(json.dumps(doc))
    second = replay_module.replay_visual_association(root, predictions=predictions,
        appearance_config='fixture', out=tmp_path/'second')
    for mode in first['runs']:
        assert first['runs'][mode]['partition'] == second['runs'][mode]['partition']
        assert 'untrusted-id' not in Path(second['runs'][mode]['assigned_predictions']).read_text()


@pytest.mark.parametrize('corrupt', ['binding','payload','recipe'])
def test_cached_features_reject_changed_binding_or_payload(tmp_path, replay_module, corrupt):
    root, predictions = prepared(tmp_path)
    replay_module.replay_visual_association(root, predictions=predictions,
        appearance_config='fixture', out=tmp_path/'first')
    directory = tmp_path/'first/features'
    manifest_path = directory/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if corrupt == 'binding':
        manifest['frames'][0]['binding']['capture_monotonic_ns'] += 1
    elif corrupt == 'recipe':
        manifest['encoder_recipe']['fixture'] = 'unbound'
    else:
        (directory/manifest['frames'][0]['path']).write_text('corrupt')
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='cached appearance'):
        replay_module.replay_visual_association(root, predictions=predictions,
            appearance_config='fixture', feature_cache=directory, out=tmp_path/'second')
    assert not (tmp_path/'second').exists()


def test_assigned_derivative_excludes_only_explicit_projection_and_ambiguity_losses(tmp_path, replay_module):
    from test_projection import scene, batch
    from test_quality_export import run_export
    from neusymnav.objects.store import ObjectOwner
    from neusymnav.perception.projector import Projector
    from neusymnav.recording.writer import ReplayWriter

    sources = [replace(scene(index), clock_domain='replay:fixture') for index in range(3)]
    sources[2] = replace(sources[2], valid_depth=np.zeros((32,32), dtype=bool))
    writer = ReplayWriter(tmp_path/'recording')
    for source in sources:
        writer.append(source)
    writer.close()
    root = tmp_path/'ledger'
    with ObjectOwner(root, episode_id='episode', primary_sensor_id='rgbd', floor_id='f0',
        detector_profile_id='fixture-v1', vocabulary_id='v1', clock_domain='replay:fixture',
        now_ns=lambda: 2_000_000_000) as owner:
        for index, source in enumerate(sources):
            detections = batch(source, boxes=((12,12,20,20),)*(2 if index == 0 else 1))
            owner.commit(source, detections, Projector(min_points=1).project(source, detections))
    taxonomy = tmp_path/'taxonomy.json'
    taxonomy.write_text(json.dumps(dict(schema_version=1, vocabulary_id='v1', categories=['chair'],
        aliases={}, provenance='synthetic fixture')))
    exported = run_export(tmp_path, (root, tmp_path/'recording/manifest.json', taxonomy))
    # The replay must not open even a neighboring file named like GT.
    (Path(exported['predictions']).parent/'ground-truth.json').write_text('invalid GT JSON; forbidden inlet')
    result = replay_module.replay_visual_association(root, predictions=exported['predictions'],
        appearance_config='fixture', out=tmp_path/'visual')
    assert (result['frames'], result['detector_outputs'], result['projected_observations'],
            result['extracted_features']) == (3,4,3,4)
    for run in result['runs'].values():
        assert run['assigned_observations'] == 2
        assert run['unresolved_observations'] == 1
        assert [item['reason'] for item in run['exclusions']] == [
            'unresolved_association','no_original_projected_observation']
        all_projected = json.loads(Path(run['predictions']).read_text())
        assigned = json.loads(Path(run['assigned_predictions']).read_text())
        assert [len(frame['objects']) for frame in all_projected['frames']] == [2,1,0]
        assert [len(frame['objects']) for frame in assigned['frames']] == [2,0,0]
        assert len(assigned['frames']) == 3 and assigned['identity_semantics'] == 'online'
