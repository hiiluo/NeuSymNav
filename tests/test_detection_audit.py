"""Hand-derived diagnostics must not change the class-aware denominator."""
import importlib.util
import json
from pathlib import Path

import pytest

from test_quality_export import make_ledger, run_export, file_hashes


def module():
    path = Path(__file__).resolve().parents[1] / 'tools/audit_detection_errors.py'
    spec = importlib.util.spec_from_file_location('detection_audit', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def obj(id, label='chair', box=None, score=None):
    return dict(id=id, label=label, bbox=box or [0, 0, 2, 2],
                **({} if score is None else dict(score=score)))


def test_wrong_class_keeps_raw_fp_fn_and_separate_confusion():
    result = module().diagnose_frames([dict(frame_id='f', gt=[obj('g')],
        pred=[obj('p', 'table', score=.9)])])
    assert [result['raw_metrics']['operating_point'][k] for k in ('tp','fp','fn')] == [0,1,1]
    assert result['diagnostics'][0]['pairs'][0]['kind'] == 'label_confusion'
    assert result['rankings']['label_confusions'] == [dict(gt_label='chair', pred_label='table', count=1)]


def test_duplicate_missing_and_empty_frames_keep_every_observation():
    frames = [dict(frame_id='f', gt=[obj('g')], pred=[obj('z', score=.8), obj('a', score=.9)]),
              dict(frame_id='missing', gt=[obj('g2')], pred=[]),
              dict(frame_id='empty', gt=[], pred=[])]
    result = module().diagnose_frames(frames)
    assert [result['raw_metrics']['operating_point'][k] for k in ('tp','fp','fn')] == [1,1,1]
    assert result['raw_metrics']['support']['frames'] == 3
    by_id = {frame['frame_id']: frame for frame in result['diagnostics']}
    assert by_id['f']['unmatched_predictions'][0]['kind'] == 'duplicate_overlap'
    assert by_id['missing']['unmatched_gt'] == ['g2']
    assert module().diagnose_frames(list(reversed(frames))) == result


def test_inclusive_iou_score_and_localization_boundaries():
    frames = [dict(frame_id='f', gt=[obj('g')], pred=[obj('p', box=[0,0,4,2], score=.25)]),
              dict(frame_id='l', gt=[obj('g')], pred=[obj('p', box=[0,0,8,2], score=.9)]),
              dict(frame_id='below', gt=[obj('g')], pred=[obj('p', score=.249)])]
    result = module().diagnose_frames(frames, localization_iou=.25)
    assert [result['raw_metrics']['operating_point'][k] for k in ('tp','fp','fn')] == [1,1,2]
    by_id = {frame['frame_id']: frame for frame in result['diagnostics']}
    assert by_id['f']['pairs'][0]['iou'] == .5
    assert by_id['l']['pairs'][0]['kind'] == 'localization'
    assert by_id['below']['below_threshold_predictions'] == ['p']


def test_one_to_one_confidence_and_lexical_ties_cannot_consume_gt_twice():
    result = module().diagnose_frames([dict(frame_id='f', gt=[obj('b'),obj('a')],
        pred=[obj('z',score=.9),obj('a',score=.9),obj('x',score=.8)])])
    pairs = result['diagnostics'][0]['pairs']
    assert [(p['pred_id'],p['gt_id']) for p in pairs] == [('a','a'),('z','b')]
    assert len(result['diagnostics'][0]['unmatched_predictions']) == 1


def test_representatives_cover_confusions_and_duplicates_before_repeated_misses():
    frames = [dict(frame_id='many-misses', gt=[obj(str(i)) for i in range(8)], pred=[]),
        dict(frame_id='confusion',gt=[obj('g')],pred=[obj('p','table',score=.9)]),
        dict(frame_id='duplicate',gt=[obj('g')],pred=[obj('a',score=.9),obj('b',score=.8)])]
    report = module().diagnose_frames(frames)
    selected = module().select_representatives(report['diagnostics'], 2)
    assert {f['frame_id'] for f in selected} == {'confusion','duplicate'}


def prepared(tmp_path):
    assets = make_ledger(tmp_path)
    export = run_export(tmp_path, assets)
    gt_path = Path(export['ground_truth_template'])
    gt = json.loads(gt_path.read_text())
    for frame in gt['frames']:
        frame.update(annotated=True, objects=[dict(id='gt-1', label='chair', bbox=[12,12,20,20])])
    gt_path.write_text(json.dumps(gt))
    return assets[0], Path(export['predictions']), gt_path


def test_source_bound_audit_preserves_input_and_writes_local_images(tmp_path):
    root, pred, gt = prepared(tmp_path)
    before = (file_hashes(root), file_hashes(pred.parent))
    result = module().audit_detection_errors(root, predictions=pred, ground_truth=gt, out=tmp_path/'audit')
    assert result['raw_metrics']['operating_point']['tp'] == 2
    assert result['source_binding']['input_hashes']['gt']
    assert result['source_binding']['verified_source_assets']
    assert (tmp_path/'audit/index.html').is_file()
    assert list((tmp_path/'audit/images').glob('*.png'))
    assert before == (file_hashes(root), file_hashes(pred.parent))
    with pytest.raises(FileExistsError):
        module().audit_detection_errors(root, predictions=pred, ground_truth=gt, out=tmp_path/'audit')


@pytest.mark.parametrize('mutation', ['gt_binding','gt_source','prediction_content'])
def test_rejects_unbound_gt_or_modified_source_predictions_before_output(tmp_path, mutation):
    root, pred, gt = prepared(tmp_path)
    path = gt if mutation.startswith('gt') else pred
    doc = json.loads(path.read_text())
    if mutation == 'gt_binding': doc['binding']['episode_id'] = 'other'
    if mutation == 'gt_source': doc['frames'][0]['source_sha256'] = '0'*64
    if mutation == 'prediction_content': doc['frames'][0]['objects'][0]['label'] = 'table'
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        module().audit_detection_errors(root, predictions=pred, ground_truth=gt, out=tmp_path/'audit')
    assert not (tmp_path/'audit').exists()
