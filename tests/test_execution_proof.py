import copy,json
from pathlib import Path
import pytest
from neusymnav.evaluation.measurements import canonical_sha256,inspect_measurements
from neusymnav.evaluation.execution_proof import bind_execution
from neusymnav.runtime.measurements import MeasurementContext
from neusymnav.runtime.observability import RunMeasurements
from test_runtime_scheduling import source,DOMAIN


def execution(tmp_path,*,startup_failure=False):
    from dataclasses import asdict
    config_path=tmp_path/'config.yaml'
    config=dict(schema_version=1,profile='baseline',floor=dict(z_m=0.,datum_source='CPU fixture calibration only',calibration_sha256='e'*64),mode='live',episode=dict(id='episode',primary_sensor_id='rgbd',floor_id='floor-0'),sensor_config=dict(seed=7,primary=dict(sensor_id='rgbd',resolution_hw=[2,3]),navigation=dict(sensor_id='nav',resolution_hw=[2,3]),scene=dict(path='scene.glb',sha256='c'*64)),workers=dict(sensor=dict(script=dict(path='worker.py',sha256='d'*64))))
    config_path.write_text(json.dumps(config));config_sha=__import__('hashlib').sha256(config_path.read_bytes()).hexdigest()
    launch=copy.deepcopy(config['sensor_config']);launch.pop('scene');launch.update(scene_id=str(tmp_path/'scene.glb'),episode_id='episode')
    launch_sha=canonical_sha256(launch)
    ack=None if startup_failure else dict(schema_version=1,episode_id='episode',clock_domain=DOMAIN,seed=7,seed_method='habitat_sim.Simulator.seed',seed_applied=True,config_sha256=launch_sha,runtime_version='CPU dependency stub for proof consistency only')
    context=MeasurementContext('proof-attempt','episode',DOMAIN,config_sha,launch_sha,None if ack is None else canonical_sha256(ack),('rgbd','nav'))
    m=RunMeasurements(context)
    dimensions={}
    for lane,modality in ([] if startup_failure else [('navigation','depth_only'),('primary','rgbd')]):
        obs=source(modality=modality);m.capture(obs)
        dimensions[lane]=dict(resolution_hw=list(obs.depth_m.shape),source=asdict(obs.key),capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=DOMAIN,samples=1,changed=False)
    artifact=json.loads(json.dumps(m.finalize(runtime_report={'clean_shutdown':True},resources=None,seed_ack=ack,launch_config=launch,outcome='failed' if startup_failure else 'incomplete',cleanup={})))
    metadata=None if startup_failure else dict(schema_version=1,launch_config_sha256=launch_sha,worker_script_sha256='d'*64,execution=ack,seed_status='applied',actual_resolution_hw=dimensions)
    start=None if metadata is None else copy.deepcopy(metadata)
    if start:start['actual_resolution_hw'].pop('primary')
    provenance=dict(attempt_id=context.attempt_id,config_sha256=config_sha,clock_domain=DOMAIN,effective_config=config,assets={'sensor_config.scene':dict(path=str(tmp_path/'scene.glb'),sha256='c'*64),'workers.sensor.script':dict(path=str(tmp_path/'worker.py'),sha256='d'*64)},sensor_launch=dict(configuration=launch,config_sha256=launch_sha,runtime_metadata=start))
    if startup_failure:provenance['phase']='before_sensor_model_startup'
    summary=dict(attempt_id=context.attempt_id,config_sha256=config_sha,mode='live',episode_id='episode',outcome='failed' if startup_failure else 'incomplete',cleanup={},worker_runtime=dict(sensor=metadata))
    inspection=inspect_measurements(artifact,attempt_id=context.attempt_id,config_sha256=config_sha)
    return artifact,inspection,dict(provenance=provenance,summary=summary,config_path=config_path,executed_config=config,seed=7)


def test_seed_ack_binds_to_launch_config_and_separate_decoded_metadata(tmp_path):
    artifact,inspection,args=execution(tmp_path);result=bind_execution(artifact,inspection,**args)
    assert result['seed_execution']['value']['seed']==7
    assert result['actual_input_resolution_hw']['value']==[2,3]
    assert not result['native_eligible_context'] and not result['native_runtime_validated']


@pytest.mark.parametrize('mutation',[
    lambda a,k:k.update(seed=1),
    lambda a,k:k['provenance'].update(attempt_id='different'),
    lambda a,k:k['provenance']['sensor_launch']['runtime_metadata'].update(worker_script_sha256='f'*64),
    lambda a,k:k['provenance']['sensor_launch']['runtime_metadata']['execution'].update(seed=True),
    lambda a,k:k['summary']['worker_runtime']['sensor'].update(seed_status='unsupported_after_reset'),
    lambda a,k:k['summary']['worker_runtime']['sensor']['actual_resolution_hw']['primary'].update(resolution_hw=[1,1]),
    lambda a,k:k['provenance']['effective_config']['sensor_config']['primary'].update(sensor_id='other'),
    lambda a,k:k['summary'].update(cleanup={'sensor':{'clean_shutdown':False}}),
    lambda a,k:k['summary'].update(outcome='completed'),
])
def test_seed_resolution_or_provenance_mismatch_rejected(tmp_path,mutation):
    artifact,inspection,args=execution(tmp_path);args=copy.deepcopy(args);mutation(artifact,args)
    with pytest.raises(ValueError):bind_execution(artifact,inspection,**args)


def test_failed_before_sensor_ack_keeps_resources_phase_without_seed_or_resolution_credit(tmp_path):
    artifact,inspection,args=execution(tmp_path,startup_failure=True)
    result=bind_execution(artifact,inspection,**args)
    assert result['seed_execution']['support']==0
    assert result['actual_input_resolution_hw']['support']==0
    assert not result['native_eligible_context']


def test_execution_inspection_cannot_be_reused_after_artifact_mutation(tmp_path):
    artifact,inspection,args=execution(tmp_path)
    artifact['actuation']['observed_body_translation_lower_bound_m']=99.
    with pytest.raises(ValueError,match='mutated'):bind_execution(artifact,inspection,**args)


def test_actual_cpu_worker_ack_binds_to_real_launcher_attempt_provenance(tmp_path,monkeypatch):
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import load_config
    from test_runtime_measurement_wiring import test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated
    import hashlib
    original_run=launcher.run
    def run(config_path,**kwargs):
        checked=launcher._checked
        def pinned_checked(path):
            cfg,assets=checked(path);script=assets['sensor'][1];spec=dict(path=str(script),sha256=hashlib.sha256(script.read_bytes()).hexdigest())
            cfg.data['workers']['sensor']['script']=spec
            cfg.path.write_text(json.dumps(cfg.data))
            cfg.checked_assets['workers.sensor.script']=spec
            cfg.checked_assets['sensor_config.scene']=dict(path=str(assets['scene']),sha256=hashlib.sha256(assets['scene'].read_bytes()).hexdigest())
            return cfg,assets
        monkeypatch.setattr(launcher,'_checked',pinned_checked)
        return original_run(config_path,**kwargs)
    monkeypatch.setattr(launcher,'run',run)
    test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch)
    root=tmp_path/'out';summary=json.loads((root/'summary.json').read_text());artifact=json.loads((root/'measurements.json').read_text())
    provenance=json.loads((root/'attempts'/f"{summary['attempt_id']}.json").read_text());config_path=tmp_path/'config.json'
    from neusymnav.evaluation.measurements import load_measurements
    artifact,inspection=load_measurements(root/'measurements.json',attempt_id=summary['attempt_id'],config_sha256=summary['config_sha256'])
    result=bind_execution(artifact,inspection,provenance=provenance,summary=summary,config_path=config_path,executed_config=load_config(config_path).data,seed=7)
    assert result['seed_execution']['value']['seed']==7
    assert result['actual_input_resolution_hw']['value']==[2,3]
    assert not result['native_runtime_validated']


def test_effective_config_argument_cannot_override_pinned_file_bytes(tmp_path):
    artifact,inspection,args=execution(tmp_path)
    args['executed_config']['profile']='geometry-only'
    with pytest.raises(ValueError,match='config'):bind_execution(artifact,inspection,**args)


@pytest.mark.parametrize('samples',[2,1000])
def test_primary_resolution_support_uses_audited_capture_population(tmp_path,samples):
    artifact,inspection,args=execution(tmp_path)
    args['summary']['worker_runtime']['sensor']['actual_resolution_hw']['primary']['samples']=samples
    metric=bind_execution(artifact,inspection,**args)['actual_input_resolution_hw']
    assert metric['value']==[2,3] and metric['support']==1
    assert 'audited' in metric['source'] and 'subset' in metric['source']


def _replace_captures(artifact,inspection,observations,*,trace_byte_cap=64*1024**2):
    meter=RunMeasurements(inspection['context'],trace_byte_cap=trace_byte_cap)
    for obs in observations:meter.capture(obs)
    artifact=json.loads(json.dumps(meter.finalize(runtime_report={'clean_shutdown':True},resources=None,
        seed_ack=artifact['seed_ack'],launch_config=artifact['launch_config'],outcome='incomplete',cleanup={})))
    return artifact,inspect_measurements(artifact,attempt_id=inspection['context'].attempt_id,config_sha256=inspection['context'].config_sha256)


def test_final_primary_counter_cannot_be_smaller_than_audited_population(tmp_path):
    from dataclasses import asdict
    artifact,inspection,args=execution(tmp_path)
    last=source(1,stamp=1_000_000_001)
    artifact,inspection=_replace_captures(artifact,inspection,[source(modality='depth_only'),source(),last])
    args['summary']['worker_runtime']['sensor']['actual_resolution_hw']['primary'].update(source=asdict(last.key),capture_monotonic_ns=last.capture_monotonic_ns)
    with pytest.raises(ValueError):bind_execution(artifact,inspection,**args)


def test_final_primary_source_cannot_precede_audited_capture(tmp_path):
    artifact,inspection,args=execution(tmp_path)
    artifact,inspection=_replace_captures(artifact,inspection,[source(modality='depth_only'),source(),source(1,stamp=1_000_000_001)])
    args['summary']['worker_runtime']['sensor']['actual_resolution_hw']['primary']['samples']=2
    with pytest.raises(ValueError):bind_execution(artifact,inspection,**args)


def test_primary_resolution_support_with_trace_loss_counts_only_retained_sources(tmp_path):
    from dataclasses import asdict
    from neusymnav.runtime.measurements import TRACE_RECORD_CHARGE
    artifact,inspection,args=execution(tmp_path)
    last=source(1,stamp=1_000_000_001)
    artifact,inspection=_replace_captures(artifact,inspection,[source(),source(modality='depth_only'),last],trace_byte_cap=TRACE_RECORD_CHARGE)
    # The deliberately small trace must be authorized by this exact recipe.
    args['executed_config']['measurements']=dict(enabled=True,trace_byte_cap=TRACE_RECORD_CHARGE)
    args['config_path'].write_text(json.dumps(args['executed_config']))
    checksum=__import__('hashlib').sha256(args['config_path'].read_bytes()).hexdigest()
    artifact['context']['config_sha256']=artifact['collector']['context']['config_sha256']=checksum
    args['summary']['config_sha256']=args['provenance']['config_sha256']=checksum
    args['provenance']['effective_config']=copy.deepcopy(args['executed_config'])
    inspection=inspect_measurements(artifact,attempt_id=args['summary']['attempt_id'],config_sha256=checksum)
    args['summary']['worker_runtime']['sensor']['actual_resolution_hw']['primary'].update(source=asdict(last.key),capture_monotonic_ns=last.capture_monotonic_ns,samples=1000)
    metric=bind_execution(artifact,inspection,**args)['actual_input_resolution_hw']
    assert not inspection['trace']['trace_complete']
    assert metric['value']==[2,3] and metric['support']==1
    assert 'audited' in metric['source'] and 'subset' in metric['source']


def test_primary_metadata_without_retained_primary_capture_is_unsupported(tmp_path):
    artifact,inspection,args=execution(tmp_path)
    artifact,inspection=_replace_captures(artifact,inspection,[source(modality='depth_only')])
    metric=bind_execution(artifact,inspection,**args)['actual_input_resolution_hw']
    assert metric['value'] is None and metric['support']==0


@pytest.mark.parametrize('samples',[1,2])
def test_navigation_startup_outside_pipeline_has_separate_sample_accounting(tmp_path,samples):
    from dataclasses import asdict
    artifact,inspection,args=execution(tmp_path)
    last=source(1,stamp=1_000_000_001,modality='depth_only')
    artifact,inspection=_replace_captures(artifact,inspection,[source(),last])
    args['summary']['worker_runtime']['sensor']['actual_resolution_hw']['navigation'].update(source=asdict(last.key),capture_monotonic_ns=last.capture_monotonic_ns,samples=samples)
    if samples==1:
        with pytest.raises(ValueError):bind_execution(artifact,inspection,**args)
    else:
        metric=bind_execution(artifact,inspection,**args)['actual_input_resolution_hw']
        assert metric['value']==[2,3] and metric['support']==1


@pytest.mark.parametrize('runtime',[[],None,1,'bad'])
@pytest.mark.parametrize('startup_failure',[False,True])
def test_malformed_worker_runtime_container_rejected_as_value_error(tmp_path,runtime,startup_failure):
    artifact,inspection,args=execution(tmp_path,startup_failure=startup_failure);args['summary']['worker_runtime']=runtime
    with pytest.raises(ValueError):bind_execution(artifact,inspection,**args)


@pytest.mark.parametrize('runtime',[{}, {'sensor':None}])
def test_missing_final_sensor_metadata_on_incomplete_attempt_stays_unsupported(tmp_path,runtime):
    artifact,inspection,args=execution(tmp_path);args['summary']['worker_runtime']=runtime
    result=bind_execution(artifact,inspection,**args)
    assert result['actual_input_resolution_hw']['support']==0
    assert result['seed_execution']['support']==1



@pytest.mark.parametrize('changed',[False,True])
def test_primary_resolution_support_counts_only_captures_at_final_dimensions(tmp_path,changed):
    from dataclasses import asdict,replace
    import numpy as np
    artifact,inspection,args=execution(tmp_path)
    earlier=replace(source(),rgb=np.zeros((1,1,3),np.uint8),depth_m=np.ones((1,1),np.float32),valid_depth=np.ones((1,1),bool))
    last=source(1,stamp=1_000_000_001)
    artifact,inspection=_replace_captures(artifact,inspection,[source(modality='depth_only'),earlier,last])
    args['summary']['worker_runtime']['sensor']['actual_resolution_hw']['primary'].update(source=asdict(last.key),capture_monotonic_ns=last.capture_monotonic_ns,samples=2,changed=changed)
    if not changed:
        with pytest.raises(ValueError):bind_execution(artifact,inspection,**args)
        return
    metric=bind_execution(artifact,inspection,**args)['actual_input_resolution_hw']
    assert metric['value']==[2,3] and metric['support']==1
    assert 'audited' in metric['source'] and 'subset' in metric['source']


def test_navigation_resolution_change_flag_cannot_be_cleared_after_startup(tmp_path):
    artifact,inspection,args=execution(tmp_path)
    args['provenance']['sensor_launch']['runtime_metadata']['actual_resolution_hw']['navigation']['changed']=True
    with pytest.raises(ValueError):bind_execution(artifact,inspection,**args)
