import json,time
from pathlib import Path
from test_runtime_scheduling import pipeline,source,wait_for,DOMAIN
from neusymnav.runtime.observability import RunMeasurements
from neusymnav.runtime.measurements import MeasurementContext
from neusymnav.runtime.resources import ResourceSampler,ResourceReading


def session():
    ctx=MeasurementContext('test-attempt','episode',DOMAIN,'a'*64,'b'*64,None,('rgbd','nav'))
    return RunMeasurements(ctx)


def test_real_pipeline_records_delayed_live_result_and_commit(tmp_path):
    from test_runtime_scheduling import Detector
    class Slow(Detector):
        def infer(self,obs):time.sleep(.02);return super().infer(obs)
    m=session();p,_,_=pipeline(tmp_path,measurements=m,detector=Slow())
    p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
    report=p.close(2);result=m.finalize(runtime_report=report,resources=None)
    assert result['collector']['distributions']['capture_to_detector_return_ns']['seen']==1
    assert result['collector']['distributions']['capture_to_object_commit_ns']['seen']==1
    assert result['collector']['admission_counts']['durable_accepted']==1
    assert result['graph_support']['live_detector_commits']==1
    assert result['graph_support']['live_object_evidence_commits']==0
    assert result['native_runtime_validated'] is False


def test_every_control_stop_reason_has_support_without_invented_depth(tmp_path):
    m=session();p,_,_=pipeline(tmp_path,measurements=m)
    assert p.control_step(object())['reason']=='navigation_unavailable'
    report=p.close(2);r=m.finalize(runtime_report=report,resources=None)
    assert r['collector']['control_reasons']['navigation_unavailable']==1
    assert r['collector']['distributions']['control_depth_age_ns']['seen']==0


def test_resource_cap_stop_is_independent_of_collector_lock(tmp_path):
    import threading
    m=session();m.cap_breach(dict(resource='rss',sampled_bytes=11,cap_bytes=10))
    p,_,_=pipeline(tmp_path,measurements=m)
    p.submit(source())
    assert p.control_step(object())['executed'] is False
    assert p.telemetry()['submitted']==1 and p.telemetry()['offered']==0
    r=m.finalize(runtime_report=p.close(2),resources=None)
    assert r['completion']['cap_breached'] and not r['completion']['complete']


def test_measurement_configuration_is_strict_and_seeded(tmp_path):
    import pytest
    from test_seed_provenance import config
    from neusymnav.runtime.configuration import load_config
    path=config(tmp_path,sensor_config=dict(seed=0))
    data=json.loads(path.read_text());data['mode']='live';data['measurements']=dict(enabled=True,rss_cap_bytes=10*1024**3,gpu_cap_bytes=5*1024**3)
    path.write_text(json.dumps(data));assert load_config(path).data['measurements']['enabled']
    for bad in [True,11*1024**3]:
        data['measurements']['rss_cap_bytes']=bad;path.write_text(json.dumps(data))
        with pytest.raises(ValueError):load_config(path)


def test_early_sensor_failure_keeps_resource_phase_and_attempt(tmp_path,monkeypatch):
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import Configuration
    from neusymnav.sensors import client
    from test_seed_provenance import config
    p=config(tmp_path);d=json.loads(p.read_text());d.update(mode='live',measurements=dict(enabled=True),sensor_config=dict(seed=0,primary=dict(sensor_id='rgbd'),navigation=dict(sensor_id='nav')),workers=dict(sensor=dict(timeout_s=.2)))
    cfg=Configuration(p,d);marker=tmp_path/'scene';marker.write_text('stub')
    monkeypatch.setattr(launcher,'load_config',lambda _:cfg)
    monkeypatch.setattr(launcher,'_checked',lambda _:(cfg,dict(sensor=(Path(__import__('sys').executable),marker),scene=marker)))
    observed=[]
    class Broken:
        def __init__(self,**kw):
            observed.extend(__import__('threading').enumerate());time.sleep(.015);raise RuntimeError('fixture sensor failed')
    monkeypatch.setattr(client,'HabitatPoseSource',Broken)
    result=launcher.run(p,duration_s=.01,out=tmp_path/'run')
    assert result['outcome']=='failed' and result['attempt_id']
    assert any(t.name=='resource-rss' for t in observed)
    artifact=json.loads((tmp_path/'run/measurements.json').read_text())
    assert artifact['context']['attempt_id']==result['attempt_id']
    assert artifact['seed_ack'] is None and artifact['resources']['rss']['samples']>0
    assert result['resource_provider_diagnostics']['schema_version']==1
    assert result['resource_provider_diagnostics']['rss']['calls']>=artifact['resources']['rss']['samples']
    assert artifact['collector']['capture_registry']['retained']==0
    assert not artifact['completion']['complete']
    assert (tmp_path/'run/attempts'/f"{result['attempt_id']}-startup.json").exists()


def test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch):
    import hashlib,sys
    from test_launcher import config
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.objects.store import ObjectOwner
    from neusymnav.contracts import DetectionBatch
    from test_sensor_execution_metadata import habitat_stub,actual_worker_script
    from test_runtime_scheduling import nav_for,AllFrames
    sensor_config,_=habitat_stub(monkeypatch);sensor_config.pop('scene_id');sensor_config.pop('episode_id')
    marker=tmp_path/'scene';marker.write_bytes(b'CPU scene marker, no native scene')
    sensor_config['scene']=dict(path=str(marker),sha256=hashlib.sha256(marker.read_bytes()).hexdigest())
    path=config(tmp_path,mode='live',sensor_config=sensor_config)
    data=json.loads(path.read_text());data['episode'].update(id='episode',primary_sensor_id='rgbd');data['workers']={'sensor':{'timeout_s':3.}};data['measurements']=dict(enabled=True);path.write_text(json.dumps(data));cfg=load_config(path)
    script=actual_worker_script(tmp_path)
    monkeypatch.setattr(launcher,'_checked',lambda _: (cfg,dict(sensor=(Path(sys.executable),script),scene=marker)))
    class Detector:
        def infer(self,obs):return DetectionBatch.from_observation(obs,(),vocabulary_id='v1')
        def close(self):pass
    class Mapper:
        def __init__(self):self.revision=0
        def update(self,obs):
            self.revision+=1
            return nav_for(obs,self.revision)
    def compose(config,assets,root,domain,clock,**kwargs):
        p=Pipeline(root,episode_id='episode',primary_sensor_id='rgbd',floor_id='floor-0',clock_domain=domain,
            owner_factory=lambda:ObjectOwner(root/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='floor-0',clock_domain=domain,detector_profile_id='cpu-fixture-seed',vocabulary_id='v1',now_ns=clock),
            detector_factory=Detector,mapper=Mapper(),keyframe_policy=AllFrames(),now_ns=clock,actual_profile='cpu-fixture-seed',measurements=kwargs.get('measurements'))
        p._launcher_worker_metadata={};return p
    monkeypatch.setattr(launcher,'_pipeline',compose)
    result=launcher.run(path,duration_s=.02,out=tmp_path/'out')
    assert result['attempt_id']
    start=json.loads((tmp_path/'out/attempts'/f"{result['attempt_id']}.json").read_text())['sensor_launch']
    final=result['worker_runtime']['sensor']
    assert start['runtime_metadata']['execution']['seed']==7
    assert start['runtime_metadata']['actual_resolution_hw']['navigation']['resolution_hw']==[4,5]
    assert 'primary' not in start['runtime_metadata']['actual_resolution_hw']
    assert final['actual_resolution_hw']['primary']['resolution_hw']==[2,3]
    assert final['actual_resolution_hw']['navigation']['resolution_hw']==[4,5]
    assert final['execution']==start['runtime_metadata']['execution']
    launch=start['configuration']
    assert launch['scene_id']==str(marker) and launch['seed']==7
    assert start['config_sha256']==hashlib.sha256(json.dumps(launch,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert start['config_sha256']==final['launch_config_sha256']
    assert start['runtime_metadata']['worker_script_sha256']==hashlib.sha256(script.read_bytes()).hexdigest()
    assert result['native_runtime_validated'] is False

    diagnostics=result['resource_provider_diagnostics']
    assert diagnostics['schema_version']==1 and diagnostics['rss']['calls']>0
    assert json.loads((tmp_path/'out/summary.json').read_text())['resource_provider_diagnostics']==diagnostics

    artifact=json.loads((tmp_path/'out/measurements.json').read_text())
    manifest=json.loads((tmp_path/'out/export-manifest.json').read_text())
    assert manifest['schema_version']==2 and 'measurements.json' in manifest['files']
    assert artifact['context']['attempt_id']==result['attempt_id']
    assert artifact['seed_ack']['seed']==7
    assert artifact['context']['seed_ack_sha256']==hashlib.sha256(json.dumps(artifact['seed_ack'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
    assert artifact['collector']['capture_registry']['retained']>0
    assert artifact['resources']['start_requested_monotonic_ns']<artifact['collector']['trace']['records'][0]['source']['capture_monotonic_ns']
    assert result['measurement_artifact']['sha256']==hashlib.sha256((tmp_path/'out/measurements.json').read_bytes()).hexdigest()
    assert artifact['native_runtime_validated'] is False


def test_live_queue_delay_beyond_fast_ttl_remains_latency_support(tmp_path):
    from test_runtime_scheduling import Detector
    clock=[1_000_000_000]
    class Slow(Detector):
        def infer(self,obs):clock[0]+=2_000_000_000;return super().infer(obs)
    m=session();p,_,_=pipeline(tmp_path,measurements=m,detector=Slow(),clock=lambda:clock[0])
    p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
    assert p.fast_semantics() is None
    r=m.finalize(runtime_report=p.close(2),resources=None)
    assert r['collector']['distributions']['capture_to_detector_return_ns']['p95']==2_000_000_000
    assert r['collector']['excluded_results']==dict(historical=0,reused=0,recovery=0)


def test_final_observer_snapshot_cannot_change_after_return(tmp_path):
    m=session();p,_,_=pipeline(tmp_path,measurements=m);p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
    report=p.close(2);a=m.finalize(runtime_report=report,resources=None)
    a['graph_support']['live_detector_commits']=999
    assert m.finalize(runtime_report=report,resources=None)['graph_support']['live_detector_commits']==1


def test_measurement_export_byte_cap_names_dropped_proofs_and_trace(tmp_path):
    from neusymnav.runtime.launcher import _measurement_payload
    m=session();p,_,_=pipeline(tmp_path,measurements=m);r=m.finalize(runtime_report=p.close(2),resources=None)
    r['collector']['trace']['records']=[dict(blob='x'*(17*1024**2))]
    data=_measurement_payload(r);decoded=json.loads(data)
    assert len(data)<=16*1024**2
    assert decoded['completion']['export_byte_overflow'] and not decoded['completion']['complete']
    assert decoded['collector']['trace']['export_dropped_records']==1
    assert not decoded['collector']['trace']['records']


def test_recorder_reservation_rejection_has_admission_support(tmp_path,monkeypatch):
    from neusymnav.runtime.quota import QuotaExceeded
    measurements=session();runtime,_,_=pipeline(tmp_path,measurements=measurements)
    reserve=runtime.quota.reserve
    def denied(key,*args,**kwargs):
        if isinstance(key,tuple) and key[0]=='source':raise QuotaExceeded('review injected source reservation rejection')
        return reserve(key,*args,**kwargs)
    monkeypatch.setattr(runtime.quota,'reserve',denied)
    runtime.submit(source())
    wait_for(lambda:bool(runtime.health.snapshot()['failed']))
    artifact=measurements.finalize(runtime_report=runtime.close(2.),resources=None)
    counts=artifact['collector']['admission_counts']
    assert counts['offered']==1 and counts['durable_accepted']==0
    assert counts['rejected']==1


def test_pending_sensor_cleanup_cannot_leave_measurements_complete(tmp_path,monkeypatch):
    from neusymnav.sensors.client import HabitatPoseSource
    close=HabitatPoseSource.close
    def pending(self,*args,**kwargs):
        # Exercise launcher ownership of an explicit non-clean worker certificate.
        # Reap the CPU child anyway so the review itself leaks no process.
        result=close(self,*args,**kwargs)
        return dict(result,clean_shutdown=False,review_pending=True)
    monkeypatch.setattr(HabitatPoseSource,'close',pending)
    test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch)
    summary=json.loads((tmp_path/'out/summary.json').read_text())
    artifact=json.loads((tmp_path/'out/measurements.json').read_text())
    assert summary['cleanup']['sensor']['clean_shutdown'] is False
    assert summary['outcome']=='incomplete'
    assert artifact['lifecycle']['outcome']==summary['outcome']
    assert artifact['completion']['complete'] is False



def test_recorder_persistence_failure_is_rejected_before_ack(tmp_path,monkeypatch):
    from neusymnav.runtime.workers import Journal
    def fail(*args,**kwargs):raise OSError('source write failed before ACK')
    monkeypatch.setattr(Journal,'accept',fail)
    m=session();runtime,_,_=pipeline(tmp_path,measurements=m)
    runtime.submit(source());wait_for(lambda:bool(runtime.health.snapshot()['failed']))
    artifact=m.finalize(runtime_report=runtime.close(2.),resources=None)
    assert artifact['collector']['admission_counts']==dict(offered=1,durable_accepted=0,rejected=1,replaced=0,stale=0)


def test_measurement_completion_requires_explicit_clean_launcher_cleanup():
    for cleanup,expected in [(None,False),({'sensor':{'clean_shutdown':False}},False),({'sensor':{}},False),({'sensor':{'clean_shutdown':True},'ui':{'clean_shutdown':False}},False),({'sensor':{'clean_shutdown':True}},True)]:
        m=session()
        artifact=m.finalize(runtime_report={'clean_shutdown':True},resources={'complete':True},cleanup=cleanup)
        assert artifact['lifecycle']['launcher_cleanup_clean'] is expected
        assert artifact['completion']['complete'] is expected
        assert artifact['lifecycle']['launcher_cleanup_status']==(None if cleanup is None else {k:v.get('clean_shutdown') is True for k,v in cleanup.items()})


def test_pending_raw_recorder_also_prevents_measurement_completion(tmp_path,monkeypatch):
    from neusymnav.recording.writer import ReplayWriter
    close=ReplayWriter.close
    def pending(self,*args,**kwargs):
        # Reap the real CPU writer, then inject its legitimate timeout certificate
        # shape to isolate launcher handling without leaving a thread behind.
        result=close(self,*args,**kwargs)
        return dict(result,stopped=False,complete=False)
    monkeypatch.setattr(ReplayWriter,'close',pending)
    test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch)
    summary=json.loads((tmp_path/'out/summary.json').read_text())
    artifact=json.loads((tmp_path/'out/measurements.json').read_text())
    assert summary['recording_certificate']['stopped'] is False
    assert summary['outcome']=='incomplete'
    assert artifact['lifecycle']['outcome']=='incomplete'
    assert artifact['completion']['complete'] is False


def test_stopped_partial_raw_data_is_clean_cleanup_but_not_completed_run(tmp_path,monkeypatch):
    from neusymnav.recording.writer import ReplayWriter
    close=ReplayWriter.close
    def partial(self,*args,**kwargs):
        result=close(self,*args,**kwargs)
        return dict(result,stopped=True,complete=False)
    monkeypatch.setattr(ReplayWriter,'close',partial)
    test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch)
    summary=json.loads((tmp_path/'out/summary.json').read_text())
    artifact=json.loads((tmp_path/'out/measurements.json').read_text())
    assert summary['outcome']=='incomplete'
    assert summary['cleanup']['raw_recorder']['clean_shutdown'] is True
    assert artifact['lifecycle']['launcher_cleanup_status']['raw_recorder'] is True


def test_launcher_recaptures_depth_after_slow_pipeline_startup(tmp_path,monkeypatch):
    from neusymnav.runtime import launcher
    original_run=launcher.run
    def delayed_run(config_path,**kwargs):
        compose=launcher._pipeline
        def slow_compose(*args,**options):
            time.sleep(.35)
            return compose(*args,**options)
        monkeypatch.setattr(launcher,'_pipeline',slow_compose)
        return original_run(config_path,**kwargs)
    monkeypatch.setattr(launcher,'run',delayed_run)
    test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch)
    result=json.loads((tmp_path/'out/summary.json').read_text())
    assert result['error'] is None
    assert result['worker_runtime']['sensor']['actual_resolution_hw']['navigation']['samples']>=2


def test_startup_recapture_retains_original_frame_in_raw_history(tmp_path,monkeypatch):
    test_measured_launcher_writes_bound_v2_artifact_and_keeps_native_unvalidated(tmp_path,monkeypatch)
    summary=json.loads((tmp_path/'out/summary.json').read_text())
    certificate=summary['recording_certificate']
    assert certificate['source_gap_count']==0
    assert certificate['expected_count']==summary['frames']
