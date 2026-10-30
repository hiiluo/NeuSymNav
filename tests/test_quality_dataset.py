import hashlib
import json

import pytest

from neusymnav.evaluation.quality_dataset import load_quality_pair


def documents():
    common = dict(schema_version=1, binding=dict(scene_id='fixture', episode_id='e',
        recording_sha256='a'*64, taxonomy_sha256='b'*64,
        coordinate_convention='canonical_z_up_m_v1'),
        provenance=dict(kind='synthetic', description='analytic test'))
    frame = dict(frame_id='f0', frame_index=0, capture_monotonic_ns=1,
        source_sha256='c'*64, geometry_hash='d'*64, width=2, height=2)
    gt = dict(common, frames=[dict(frame, annotated=True, objects=[dict(
        id='g', label='chair', bbox=[0, 0, 2, 2], mask=[[True]*2]*2)])])
    pred = dict(common, identity_semantics='online', score_floor=0.0, max_detections=30,
        frames=[dict(frame, status='complete', objects=[dict(id='p', identity='i',
            label='chair', score=.9, bbox=[0, 0, 2, 2], mask=[[True]*2]*2)])])
    return gt, pred


def write_pair(tmp_path, gt, pred):
    a, b = tmp_path/'gt.json', tmp_path/'pred.json'
    a.write_text(json.dumps(gt)); b.write_text(json.dumps(pred))
    return a, b


def test_bound_pair_preserves_observations(tmp_path):
    a,b=write_pair(tmp_path,*documents())
    result=load_quality_pair(a,b)
    assert result['frames'][0]['gt'][0]['id']=='g'
    assert result['frames'][0]['pred'][0]['identity']=='i'
    assert result['input_hashes']['gt']==hashlib.sha256(a.read_bytes()).hexdigest()


@pytest.mark.parametrize('mutation', ['binding','source','unannotated','missing_frame','duplicate','nan','shape','score','bounds'])
def test_reject_invalid_or_unbound_data(tmp_path, mutation):
    gt,pred=documents()
    if mutation=='binding': pred['binding']['scene_id']='wrong'  # deepcopy below handles common object
    # documents shares common binding; ensure mismatch explicitly for this case.
    if mutation=='binding': gt['binding']=dict(pred['binding'],scene_id='fixture')
    if mutation=='source': pred['frames'][0]['source_sha256']='e'*64
    if mutation=='unannotated': gt['frames'][0]['annotated']=False
    if mutation=='missing_frame': pred['frames']=[]
    if mutation=='duplicate': gt['frames']*=2
    if mutation=='nan': pred['frames'][0]['objects'][0]['score']=float('nan')
    if mutation=='shape': pred['frames'][0]['objects'][0]['mask']=[[True]]
    if mutation=='score': pred['frames'][0]['objects'][0]['score']=2
    if mutation=='bounds': pred['frames'][0]['objects'][0]['bbox']=[0,0,3,2]
    with pytest.raises(ValueError): load_quality_pair(*write_pair(tmp_path,gt,pred))


def test_missing_prediction_is_explicit_empty_not_removed(tmp_path):
    gt,pred=documents(); pred['frames'][0].update(status='missing',objects=[])
    result=load_quality_pair(*write_pair(tmp_path,gt,pred))
    assert len(result['frames'])==1 and result['frames'][0]['pred']==[]


def test_missing_status_cannot_contain_detections(tmp_path):
    gt,pred=documents(); pred['frames'][0]['status']='missing'
    with pytest.raises(ValueError):load_quality_pair(*write_pair(tmp_path,gt,pred))
