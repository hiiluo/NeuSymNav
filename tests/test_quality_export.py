"""Read-only ledger export with genuine committed contracts, synthetic inputs."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sqlite3

import numpy as np
from PIL import Image
import pytest

from test_projection import batch, scene
from neusymnav.objects.store import ObjectOwner
from neusymnav.perception.projector import Projector
from neusymnav.recording.writer import ReplayWriter
from neusymnav.evaluation.quality_dataset import load_quality_pair


def exporter(*args, **kwargs):
    from neusymnav.evaluation.quality_export import export_quality
    return export_quality(*args, **kwargs)


def make_ledger(tmp_path, *, empty=False, invalid_depth=False, count=2, merge=False):
    root = tmp_path / 'ledger'
    sources = [replace(scene(i, shift=i*3 if merge else 0), clock_domain='replay:fixture')
               for i in range(count)]
    if invalid_depth:
        sources = [replace(source, valid_depth=np.zeros_like(source.valid_depth)) for source in sources]
    writer = ReplayWriter(tmp_path / 'recording')
    for source in sources:
        assert writer.append(source)
    assert writer.close()['complete']
    owner = ObjectOwner(root, episode_id='episode', primary_sensor_id='rgbd', floor_id='f0',
                        detector_profile_id='fixture-v1', vocabulary_id='v1',
                        clock_domain='replay:fixture', now_ns=lambda:2_000_000_000)
    for source in reversed(sources):
        detection_batch = batch(source, boxes=() if empty else ((12,12,20,20),))
        owner.commit(source, detection_batch, Projector(min_points=1).project(source, detection_batch))
    if merge:
        owner.merge(*owner.snapshot().objects)
    owner.close()
    taxonomy = tmp_path / 'taxonomy.json'
    taxonomy.write_text(json.dumps(dict(schema_version=1, vocabulary_id='v1', categories=['chair'],
                                       aliases={}, provenance='synthetic test taxonomy')))
    return root, tmp_path / 'recording' / 'manifest.json', taxonomy


def run_export(tmp_path, assets, **kwargs):
    root, recording, taxonomy = assets
    return exporter(root, scene_id='synthetic-test-scene', recording_manifest=recording,
                    taxonomy_path=taxonomy, out=tmp_path/'export', source_kind='synthetic', **kwargs)


def file_hashes(root):
    return {str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file()}


def test_exports_ordered_committed_detection_masks_previews_and_unannotated_gt(tmp_path):
    assets = make_ledger(tmp_path)
    before = file_hashes(assets[0])
    result = run_export(tmp_path, assets, max_frames=1)
    assert file_hashes(assets[0]) == before
    assert (result['frames'], result['detections'], result['total_committed_batches']) == (1,1,2)
    pred = json.loads(Path(result['predictions']).read_text())
    gt = json.loads(Path(result['ground_truth_template']).read_text())
    assert pred['frames'][0]['frame_index'] == 0
    assert pred['frames'][0]['objects'][0]['bbox'] == [12,12,20,20]
    assert pred['frames'][0]['objects'][0]['score'] == .9
    assert pred['identity_semantics'] == 'final_canonical_only'
    assert pred['score_floor'] is None and pred['max_detections'] is None
    assert pred['binding']['recording_sha256'] == hashlib.sha256(assets[1].read_bytes()).hexdigest()
    assert pred['binding']['taxonomy_sha256'] == hashlib.sha256(assets[2].read_bytes()).hexdigest()
    assert gt['frames'][0]['annotated'] is False and gt['frames'][0]['objects'] == []
    assert 'geometry_objects' not in pred and 'geometry_objects' not in gt
    mask_ref = pred['frames'][0]['objects'][0]['mask']
    mask_path = Path(result['predictions']).parent / mask_ref['path']
    assert hashlib.sha256(mask_path.read_bytes()).hexdigest() == mask_ref['sha256']
    assert np.load(mask_path, allow_pickle=False).dtype == np.bool_
    previews = sorted(Path(result['previews']).glob('*.png'))
    assert len(previews) == 2
    assert all(Image.open(path).size == (32,32) for path in previews)
    with pytest.raises(ValueError, match='unannotated'):
        load_quality_pair(result['ground_truth_template'], result['predictions'])


def test_independent_annotation_can_load_exported_predictions(tmp_path):
    result = run_export(tmp_path, make_ledger(tmp_path), max_frames=1)
    gt_path = Path(result['ground_truth_template'])
    gt = json.loads(gt_path.read_text())
    gt['frames'][0].update(annotated=True, objects=[dict(id='independent-gt', label='chair', bbox=[11,11,21,21])])
    annotated = gt_path.with_name('independently-annotated.json')
    annotated.write_text(json.dumps(gt))
    pair = load_quality_pair(annotated, result['predictions'])
    assert len(pair['frames'][0]['pred']) == 1
    assert pair['frames'][0]['pred'][0]['identity']
    assert pair['frames'][0]['gt'][0]['bbox'] == [11,11,21,21]


def test_unprojectable_detection_is_exported_without_invented_identity(tmp_path):
    result = run_export(tmp_path, make_ledger(tmp_path, invalid_depth=True))
    doc = json.loads(Path(result['predictions']).read_text())
    assert result['detections'] == 2 and result['identity_observations'] == 0
    assert all('identity' not in frame['objects'][0] for frame in doc['frames'])


def test_empty_batches_are_not_filtered(tmp_path):
    result = run_export(tmp_path, make_ledger(tmp_path, empty=True))
    doc = json.loads(Path(result['predictions']).read_text())
    assert result['frames'] == 2 and result['detections'] == 0
    assert all(frame['status'] == 'complete' and frame['objects'] == [] for frame in doc['frames'])


def test_merged_identities_are_explicitly_final_canonical_only(tmp_path):
    result = run_export(tmp_path, make_ledger(tmp_path, merge=True))
    doc = json.loads(Path(result['predictions']).read_text())
    identities = {frame['objects'][0]['identity'] for frame in doc['frames']}
    assert len(identities) == 1 and len(doc['final_aliases']) == 1
    assert doc['identity_semantics'] == 'final_canonical_only'


@pytest.mark.parametrize('kind', ['source_asset','batch_asset','mask_asset'])
def test_corrupt_asset_is_rejected_without_ledger_mutation(tmp_path, kind):
    assets = make_ledger(tmp_path)
    with sqlite3.connect(assets[0]/'objects.sqlite3') as conn:
        if kind == 'mask_asset':
            ref = json.loads(conn.execute('SELECT data FROM batches LIMIT 1').fetchone()[0])['detections']['0']['mask_asset']
        else:
            ref = conn.execute(f'SELECT {kind} FROM batches LIMIT 1').fetchone()[0]
    (assets[0]/'assets'/ref).write_bytes(b'corrupt')
    before = file_hashes(assets[0])
    with pytest.raises(ValueError, match='checksum'):
        run_export(tmp_path, assets)
    assert file_hashes(assets[0]) == before


@pytest.mark.parametrize('limit', [0,-1,1001,True,1.5])
def test_invalid_limits_rejected_before_output(tmp_path, limit):
    with pytest.raises(ValueError):
        run_export(tmp_path, make_ledger(tmp_path), max_frames=limit)
    assert not (tmp_path/'export').exists()


def test_nonempty_output_is_never_overwritten(tmp_path):
    assets = make_ledger(tmp_path)
    output = tmp_path/'export'; output.mkdir(); (output/'keep').write_bytes(b'keep')
    with pytest.raises(FileExistsError):
        run_export(tmp_path, assets)
    assert (output/'keep').read_bytes() == b'keep'


def test_output_inside_ledger_is_rejected(tmp_path):
    root, recording, taxonomy = make_ledger(tmp_path)
    with pytest.raises(ValueError):
        exporter(root, scene_id='test', recording_manifest=recording, taxonomy_path=taxonomy,
                 out=root/'export', source_kind='synthetic')
    assert not (root/'export').exists()


def test_recording_must_bind_selected_committed_source(tmp_path):
    assets = make_ledger(tmp_path)
    # Another valid recording has the same episode but different capture pose.
    other = ReplayWriter(tmp_path/'other')
    assert other.append(replace(scene(), clock_domain='replay:fixture', calibration_id='different'))
    assert other.close()['complete']
    with pytest.raises(ValueError, match='recording'):
        run_export(tmp_path, (assets[0], tmp_path/'other'/'manifest.json', assets[2]))


def test_taxonomy_vocabulary_must_match_ledger(tmp_path):
    assets = make_ledger(tmp_path)
    doc = json.loads(assets[2].read_text()); doc['vocabulary_id'] = 'other'
    assets[2].write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='vocabulary'):
        run_export(tmp_path, assets)


def test_replay_clock_cannot_be_labeled_recorded_by_default(tmp_path):
    root, recording, taxonomy = make_ledger(tmp_path)
    with pytest.raises(ValueError, match='synthetic'):
        exporter(root, scene_id='test', recording_manifest=recording, taxonomy_path=taxonomy, out=tmp_path/'export')


def test_active_owner_is_rejected_without_source_mutation(tmp_path):
    assets = make_ledger(tmp_path)
    with ObjectOwner(assets[0], episode_id='episode', primary_sensor_id='rgbd', floor_id='f0',
                     detector_profile_id='fixture-v1', vocabulary_id='v1',
                     clock_domain='replay:fixture', now_ns=lambda:2_000_000_000):
        before = file_hashes(assets[0])
        with pytest.raises(ValueError, match='active ledger'):
            run_export(tmp_path, assets)
        assert file_hashes(assets[0]) == before
        assert not (tmp_path/'export').exists()


def test_uncheckpointed_wal_is_rejected_instead_of_ignored(tmp_path):
    assets = make_ledger(tmp_path)
    with sqlite3.connect(assets[0]/'objects.sqlite3') as connection:
        connection.execute("INSERT INTO metadata VALUES ('uncheckpointed-test','committed')")
        connection.commit()
        assert (assets[0]/'objects.sqlite3-wal').stat().st_size > 0
        before = file_hashes(assets[0])
        with pytest.raises(ValueError, match='checkpointed'):
            run_export(tmp_path, assets)
        assert file_hashes(assets[0]) == before
        assert not (tmp_path/'export').exists()
