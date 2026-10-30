"""Fixed-source replay uses typed ledger evidence, never original identities or GT."""

import importlib.util
import json
from pathlib import Path

import pytest

from test_quality_export import file_hashes, make_ledger, run_export
from neusymnav.evaluation.quality_dataset import _validate_document


def replay(*args, **kwargs):
    path = Path(__file__).resolve().parents[1] / 'tools/replay_association_quality.py'
    spec = importlib.util.spec_from_file_location('association_quality_replay', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.replay_association_quality(*args, **kwargs)


def prepared(tmp_path, **kwargs):
    assets = make_ledger(tmp_path, **kwargs)
    exported = run_export(tmp_path, assets)
    return assets[0], Path(exported['predictions'])


@pytest.mark.parametrize('field,value', [('source_sha256','0'*64), ('geometry_hash','1'*64),
                                       ('capture_monotonic_ns',987654321)])
def test_rejects_source_mismatch(tmp_path, field, value):
    root, predictions = prepared(tmp_path)
    doc = json.loads(predictions.read_text())
    doc['frames'][0][field] = value
    predictions.write_text(json.dumps(doc))
    before = file_hashes(root)
    with pytest.raises(ValueError, match='source|order'):
        replay(root, predictions=predictions, out=tmp_path/'replay')
    assert file_hashes(root) == before
    assert not (tmp_path/'replay').exists()


def test_rejects_wrong_source_order_and_provenance(tmp_path):
    root, predictions = prepared(tmp_path)
    original = json.loads(predictions.read_text())
    doc = json.loads(predictions.read_text())
    doc['frames'].reverse()
    predictions.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='order'):
        replay(root, predictions=predictions, out=tmp_path/'replay')
    original['provenance']['source_metadata'][0]['calibration_id'] = 'wrong-calibration'
    predictions.write_text(json.dumps(original))
    with pytest.raises(ValueError, match='provenance'):
        replay(root, predictions=predictions, out=tmp_path/'replay')


def test_frame_local_detection_ids_are_replayed_once_per_frame_and_inputs_unchanged(tmp_path):
    root, predictions = prepared(tmp_path)
    source = json.loads(predictions.read_text())
    assert [f['objects'][0]['id'] for f in source['frames']] == ['0','0']
    before_ledger, before_export = file_hashes(root), file_hashes(predictions.parent)
    result = replay(root, predictions=predictions, out=tmp_path/'replay')
    assert file_hashes(root) == before_ledger
    assert file_hashes(predictions.parent) == before_export
    assert result['detector_outputs'] == result['projected_observations'] == 2
    for mode in ('legacy_geometry','conceptgraphs_spatial'):
        doc = json.loads(Path(result['runs'][mode]['predictions']).read_text())
        _validate_document(doc, prediction=True)
        assert doc['identity_semantics'] == 'online' and doc['final_aliases'] == {}
        assert len(doc['frames']) == 2
        identities = [f['objects'][0]['identity'] for f in doc['frames']]
        assert identities[0] == identities[1]
        assert identities[0].startswith('replay:')
        assert identities[0] != source['frames'][0]['objects'][0]['identity']
        for actual, original in zip(doc['frames'], source['frames']):
            assert actual['capture_monotonic_ns'] == original['capture_monotonic_ns']
            assert actual['objects'][0]['mask'] == original['objects'][0]['mask']
            ref = actual['objects'][0]['mask']['path']
            assert (Path(result['runs'][mode]['predictions']).parent/ref).read_bytes() == (predictions.parent/ref).read_bytes()
    assert result['visual_comparison']['available'] is False


def test_original_final_identities_are_never_used_to_seed_replay(tmp_path):
    root, predictions = prepared(tmp_path)
    doc = json.loads(predictions.read_text())
    for frame in doc['frames']:
        frame['objects'][0]['identity'] = 'untrusted-original-final-identity'
    doc['final_aliases'] = {'legacy-alias': 'untrusted-original-final-identity'}
    predictions.write_text(json.dumps(doc))
    result = replay(root, predictions=predictions, out=tmp_path/'replay')
    for run in result['runs'].values():
        assert 'untrusted-original-final-identity' not in Path(run['predictions']).read_text()


def test_ambiguous_projected_observations_remain_counted_without_fabricated_identity(tmp_path):
    from dataclasses import replace
    from test_projection import batch, scene
    from neusymnav.objects.store import ObjectOwner
    from neusymnav.perception.projector import Projector
    from neusymnav.recording.writer import ReplayWriter

    root = tmp_path/'ledger'
    sources = [replace(scene(index), clock_domain='replay:fixture') for index in range(2)]
    writer = ReplayWriter(tmp_path/'recording')
    for source in sources:
        writer.append(source)
    writer.close()
    with ObjectOwner(root, episode_id='episode', primary_sensor_id='rgbd', floor_id='f0',
                     detector_profile_id='fixture-v1', vocabulary_id='v1',
                     clock_domain='replay:fixture', now_ns=lambda:2_000_000_000) as owner:
        for index, source in enumerate(sources):
            detections = batch(source, boxes=((12,12,20,20),)*(2 if index == 0 else 1))
            owner.commit(source, detections, Projector(min_points=1).project(source, detections))
    taxonomy = tmp_path/'taxonomy.json'
    taxonomy.write_text(json.dumps(dict(schema_version=1, vocabulary_id='v1', categories=['chair'],
        aliases={}, provenance='synthetic test taxonomy')))
    exported = run_export(tmp_path, (root, tmp_path/'recording/manifest.json', taxonomy))
    result = replay(root, predictions=exported['predictions'], out=tmp_path/'replay')
    assert result['projected_observations'] == result['detector_outputs'] == 3
    for run in result['runs'].values():
        doc = json.loads(Path(run['predictions']).read_text())
        assert doc['identity_semantics'] == 'none'
        assert [len(f['objects']) for f in doc['frames']] == [2,1]
        assert 'identity' not in doc['frames'][1]['objects'][0]
        assert run['unresolved_observations'] == run['ambiguous_observations'] == 1
        diagnostics = json.loads(Path(run['diagnostics']).read_text())
        assert diagnostics['per_frame'][1]['assignments'][0]['online_identity'] is None


@pytest.mark.parametrize('options', [dict(empty=True),dict(invalid_depth=True)])
def test_retains_every_empty_or_projection_failed_frame(tmp_path, options):
    root, predictions = prepared(tmp_path, **options)
    result = replay(root, predictions=predictions, out=tmp_path/'replay')
    assert result['frames'] == 2 and result['projected_observations'] == 0
    assert result['projection_losses'] == (2 if options.get('invalid_depth') else 0)
    for run in result['runs'].values():
        doc = json.loads(Path(run['predictions']).read_text())
        assert len(doc['frames']) == 2
        assert all(f['objects'] == [] for f in doc['frames'])


def test_rejects_output_inside_inputs_and_existing_output(tmp_path):
    root, predictions = prepared(tmp_path)
    with pytest.raises(ValueError, match='outside'):
        replay(root, predictions=predictions, out=predictions.parent/'replay')
    output = tmp_path/'replay'
    output.mkdir()
    (output/'keep').write_bytes(b'preserve')
    with pytest.raises(FileExistsError):
        replay(root, predictions=predictions, out=output)
    assert (output/'keep').read_bytes() == b'preserve'


@pytest.mark.parametrize('mask_path', ['/tmp/untrusted.npy', '../outside.npy', 'predictions.json'])
def test_rejects_unsafe_mask_reference_paths(tmp_path, mask_path):
    root, predictions = prepared(tmp_path)
    doc = json.loads(predictions.read_text())
    doc['frames'][0]['objects'][0]['mask']['path'] = mask_path
    predictions.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='mask'):
        replay(root, predictions=predictions, out=tmp_path/'replay')
    assert not (tmp_path/'replay').exists()
