import json,copy
from pathlib import Path
import pytest
from test_evaluation_protocol import pin,suite_at
from test_execution_proof import execution


def suite_v2(tmp_path):
    value,inspection,args=execution(tmp_path,startup_failure=True)
    cfg=args['config_path'];provenance=args['provenance'];summary=args['summary']
    measure_path=tmp_path/'measurements.json';measure_path.write_text(json.dumps(value))
    summary['measurement_artifact']=dict(path='measurements.json',sha256=pin(measure_path)['sha256'])
    summary_path=tmp_path/'summary.json';summary_path.write_text(json.dumps(summary))
    prov_path=tmp_path/'provenance.json';prov_path.write_text(json.dumps(provenance))
    result=tmp_path/'result.json';result.write_text(json.dumps(dict(schema_version=2,scene_id='scene-0',seed=7,outcome='failed',attempted=True,reason='CPU fixture sensor startup failure',export=None,provenance=pin(prov_path),measurements=pin(measure_path),summary=pin(summary_path))))
    suite=tmp_path/'suite.json'
    data=dict(schema_version=2,suite_id='partial-phase-v2',scope='native_core',requested_scene_count=2,duration_s=300,seeds=[7],scenes=[dict(scene_id='scene-0',input_kind='scene',input=dict(path=str(tmp_path/'scene.glb'),sha256='c'*64),offline_gt=None)],profile=dict(id='baseline',appearance_mode='off',config=pin(cfg),model=pin(cfg),taxonomy=pin(cfg),configured_resolution_hw=[2,3]),budgets=dict(rss_bytes=10*1024**3,vram_bytes=5*1024**3,raw_bytes=2*1024**3,export_bytes=8*1024**3),attempts=[dict(scene_id='scene-0',seed=7,result=pin(result),missing_reason=None,execution_config=pin(cfg))],comparators={k:dict(status='missing',reason='No comparator',artifact=None) for k in ('legacy_new','legacy_cg','appearance_on')})
    # Real local fixture bytes, no data/model download or native execution.
    scene=tmp_path/'scene.glb';scene.write_bytes(b'CPU fixture scene marker')
    data['scenes'][0]['input']=pin(scene)
    config=json.loads(cfg.read_text());config['sensor_config']['scene']=dict(path='scene.glb',sha256=pin(scene)['sha256']);config['detector']=dict(checkpoint=dict(path='scene.glb',sha256=pin(scene)['sha256']),taxonomy=dict(path='scene.glb',sha256=pin(scene)['sha256']));cfg.write_text(json.dumps(config))
    # Rebuild fixture to keep exact config/launch/ACK provenance coherent.
    from neusymnav.evaluation.measurements import canonical_sha256
    checksum=pin(cfg)['sha256'];launch=value['launch_config'];launch['scene_id']=str(scene)
    for ctx in (value['context'],value['collector']['context']):ctx.update(config_sha256=checksum,launch_config_sha256=canonical_sha256(launch))
    provenance.update(effective_config=config,config_sha256=checksum);provenance['assets']['sensor_config.scene']=dict(path=str(scene),sha256=pin(scene)['sha256']);provenance['assets']['detector.checkpoint']=dict(path=str(scene),sha256=pin(scene)['sha256']);provenance['assets']['detector.taxonomy']=dict(path=str(scene),sha256=pin(scene)['sha256']);provenance['sensor_launch'].update(configuration=launch,config_sha256=canonical_sha256(launch))
    measure_path.write_text(json.dumps(value));summary.update(config_sha256=checksum,measurement_artifact=dict(path='measurements.json',sha256=pin(measure_path)['sha256']));summary_path.write_text(json.dumps(summary));prov_path.write_text(json.dumps(provenance))
    record=json.loads(result.read_text());record.update(provenance=pin(prov_path),measurements=pin(measure_path),summary=pin(summary_path));result.write_text(json.dumps(record))
    data['profile'].update(config=pin(cfg),model=pin(scene),taxonomy=pin(scene));data['attempts'][0].update(execution_config=pin(cfg),result=pin(result));suite.write_text(json.dumps(data))
    return suite


def test_failed_startup_v2_keeps_denominator_and_measured_phase_without_accuracy(tmp_path):
    from neusymnav.evaluation.protocol import evaluate_suite
    path=suite_v2(tmp_path);report=evaluate_suite(path,out=tmp_path/'report')
    assert report['counts']==dict(planned=1,attempted=1,completed=0,incomplete=0,failed=1,timeout=0,missing=0)
    run=report['runs'][0]
    assert run['quality']['geometry']['support']==0
    assert run['checks']['measurement_integrity']=='pass'
    assert run['checks']['seed_execution']['support']==0
    assert report['native_runtime_validated'] is False


def test_missing_v2_attempt_requires_own_pinned_seed_config(tmp_path):
    from neusymnav.evaluation.protocol import evaluate_suite
    path=suite_v2(tmp_path);data=json.loads(path.read_text());data['attempts'][0].update(result=None,missing_reason='not launched');data['attempts'][0].pop('execution_config');path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='execution_config'):evaluate_suite(path,out=tmp_path/'report')


def test_v2_rejects_frozen_recipe_change_beyond_seed_and_episode(tmp_path):
    from neusymnav.evaluation.protocol import evaluate_suite
    path=suite_v2(tmp_path);data=json.loads(path.read_text());cfg=tmp_path/'changed.json';config=json.loads(Path(data['profile']['config']['path']).read_text());config['profile']='geometry-only';cfg.write_text(json.dumps(config));data['attempts'][0]['execution_config']=pin(cfg);path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='recipe'):evaluate_suite(path,out=tmp_path/'report')


def test_completed_inspection_requires_result_summary_to_be_exact_same_file_contents(tmp_path):
    from neusymnav.evaluation.suite_v2 import inspect_result
    from neusymnav.evaluation.protocol import _load_suite,_result
    path=suite_v2(tmp_path);suite,base=_load_suite(path);entry=suite['attempts'][0];record=_result(base,entry)
    forged=json.loads(Path(record['summary']['path']).read_text());forged['frames']=999
    with pytest.raises(ValueError,match='summary'):inspect_result(suite,base,entry,record,summary=forged)


def test_partial_phase_must_still_match_frozen_model_recipe(tmp_path):
    from neusymnav.evaluation.protocol import evaluate_suite
    path=suite_v2(tmp_path);data=json.loads(path.read_text());model=tmp_path/'other-model';model.write_bytes(b'other');data['profile']['model']=pin(model);path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='model|detector'):evaluate_suite(path,out=tmp_path/'report')


def test_partial_execution_cannot_be_counted_twice_under_another_scene(tmp_path):
    from neusymnav.evaluation.protocol import evaluate_suite
    path=suite_v2(tmp_path);data=json.loads(path.read_text());second=copy.deepcopy(data['scenes'][0]);second['scene_id']='scene-1';data['scenes'].append(second)
    entry=copy.deepcopy(data['attempts'][0]);entry['scene_id']='scene-1';record=json.loads(Path(entry['result']['path']).read_text());record['scene_id']='scene-1';record_path=tmp_path/'second-result.json';record_path.write_text(json.dumps(record));entry['result']=pin(record_path);data['attempts'].append(entry);path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='duplicate measured execution'):evaluate_suite(path,out=tmp_path/'report')


def test_frozen_resolution_must_match_seed_specific_config_even_for_missing_slot(tmp_path):
    from neusymnav.evaluation.protocol import evaluate_suite
    path=suite_v2(tmp_path);data=json.loads(path.read_text());data['attempts'][0].update(result=None,missing_reason='not launched');data['profile']['configured_resolution_hw']=[4,5];path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='resolution'):evaluate_suite(path,out=tmp_path/'report')
