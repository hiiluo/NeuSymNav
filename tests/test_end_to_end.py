"""An actual public replay/evaluate path, with annotations read offline only."""
from pathlib import Path
import json
import pytest
from test_evaluation_protocol import completed_suite,pin


def test_replay_to_offline_scores_gt_change_affects_only_evaluator(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'replay'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    path=completed_suite(tmp_path,root);value=json.loads(path.read_text())
    gt=Path(__file__).parent/'fixtures/evaluation/semantic-a.json'
    value['scenes'][0]['offline_gt']=pin(gt);value['scenes'][0]['scene_id']='fixture'
    path.write_text(json.dumps(value));a=evaluate_suite(path,out=tmp_path/'a')
    value['scenes'][0]['offline_gt']=pin(gt.with_name('semantic-b.json'));path.write_text(json.dumps(value))
    b=evaluate_suite(path,out=tmp_path/'b')
    assert a['runs'][0]['quality']['geometry']['matched_objects']==1
    assert a['runs'][0]['quality']['label']['exact']['value']==1
    assert b['runs'][0]['quality']['label']['exact']['value']==0
    assert a['runs'][0]['quality']['identity']['value'] is None
    assert a['runs'][0]['quality']['geometry']['gt_scope_objects']==1


@pytest.mark.parametrize('kind',['clock','revision','dangling','duplicate_event','hash'])
def test_rejects_corrupt_or_incoherent_runtime_exports(tmp_path,kind):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'replay'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    name='nav.json' if kind in {'clock','revision','hash'} else 'hierarchy.json' if kind=='dangling' else 'summary.json'
    path=root/name;payload=json.loads(path.read_text())
    if kind in {'clock','revision'}:payload['payload']['fields']['clock_domain' if kind=='clock' else 'revision']='wrong' if kind=='clock' else 2
    elif kind=='dangling':payload['payload']['fields']['edges']['tuple'][0]['fields']['target_id']='missing'
    elif kind=='duplicate_event':payload['events'].append(payload['events'][0])
    else:payload['extra']='corrupt'
    path.write_text(json.dumps(payload))
    if kind!='hash':
        import hashlib
        manifest=json.loads((root/'export-manifest.json').read_text());manifest['files'][name]=hashlib.sha256(path.read_bytes()).hexdigest();(root/'export-manifest.json').write_text(json.dumps(manifest))
    suite=completed_suite(tmp_path,root)
    with pytest.raises(ValueError):evaluate_suite(suite,out=tmp_path/'evaluation')


def rehash_export(root,name):
    import hashlib
    manifest=json.loads((root/'export-manifest.json').read_text());manifest['files'][name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    (root/'export-manifest.json').write_text(json.dumps(manifest))


@pytest.mark.parametrize('attribute',['floor_id','raw_label','category','centroid','bounds','evidence_refs','lifecycle','aliases'])
def test_export_rejects_every_mismatched_canonical_object_projection(tmp_path,attribute):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.exports import load_runtime_export
    from neusymnav.contracts.serialization import loads,dumps
    from dataclasses import replace
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'runtime';replay(fixture/'recording',fixture/'config.yaml',out=root)
    hierarchy=loads((root/'hierarchy.json').read_text());key=next(k for k,n in hierarchy.nodes.items() if n.kind=='object')
    node=hierarchy.nodes[key];attrs=dict(node.attributes)
    changes=dict(floor_id='wrong-floor',raw_label='wrong label',category='sofa',centroid=[100.,100.,100.],
        bounds=[[100.,100.,100.],[101.,101.,101.]],evidence_refs=('uncommitted-evidence',),lifecycle='retired',aliases=('unproven-alias',))
    attrs[attribute]=changes[attribute];nodes=dict(hierarchy.nodes);nodes[key]=replace(node,attributes=attrs)
    (root/'hierarchy.json').write_text(dumps(replace(hierarchy,nodes=nodes)));rehash_export(root,'hierarchy.json')
    with pytest.raises(ValueError,match='object|alias'):load_runtime_export(root/'export-manifest.json')


def ambiguous_export(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.recording.writer import ReplayWriter
    from test_projection import scene,batch
    fixture=Path(__file__).parent/'fixtures/package';recording=tmp_path/'recording';writer=ReplayWriter(recording)
    sources=[scene(0),scene(1)]
    for obs in sources:assert writer.append(obs)
    assert writer.close()['complete']
    batches=[batch(sources[0],((12,12,20,20),(12,12,20,20))),batch(sources[1])]
    detections=tmp_path/'batches.json';detections.write_text(json.dumps(dict(schema_version=1,batches=[v.to_dict() for v in batches])))
    config=json.loads((fixture/'config.yaml').read_text());config['episode']['id']='episode';config['fixture']['detections']=pin(detections)
    path=tmp_path/'config.json';path.write_text(json.dumps(config));root=tmp_path/'runtime'
    result=replay(recording,path,out=root);assert result['outcome']=='completed';return root,recording,path,detections


def test_unresolved_detection_rows_remain_in_event_denominator_without_identity_credit(tmp_path):
    from neusymnav.evaluation.exports import load_runtime_export
    from neusymnav.evaluation.protocol import evaluate_suite
    root,recording,config,detections=ambiguous_export(tmp_path)
    summary,objects,nav,hierarchy=load_runtime_export(root/'export-manifest.json')
    assert summary['events_total']==3
    assert sum(e['object_id'] is None for e in summary['events'])==1
    path=completed_suite(tmp_path,root);value=json.loads(path.read_text())
    value['scenes'][0]['input']=pin(recording/'manifest.json');value['profile'].update(config=pin(config),model=pin(detections),configured_resolution_hw=[32,32]);path.write_text(json.dumps(value))
    report=evaluate_suite(path,out=tmp_path/'evaluation');checks=report['runs'][0]['checks']
    assert checks['unresolved_event_summary_count']==1
    assert checks['event_summary_count']==checks['events_total']==3
    assert report['runs'][0]['quality']['identity']['support']==0


@pytest.mark.parametrize('change',['nonnull_dangling','null_bad_source','null_bad_digest','null_extra_field'])
def test_unresolved_event_support_does_not_disable_source_or_endpoint_validation(tmp_path,change):
    from neusymnav.evaluation.exports import load_runtime_export
    root,*_=ambiguous_export(tmp_path);path=root/'summary.json';summary=json.loads(path.read_text())
    event=next(e for e in summary['events'] if e['object_id'] is None)
    if change=='nonnull_dangling':event['object_id']='not-canonical'
    elif change=='null_bad_source':event['source']['frame_index']=True
    elif change=='null_bad_digest':event['event_id']='unproved'
    else:event['claimed_identity']='unproved'
    path.write_text(json.dumps(summary));rehash_export(root,'summary.json')
    with pytest.raises(ValueError):load_runtime_export(root/'export-manifest.json')


def test_hierarchy_empty_alias_projection_cannot_be_omitted(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.exports import load_runtime_export
    from neusymnav.contracts.serialization import loads,dumps
    from dataclasses import replace
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'runtime';replay(fixture/'recording',fixture/'config.yaml',out=root)
    hierarchy=loads((root/'hierarchy.json').read_text());key=next(k for k,n in hierarchy.nodes.items() if n.kind=='object')
    node=hierarchy.nodes[key];attrs=dict(node.attributes);del attrs['aliases'];nodes=dict(hierarchy.nodes);nodes[key]=replace(node,attributes=attrs)
    (root/'hierarchy.json').write_text(dumps(replace(hierarchy,nodes=nodes)));rehash_export(root,'hierarchy.json')
    with pytest.raises(ValueError,match='object.*projection|alias'):load_runtime_export(root/'export-manifest.json')
