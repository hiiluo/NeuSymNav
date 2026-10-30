import json

from test_quality_dataset import documents, write_pair
from neusymnav.evaluation.quality_report import evaluate_quality


def test_synthetic_report_and_cli_outputs(tmp_path):
    a,b=write_pair(tmp_path,*documents())
    result=evaluate_quality(a,b,out=tmp_path/'report')
    assert result['evidence_kind']=='synthetic'
    assert result['detection']['operating_point']['tp']==1
    assert result['geometry']['available'] is False
    assert result['association']['online']['idf1']['value']==1
    assert (tmp_path/'report'/'report.md').exists()
    assert json.loads((tmp_path/'report'/'report.json').read_text())['native_runtime_validated'] is False


def test_final_ledger_identity_never_masquerades_as_online(tmp_path):
    gt,pred=documents(); pred['identity_semantics']='final_canonical_only'
    a,b=write_pair(tmp_path,gt,pred)
    result=evaluate_quality(a,b,out=tmp_path/'report')
    assert result['association']['online']['available'] is False
    assert result['association']['final_canonicalized']['idf1']['value']==1


def test_existing_output_not_overwritten(tmp_path):
    import pytest
    a,b=write_pair(tmp_path,*documents()); out=tmp_path/'report'; out.mkdir(); (out/'report.json').write_text('keep')
    with pytest.raises(ValueError): evaluate_quality(a,b,out=out)
    assert (out/'report.json').read_text()=='keep'


def test_frame_local_observation_ids_are_namespaced(tmp_path):
    import copy
    gt,pred=documents()
    for doc in (gt,pred):
        row=copy.deepcopy(doc['frames'][0])
        row.update(frame_id='f1',frame_index=1,capture_monotonic_ns=2)
        doc['frames'].append(row)
    a,b=write_pair(tmp_path,gt,pred)
    report=evaluate_quality(a,b,out=tmp_path/'report')
    assert report['association']['online']['idf1']['value']==1


def test_final_only_supplied_aliases_are_applied(tmp_path):
    import copy
    gt,pred=documents(); pred['identity_semantics']='final_canonical_only'
    for doc in (gt,pred):
        row=copy.deepcopy(doc['frames'][0])
        row.update(frame_id='f1',frame_index=1,capture_monotonic_ns=2)
        doc['frames'].append(row)
    pred['frames'][1]['objects'][0].update(id='p1',identity='i2')
    pred['final_aliases']={'i2':'i'}
    a,b=write_pair(tmp_path,gt,pred)
    report=evaluate_quality(a,b,out=tmp_path/'report')
    assert report['association']['online']['available'] is False
    assert report['association']['final_canonicalized']['idf1']['value']==1
    assert report['association']['final_canonicalized']['id_switches']['value']==0
