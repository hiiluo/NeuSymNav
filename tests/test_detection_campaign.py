import importlib.util
from pathlib import Path
import pytest
import numpy as np

spec=importlib.util.spec_from_file_location('campaign',Path(__file__).parents[1]/'tools/evaluate_detection_campaign.py')
m=importlib.util.module_from_spec(spec)

def tool():
    spec.loader.exec_module(m)
    return m

def data():
    return [dict(frame_id='f',gt=[dict(id='g',label='chair',bbox=[0,0,2,2])],pred=[
        dict(id='p',label='chair',bbox=[0,0,2,2],score=.5),
        dict(id='d',label='chair',bbox=[0,0,2,2],score=.4),
        dict(id='w',label='table',bbox=[0,0,2,2],score=.9)])]

def test_prefix_pr_matches_official_scorer_and_retains_all_gt():
    from neusymnav.evaluation.detection_quality import evaluate_detection
    result=tool().analyze(data(),thresholds=[.25,.5,.6])
    for row in result['global_pr']:
        point=evaluate_detection(data(),confidence_threshold=row['threshold'])['operating_point']
        assert {k:row[k] for k in ('tp','fp','fn','precision','recall','f1')}=={k:point[k] for k in ('tp','fp','fn','precision','recall','f1')}
    assert result['support']['ground_truth']==1
    assert result['support']['frames']==1

def test_calibration_does_not_suppress_prediction_only_classes():
    result=tool().analyze(data(),thresholds=[.25,.5,.6])
    assert result['calibration']['per_class']['table']['threshold']==result['calibration']['global_threshold']
    assert result['calibration']['per_class']['table']['reason']=='insufficient_gt_or_tp_support'
    assert result['calibration']['scope']=='diagnostic_in_sample_not_held_out'

def test_numpy_masks_match_list_mask_reference():
    from neusymnav.evaluation.detection_quality import evaluate_detection
    frames=data()
    for obj in frames[0]['gt']+frames[0]['pred']:obj['mask']=np.ones((2,2),bool)
    result=tool().analyze(frames,thresholds=[.25])
    for obj in frames[0]['gt']+frames[0]['pred']:obj['mask']=obj['mask'].tolist()
    expected=evaluate_detection(frames)
    assert result['mask_ap']['ap50_95']==pytest.approx(expected['mask_ap']['ap50_95'])
    assert result['bbox_ap']['ap50_95']==pytest.approx(expected['bbox_ap']['ap50_95'])

def test_empty_frames_and_inclusive_threshold():
    frames=data()+[dict(frame_id='missing',gt=[dict(id='g',label='chair',bbox=[0,0,2,2])],pred=[])]
    result=tool().analyze(frames,thresholds=[.5])
    assert (result['global_pr'][0]['tp'],result['global_pr'][0]['fn'])==(1,1)
    assert result['support']['frames']==2

@pytest.mark.parametrize('thresholds',[[],[float('nan')],[-.1],[1.1],[True]])
def test_invalid_thresholds_fail(thresholds):
    with pytest.raises(ValueError):tool().analyze(data(),thresholds=thresholds)
