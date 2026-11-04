import copy
import pytest

from neusymnav.evaluation.graph_admission import evaluate

H = 'a' * 64

def data():
    return {'schema': 'graph-admission-v1', 'provenance': {k: H for k in ('frames_sha256', 'poses_sha256', 'detector_sha256', 'recipe_sha256', 'gt_sha256')}, 'iou_threshold': .5, 'frames': [
        {'id': 'f0', 'time_s': 0, 'scene': 's', 'gt': [{'id':'g1','box':[0,0,2,2], 'label':'chair', 'visibility':'visible'}, {'id':'g2','box':[3,0,5,2], 'label':'table', 'visibility':'visible'}], 'pred': [{'id':'p1','box':[0,0,2,2], 'label':'chair','scope':'inside'}, {'id':'dup','box':[0,0,2,2], 'label':'chair','scope':'inside'}, {'id':'unknown','box':[9,0,11,2], 'label':'chair','scope':'unknown'}]},
        {'id': 'f1', 'time_s': 2, 'scene': 's', 'gt': [{'id':'g1','box':[0,0,2,2], 'label':'chair','visibility':'visible'}, {'id':'g2','box':[3,0,5,2], 'label':'table','visibility':'visible'}], 'pred': [{'id':'p1','box':[0,0,2,2], 'label':'table','scope':'inside'}]}]}

def test_fixed_denominator_duplicates_unknown_and_unconfirmed():
    result = evaluate(data())
    assert result['presence'] == {'tp': 2, 'fp': 1, 'fn': 2, 'unknown': 1, 'precision': 2/3, 'recall': .5, 'f1': 4/7}
    assert result['duplicates']['count'] == 1
    assert result['confirmation']['unconfirmed'] == 1
    assert result['confirmation']['median_s'] == 0
    assert result['label']['correct'] == 1 and result['label']['total'] == 2

def test_exact_iou_boundary_and_false_merge():
    d = data(); d['frames'] = [d['frames'][0]]
    d['frames'][0]['gt'][1]['box'] = [0, 0, 1, 2]
    d['frames'][0]['pred'] = [{'id':'p', 'box':[0,0,2,2], 'label':'chair','scope':'inside'}]
    r = evaluate(d)
    assert r['presence']['tp'] == 1 and r['presence']['fn'] == 1
    assert r['potential_false_merges'] == {'count': 1, 'denominator': 1, 'rate': 1.0}

def test_matching_maximizes_cardinality_before_iou():
    d = data(); d['iou_threshold'] = .3; d['frames'] = [d['frames'][0]]
    d['frames'][0]['gt'][1]['box'] = [1,0,3,2]
    d['frames'][0]['pred'] = [{'id':'a','box':[0,0,3,2], 'label':'chair','scope':'inside'}, {'id':'b','box':[0,0,1,2], 'label':'chair','scope':'inside'}]
    assert evaluate(d)['presence']['tp'] == 2

@pytest.mark.parametrize('mutation', ['missing_hash', 'duplicate_frame', 'time_reverse', 'duplicate_gt', 'invalid_scope', 'nan'])
def test_rejects_ambiguous_or_unproven_inputs(mutation):
    d = data()
    if mutation == 'missing_hash': del d['provenance']['gt_sha256']
    if mutation == 'duplicate_frame': d['frames'][1]['id'] = 'f0'
    if mutation == 'time_reverse': d['frames'][1]['time_s'] = -1
    if mutation == 'duplicate_gt': d['frames'][0]['gt'][1]['id'] = 'g1'
    if mutation == 'invalid_scope': d['frames'][0]['pred'][0]['scope'] = 'maybe'
    if mutation == 'nan': d['frames'][0]['pred'][0]['box'][0] = float('nan')
    with pytest.raises(ValueError): evaluate(d)

def test_node_metrics_count_distinct_graph_and_gt_ids_once():
    r = evaluate(data())['nodes']
    assert r == {'tp': 1, 'fp': 1, 'fn': 1, 'precision': .5, 'recall': .5, 'f1': .5}

def test_node_identity_matching_cannot_reuse_graph_node_for_two_gt_objects():
    d = data(); d['frames'][1]['pred'] = [{'id':'p1','box':[3,0,5,2], 'label':'table','scope':'inside'}]
    r = evaluate(d)['nodes']
    assert r['tp'] == 2 and r['fp'] == 0 and r['fn'] == 0

def test_replay_refuses_existing_destination(tmp_path):
    from neusymnav.evaluation.graph_admission import replay_owner
    with pytest.raises(FileExistsError):
        replay_owner(tmp_path, tmp_path / 'predictions.json', tmp_path)

def test_confirmation_respects_global_one_to_one_node_identity():
    d = data(); d['frames'][0]['pred'] = [{'id':'p1','box':[3,0,5,2], 'label':'table','scope':'inside'}]
    d['frames'][1]['pred'] = [{'id':'p1','box':[0,0,2,2], 'label':'chair','scope':'inside'}]
    r = evaluate(d)
    assert r['nodes']['tp'] == 1
    assert r['confirmation']['confirmed'] == 1 and r['confirmation']['unconfirmed'] == 1

def test_projection_excludes_behind_camera_and_occluded_points():
    from types import SimpleNamespace
    import numpy as np
    from neusymnav.evaluation.graph_admission import project_visible_box
    source = SimpleNamespace(K=np.eye(3), T_world_camera=np.eye(4), depth_m=np.ones((4,4)), valid_depth=np.ones((4,4), dtype=bool))
    assert project_visible_box(np.array([[1.,1.,1.],[2.,2.,1.],[1.,1.,2.],[1.,1.,-1.]]), source, min_points=2) == [1,1,3,3]
