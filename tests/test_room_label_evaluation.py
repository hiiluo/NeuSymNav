import pytest

from neusymnav.evaluation.room_labels import evaluate_room_label_pilot


def row(room, context, truth, label, status='available', support=True, **extra):
    return {'physical_room_id':room,'scene_id':'scene-'+room,'context_hash':context,
        'reference_labels':truth,'geometry_status':'available','label':label,'status':status,
        'supporting_object_ids':['O(0)'] if support else [],'eligible':True,
        'latency_ms':12.0,'peak_rss_bytes':1000,**extra}


def test_perfect_and_all_unknown_report_coverage_and_supported_scores():
    refs=[row('r1','c1',['kitchen'],'kitchen'),row('r2','c2',['bedroom'],'bedroom')]
    perfect=evaluate_room_label_pilot(refs,model_version='rules-v1')
    assert perfect['physical_room_count']==2
    assert perfect['coverage']==1.0
    assert perfect['selective_accuracy']==1.0
    unknown=evaluate_room_label_pilot([row('r1','c1',['kitchen'],'unknown','unknown',False),
        row('r2','c2',['bedroom'],'unknown','unknown',False)],model_version='slm')
    assert unknown['coverage']==0.0
    assert unknown['selective_accuracy'] is None
    assert unknown['abstention_count']==2


def test_wrong_confident_mixed_reference_and_missing_reference_are_separate():
    refs=[row('r1','c1',['kitchen'],'bedroom'),row('r2','c2',['bathroom','utility'],'bathroom'),
          row('r3','c3',[],'kitchen')]
    refs[2]['eligible']=False
    refs[2]['skip_reason']='missing_human_reference'
    scored=evaluate_room_label_pilot(refs,model_version='slm')
    assert scored['physical_room_count']==2
    assert scored['selective_accuracy']==0.5
    assert scored['multi_label_reference_count']==1
    assert scored['skipped_reasons']=={'missing_human_reference':1}
    assert scored['per_scene']['scene-r1']['physical_room_count']==1


def test_revisions_of_one_physical_room_do_not_inflate_sample_and_track_flips():
    refs=[row('r1','c2',['kitchen'],'kitchen')]
    refs.append(row('r1','c1',['kitchen'],'bedroom',geometry_revision=1))
    refs[1]['selected']=False
    scored=evaluate_room_label_pilot(refs,model_version='slm')
    assert scored['physical_room_count']==1
    assert scored['revision_prediction_count']==2
    assert scored['flip_count']==1
    assert scored['confusion']['kitchen']['kitchen']==1


def test_geometry_failure_is_not_counted_as_semantic_error_and_bad_identity_rejected():
    refs=[row('r1','c1',['kitchen'],'unknown',geometry_status='unavailable',
              status='insufficient_evidence',support=False)]
    scored=evaluate_room_label_pilot(refs,model_version='slm')
    assert scored['geometry_unavailable_count']==1
    assert scored['coverage'] is None
    bad=[row('r1','c1',['kitchen'],'kitchen'),row('r1','c2',['kitchen'],'kitchen')]
    with pytest.raises(ValueError,match='exactly one selected context'):
        evaluate_room_label_pilot(bad,model_version='rules')

