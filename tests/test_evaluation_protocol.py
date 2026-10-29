"""Public evaluator accounting: every frozen scene/seed slot stays in scope."""
from pathlib import Path
import hashlib
import json

import pytest


def pin(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def suite_at(tmp_path, outcomes=('completed','failed','timeout','missing')):
    asset=tmp_path/'asset';asset.write_text('explicit fixture input, not a native scene')
    attempts=[]
    for i,outcome in enumerate(outcomes):
        record=None
        if outcome!='missing':
            path=tmp_path/f'result-{i}.json'
            path.write_text(json.dumps(dict(schema_version=1,scene_id=f'scene-{i//2}',seed=i%2,
                outcome=outcome,attempted=True,reason='test fixture outcome',export=None,provenance=None)))
            record=pin(path)
        attempts.append(dict(scene_id=f'scene-{i//2}',seed=i%2,result=record,missing_reason='scheduled input unavailable' if record is None else None))
    value=dict(schema_version=1,suite_id='accounting-v1',scope='fixture_correctness',requested_scene_count=2,
        duration_s=300,seeds=[0,1],scenes=[dict(scene_id=f'scene-{i}',input_kind='scene',input=pin(asset),offline_gt=None) for i in range(2)],
        profile=dict(id='fixture',appearance_mode='off',config=pin(asset),model=pin(asset),taxonomy=pin(asset),configured_resolution_hw=[240,320]),
        budgets=dict(rss_bytes=10*1024**3,vram_bytes=5*1024**3,raw_bytes=2*1024**3,export_bytes=8*1024**3),
        attempts=attempts,comparators={key:dict(status='missing',reason='no compatible artifacts',artifact=None) for key in ['legacy_new','legacy_cg','appearance_on']})
    path=tmp_path/'suite.json';path.write_text(json.dumps(value));return path


def test_failed_timeout_and_missing_stay_in_denominator(tmp_path):
    from neusymnav.evaluation.protocol import evaluate_suite
    # No completed export is fabricated for the first slot: it must be rejected.
    path=suite_at(tmp_path,('incomplete','failed','timeout','missing'))
    report=evaluate_suite(path,out=tmp_path/'report')
    assert report['counts']==dict(planned=4,attempted=3,completed=0,incomplete=1,failed=1,timeout=1,missing=1)
    assert report['completion_fraction']['value']==0
    assert report['completion_fraction']['denominator']==4
    assert report['outcome']=='failed'
    assert report['runs'][3]['metrics']['capture_to_commit_ms']['value'] is None
    assert report['runs'][3]['metrics']['capture_to_commit_ms']['support']==0


def completed_suite(tmp_path, export_root):
    """Pin a real launcher export, independently from its offline annotations."""
    repo=Path(__file__).resolve().parents[1];fixture=repo/'tests/fixtures/package'
    summary=json.loads((export_root/'summary.json').read_text())
    path=suite_at(tmp_path,('incomplete','failed','timeout','missing'))
    value=json.loads(path.read_text())
    value['suite_id']='real-replay-v1';value['seeds']=[0]
    value['scenes']=[dict(scene_id='fixture',input_kind='recording',input=pin(fixture/'recording/manifest.json'),offline_gt=None)]
    value['profile'].update(config=pin(fixture/'config.yaml'),model=pin(fixture/'batches.json'),taxonomy=pin(repo/'configs/taxonomy-v1.json'),configured_resolution_hw=[12,12])
    record=tmp_path/'real-result.json'
    record.write_text(json.dumps(dict(schema_version=1,scene_id='fixture',seed=0,outcome='completed',attempted=True,reason=None,
        export=pin(export_root/'export-manifest.json'),provenance=pin(export_root/'attempts'/f"{summary['attempt_id']}.json"))))
    value['attempts']=[dict(scene_id='fixture',seed=0,result=pin(record),missing_reason=None)]
    path.write_text(json.dumps(value));return path


def test_real_runtime_exports_have_scoped_metrics_and_no_native_promotion(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'replay'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    path=completed_suite(tmp_path,root)
    report=evaluate_suite(path,out=tmp_path/'report')
    run=report['runs'][0]
    assert report['outcome']=='completed' # fixture evaluation finished, not native acceptance
    assert report['native_runtime_validated'] is False
    assert report['gates']['runtime_boundedness']=='not_proven'
    assert report['gates']['useful_core_demonstration']=='insufficient demonstration'
    assert run['metrics']['accepted_fraction']['value']==1
    assert run['metrics']['room_membership_assigned']['denominator']==1
    assert run['metrics']['capture_to_commit_ms']['value'] is None
    assert run['metrics']['rss_peak_bytes']['value'] is None
    assert run['quality']['geometry']['support']==0
    assert run['quality']['identity']['support']==0


def test_exact_labels_and_canonical_aliases_have_separate_denominators():
    from neusymnav.evaluation.metrics import evaluate_labels
    from neusymnav.contracts import Taxonomy
    taxonomy=Taxonomy.load(Path(__file__).parents[1]/'configs/taxonomy-v1.json')
    scores=evaluate_labels([('couch','sofa'),('alien-a','alien-b'),('chair','chair')],taxonomy)
    assert scores['exact']['value']==pytest.approx(1/3)
    assert scores['canonical']['value']==pytest.approx(2/3)
    assert scores['canonical']['denominator']==3 # unknowns never count as unknown==unknown successes
    assert scores['canonical_known_pairs']==2


@pytest.mark.parametrize('change',[
    lambda v:v.update(typo=True),
    lambda v:v.update(schema_version=True),
    lambda v:v.update(duration_s=301),
    lambda v:v.update(seeds=[0,True]),
    lambda v:v['attempts'].pop(),
    lambda v:v['attempts'].append(v['attempts'][0]),
])
def test_frozen_suite_rejects_ambiguous_or_out_of_budget_protocol(tmp_path,change):
    from neusymnav.evaluation.protocol import evaluate_suite
    path=suite_at(tmp_path,('incomplete','failed','timeout','missing'));value=json.loads(path.read_text());change(value);path.write_text(json.dumps(value))
    with pytest.raises(ValueError):evaluate_suite(path,out=tmp_path/'report')


def test_legacy_new_adapter_is_read_only_and_converts_only_explicit_convention(tmp_path):
    from neusymnav.evaluation.legacy import normalize_legacy_new
    path=tmp_path/'new.json'
    path.write_text(json.dumps(dict(schema_version=2,episode_id='legacy-e',version=1,nodes=[dict(id='new-1',label='chair',centroid_world=[1,2,3],aabb_min_world=[0,1,2],aabb_max_world=[2,3,4],status='active')],edges=[],evidence=[])))
    before=path.read_bytes()
    normalized=normalize_legacy_new(path,coordinate_convention='new_y_up_v1')
    assert normalized['objects'][0]['bounds']==[[0.,-4.,1.],[2.,-2.,3.]]
    assert normalized['objects'][0]['object_id']=='new-1'
    assert path.read_bytes()==before
    with pytest.raises(ValueError):normalize_legacy_new(path,coordinate_convention='guess')


def test_source_math_port_matches_pinned_primary_analytic_cases():
    from neusymnav.evaluation.instance_metrics import evaluate_instances,compute_idf1,FrameMatches
    # One predicted identity changes after frame 0; 2/3 observations may share
    # one global correspondence, giving IDTP=2, IDFP=1, IDFN=1, IDF1=2/3.
    identity=compute_idf1([FrameMatches(0,['a'],['gt'],[('a','gt')]),FrameMatches(1,['b'],['gt'],[('b','gt')]),FrameMatches(2,['b'],['gt'],[('b','gt')])])
    assert identity.metric.value==pytest.approx(2/3)
    assert (identity.idtp,identity.idfp,identity.idfn)==(2,1,1)
    # Greedy 0.9 would strand prediction b: optimum is a->y + b->x.
    score=evaluate_instances(['a','b'],['x','y'],['x','y','unseen'],[[.9,.8],[.85,0]])
    assert [(m.predicted_id,m.ground_truth_id) for m in score.matching.matches]==[('a','y'),('b','x')]
    assert score.precision.value==1
    assert score.coverage.value==pytest.approx(2/3)
    assert evaluate_instances([],[],[],[]).coverage.value is None


def test_deterministic_replay_cannot_be_relabelled_as_an_independent_seed(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'replay'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    path=completed_suite(tmp_path,root);value=json.loads(path.read_text())
    record=tmp_path/'real-result.json';result=json.loads(record.read_text());result['seed']=1;record.write_text(json.dumps(result))
    value['seeds']=[1];value['attempts'][0].update(seed=1,result=pin(record));path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='seed'):evaluate_suite(path,out=tmp_path/'report')


def test_one_completed_execution_cannot_be_duplicated_under_another_scene(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'replay'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    path=completed_suite(tmp_path,root);value=json.loads(path.read_text())
    value['scenes'].append(dict(value['scenes'][0],scene_id='same-recording-other-name'))
    second=tmp_path/'second-result.json';result=json.loads((tmp_path/'real-result.json').read_text());result['scene_id']='same-recording-other-name';second.write_text(json.dumps(result))
    value['attempts'].append(dict(scene_id='same-recording-other-name',seed=0,result=pin(second),missing_reason=None));path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='duplicate|execution'):evaluate_suite(path,out=tmp_path/'report')


def test_completed_effective_configuration_must_equal_pinned_config_contents(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'replay'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    path=completed_suite(tmp_path,root);record=tmp_path/'real-result.json';result=json.loads(record.read_text())
    provenance=Path(result['provenance']['path']);value=json.loads(provenance.read_text());value['effective_config']['profile']='appearance';provenance.write_text(json.dumps(value))
    result['provenance']=pin(provenance);record.write_text(json.dumps(result))
    suite=json.loads(path.read_text());suite['attempts'][0]['result']=pin(record);path.write_text(json.dumps(suite))
    with pytest.raises(ValueError,match='effective.*config|configuration'):evaluate_suite(path,out=tmp_path/'report')


def test_resolution_is_bound_to_checked_recording_source_frames(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'replay'
    replay(fixture/'recording',fixture/'config.yaml',out=root)
    path=completed_suite(tmp_path,root);value=json.loads(path.read_text());value['profile']['configured_resolution_hw']=[1,1];path.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='resolution'):evaluate_suite(path,out=tmp_path/'report')


def test_native_completed_export_without_executed_seed_proof_is_rejected(tmp_path):
    """Even consistent claimed live metadata cannot manufacture a missing seed inlet."""
    from neusymnav.runtime.launcher import replay
    from neusymnav.evaluation.protocol import evaluate_suite
    from test_end_to_end import rehash_export
    fixture=Path(__file__).parent/'fixtures/package';root=tmp_path/'runtime';replay(fixture/'recording',fixture/'config.yaml',out=root)
    path=completed_suite(tmp_path,root);suite=json.loads(path.read_text())
    config=json.loads((fixture/'config.yaml').read_text());config['mode']='live';config['sensor_config']=dict(primary=dict(resolution_hw=[12,12]));config.pop('fixture')
    config_path=tmp_path/'live-config.json';config_path.write_text(json.dumps(config));suite['profile']['config']=pin(config_path);suite['scope']='native_core'
    summary_path=root/'summary.json';summary=json.loads(summary_path.read_text());summary['mode']='live';summary_path.write_text(json.dumps(summary));rehash_export(root,'summary.json')
    record_path=tmp_path/'real-result.json';record=json.loads(record_path.read_text());provenance_path=Path(record['provenance']['path']);provenance=json.loads(provenance_path.read_text())
    provenance.update(effective_config=config,config_sha256=pin(config_path)['sha256']);provenance['assets']['detector.checkpoint']=suite['profile']['model'];provenance['assets']['detector.taxonomy']=suite['profile']['taxonomy']
    provenance_path.write_text(json.dumps(provenance));record.update(provenance=pin(provenance_path),export=pin(root/'export-manifest.json'));record_path.write_text(json.dumps(record));suite['attempts'][0]['result']=pin(record_path);path.write_text(json.dumps(suite))
    with pytest.raises(ValueError,match='native execution seed proof unavailable'):evaluate_suite(path,out=tmp_path/'evaluation')
