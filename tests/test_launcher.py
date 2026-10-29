from pathlib import Path
import hashlib
import json
import pytest


def config(tmp_path,**updates):
    value=dict(schema_version=1,mode='fixture_cpu_no_models',profile='geometry-only',
        episode=dict(id='episode-1',primary_sensor_id='rgbd',floor_id='floor-0'),
        floor=dict(z_m=0.,datum_source='fixture-calibration',calibration_sha256='a'*64),
        fixture=dict(detections=dict(path='batches.json',sha256=hashlib.sha256(b'{"schema_version":1,"batches":[]}').hexdigest())))
    (tmp_path/'batches.json').write_bytes(b'{"schema_version":1,"batches":[]}')
    value.update(updates)
    path=tmp_path/'config.json';path.write_text(json.dumps(value));return path


def test_preflight_resolves_assets_from_config_directory(tmp_path,monkeypatch):
    from neusymnav.runtime.launcher import preflight
    path=config(tmp_path)
    monkeypatch.chdir('/')
    result=preflight(path)
    assert result['ready'] is True
    assert result['mode']=='fixture_cpu_no_models'
    assert result['native_runtime_validated'] is False


def test_preflight_rejects_corrupt_declared_asset(tmp_path):
    from neusymnav.runtime.launcher import preflight
    path=config(tmp_path);(tmp_path/'batches.json').write_text('changed')
    assert not preflight(path)['ready']
    assert 'checksum' in str(preflight(path)['issues'])


def test_configuration_rejects_unknown_fields_and_yaml_aliases(tmp_path):
    from neusymnav.runtime.configuration import load_config
    path=config(tmp_path,typo=True)
    with pytest.raises(ValueError,match='unknown'):load_config(path)
    path.write_text('schema_version: 1\nx: &value [a]\ny: *value\n')
    with pytest.raises(ValueError,match='alias|anchor'):load_config(path)


def test_live_run_rejects_fixture_mode(tmp_path):
    from neusymnav.runtime.launcher import run
    with pytest.raises(ValueError,match='replay.only|replay only'):
        run(config(tmp_path),duration_s=1,out=tmp_path/'output')


def test_fixture_replay_commits_real_detection_and_resumes_same_ledger(tmp_path):
    from neusymnav.runtime.launcher import replay
    fixture=Path(__file__).parent/'fixtures'/'launcher'
    result=replay(fixture/'recording',fixture/'config.yaml',out=tmp_path/'out')
    assert result['outcome']=='completed',result
    expected=json.loads((fixture/'expected.json').read_text())
    assert result['object_ids']==expected['object_ids']
    assert result['events']==expected['events']
    assert result['events_complete']
    assert result['events_total']==len(result['events'])
    again=replay(fixture/'recording',fixture/'config.yaml',out=tmp_path/'out')
    assert again['outcome']=='completed',again
    assert again['object_ids']==result['object_ids']
    assert again['events']==result['events']
    assert again['skipped_restored_frames']==1
    assert again['replay_session']['session_id']==result['replay_session']['session_id']


def test_config_preserves_venv_interpreter_spelling(tmp_path):
    import sys
    from neusymnav.runtime.configuration import load_config,file_sha256
    venv=tmp_path/'venv';venv.mkdir();link=venv/'python';link.symlink_to(Path(sys.executable).resolve())
    c=load_config(config(tmp_path))
    assert c.asset(dict(path='venv/python',sha256=file_sha256(link)),'python',executable=True)==link


def test_resume_restores_coherent_persisted_map_and_hierarchy(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.contracts.serialization import loads
    fixture=Path(__file__).parent/'fixtures'/'launcher';out=tmp_path/'out'
    first=replay(fixture/'recording',fixture/'config.yaml',out=out)
    old=(out/'hierarchy.json').read_bytes()
    again=replay(fixture/'recording',fixture/'config.yaml',out=out)
    assert again['hierarchy_available'],again
    assert again['hierarchy_restored']
    assert (out/'hierarchy.json').read_bytes()==old
    hierarchy=loads(old.decode());nav=loads((out/'nav.json').read_text())
    assert nav.revision==hierarchy.map_revision
    assert nav.clock_domain==again['replay_session']['clock_domain']
    assert again['source_revisions']['object']==hierarchy.object_revision


def test_fixture_rejects_wrong_original_geometry_before_rebinding(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.contracts import from_dict
    from dataclasses import replace
    fixture=Path(__file__).parent/'fixtures'/'launcher'
    value=json.loads((fixture/'batches.json').read_text())
    value['batches'][0]=replace(from_dict(value['batches'][0]),geometry_hash='0'*64).to_dict()
    payload=json.dumps(value).encode();(tmp_path/'batches.json').write_bytes(payload)
    data=json.loads((fixture/'config.yaml').read_text());data['fixture']['detections']['sha256']=hashlib.sha256(payload).hexdigest()
    (tmp_path/'config.yaml').write_text(json.dumps(data))
    with pytest.raises(ValueError,match='original source/geometry_hash'):
        replay(fixture/'recording',tmp_path/'config.yaml',out=tmp_path/'out')


@pytest.mark.parametrize('extra',[
    dict(ui=dict(enabled='false')),
    dict(navigation=dict(robot=dict(geometry_id='r',radius_m=.2,height_m=1.,typo=True))),
    dict(workers=dict(sensor=dict(python=None,script=None,timeout_s=-1))),
    dict(replay=dict(allow_incomplete='false')),
])
def test_nested_configuration_rejects_invalid_values(tmp_path,extra):
    from neusymnav.runtime.configuration import load_config
    with pytest.raises(ValueError):load_config(config(tmp_path,**extra))


def test_config_rejects_duplicate_and_deep_yaml(tmp_path):
    from neusymnav.runtime.configuration import load_config
    path=tmp_path/'bad.yaml';path.write_text('schema_version: 1\nschema_version: 1\n')
    with pytest.raises(ValueError,match='duplicate'):load_config(path)
    path.write_text('x: '+('['*20)+'1'+(']'*20))
    with pytest.raises(ValueError,match='depth'):load_config(path)


def test_ui_bad_version_and_oversize_commands_are_rejected(tmp_path):
    from neusymnav.runtime.ui_transport import decode_publication,UiEndpoint
    with pytest.raises(ValueError,match='version|schema'):decode_publication(b'{"wire_version":true}')


def test_interpreter_preflight_reports_missing_worker_module():
    import sys
    from neusymnav.runtime.launcher import _probe_interpreter
    with pytest.raises(ValueError,match='neusymnav_missing_native_dependency.*install|missing.*neusymnav_missing_native_dependency'):
        _probe_interpreter(sys.executable,['neusymnav_missing_native_dependency'],'sensor')


def test_resume_rejects_corrupted_persisted_hierarchy(tmp_path):
    from neusymnav.runtime.launcher import replay
    fixture=Path(__file__).parent/'fixtures'/'launcher';out=tmp_path/'out'
    replay(fixture/'recording',fixture/'config.yaml',out=out)
    with (out/'hierarchy.json').open('a') as stream:stream.write(' ')
    result=replay(fixture/'recording',fixture/'config.yaml',out=out)
    assert result['outcome']=='incomplete'
    assert 'checksum mismatch' in result['export_issue']


def test_replay_corrupt_payload_never_reports_completed(tmp_path):
    import shutil
    from neusymnav.runtime.launcher import replay
    fixture=Path(__file__).parent/'fixtures'/'launcher';recording=tmp_path/'recording'
    shutil.copytree(fixture/'recording',recording)
    frame=recording/'frame-000000000000.json';frame.write_text(frame.read_text()+' ')
    result=replay(recording,fixture/'config.yaml',out=tmp_path/'out')
    assert result['outcome']=='failed'
    assert not result['recording_certificate']['complete']


def test_configuration_preserves_legacy_appearance_recipe():
    import yaml
    original=yaml.safe_load((Path(__file__).parent/'fixtures/regressions/legacy-appearance.yaml').read_text())
    updated=yaml.safe_load((Path(__file__).parents[1]/'configs/appearance.yaml').read_text())
    assert updated['worker']==original['worker']
    assert updated['provenance']==original['provenance']


def test_pending_accepted_replay_uses_restored_virtual_clock(tmp_path):
    from neusymnav.runtime.launcher import replay
    from neusymnav.runtime.workers import Journal
    from neusymnav.recording.replay import ReplaySession,ReplayReader
    fixture=Path(__file__).parent/'fixtures'/'launcher';out=tmp_path/'out';out.mkdir()
    session=ReplaySession.open(out/'replay-session.json',fixture/'recording',start_ns=123)
    obs=next(ReplayReader(fixture/'recording',session=session).frames())
    config=dict(schema_version=1,episode_id='p09-fixture',primary_sensor_id='rgbd',clock_domain=session.clock_domain,
        floor_id='floor-0',actual_profile='geometry-only:fixture_cpu_no_models')
    journal=Journal(out,config);journal.accept(obs);journal.close()
    result=replay(fixture/'recording',fixture/'config.yaml',out=out)
    assert result['runtime']['failed']=={}
    assert result['runtime']['metrics']['recovered']==1
    assert result['object_ids']==json.loads((fixture/'expected.json').read_text())['object_ids']
    assert result['skipped_restored_frames']==1
    assert result['outcome']=='incomplete' # no prior coherent map export exists


def test_live_worker_scripts_cannot_import_from_external_source(tmp_path):
    from neusymnav.runtime.configuration import load_config,file_sha256
    script=tmp_path/'worker.py';script.write_text('print("not package source")\n')
    import sys
    path=config(tmp_path,workers=dict(sensor=dict(python=dict(path=sys.executable,sha256=file_sha256(sys.executable)),script=dict(path='worker.py',sha256=file_sha256(script)))))
    c=load_config(path)
    with pytest.raises(ValueError,match='bundled|package'):
        c.worker('sensor')


def test_budget_caps_cannot_silently_exceed_runtime_policy(tmp_path):
    from neusymnav.runtime.configuration import load_config
    with pytest.raises(ValueError,match='cap|policy'):
        load_config(config(tmp_path,budgets=dict(raw_cap=4*1024**3,total_cap=16*1024**3)))


@pytest.mark.parametrize('raw_reject',[False,True])
def test_live_capture_waits_only_for_exact_nav_and_executes_pulses(tmp_path,monkeypatch,raw_reject):
    import sys,time
    from dataclasses import replace
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.contracts import FrameKey,DetectionBatch,MotionCommand,NavigationDecision
    from neusymnav.objects.store import ObjectOwner
    from contract_helpers import observation
    from test_runtime_places import Map
    from neusymnav.sensors import client
    data=json.loads(config(tmp_path).read_text());data['mode']='live';data['episode']['id']='episode';data['sensor_config']={};data['workers']={'sensor':{}}
    path=tmp_path/'live.json';path.write_text(json.dumps(data));cfg=load_config(path)
    captures=[];pulses=[]
    class Sensor:
        def __init__(self,**kwargs):self.n={};self.latest=None
        def _capture(self,modality,sensor):
            index=self.n.get(sensor,0);self.n[sensor]=index+1
            obs=observation(key=FrameKey('episode',sensor,index),capture_monotonic_ns=time.monotonic_ns(),clock_domain='host_monotonic:launcher-fixture',modality=modality)
            captures.append(obs)
            if modality=='depth_only':self.latest=obs
            return obs
        def capture(self):return self._capture('rgbd','rgbd')
        def capture_navigation(self):return self._capture('depth_only','depth')
        def robot_pose(self,obs):return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain,pose_version=obs.pose_version,robot_xy=(.75,.75),yaw_rad=0.)
        def execute(self,command):pulses.append(command);return dict(executed=True)
        def close(self,timeout_s):return dict(clean_shutdown=True)
    class Detector:
        def infer(self,obs):return DetectionBatch(obs.key,obs.geometry_hash,'fixture-vocabulary',(),'complete',False)
        def close(self):pass
    class SlowMap(Map):
        def __init__(self):self.rev=0
        def update(self,obs):time.sleep(.015);self.rev+=1;return replace(super().update(obs),revision=self.rev)
    class Guard:
        def bind_nav(self,nav,**kwargs):self.nav=nav
        def filter(self,decision,latest,now):return MotionCommand(latest.key,self.nav.revision,now,now+1000,latest.clock_domain,.1,0.,'fixture',latest.capture_monotonic_ns)
    class Navigator:
        def step(self,nav,*args):return NavigationDecision(None,((0.,0.),),.1,0.,nav.revision,'fixture')
    def compose(c,a,root,domain,clock,**kwargs):
        return Pipeline(root,episode_id='episode',primary_sensor_id='rgbd',floor_id='floor-0',clock_domain=domain,
            owner_factory=lambda:ObjectOwner(root/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='floor-0',clock_domain=domain,detector_profile_id='fixture',vocabulary_id='fixture-vocabulary',now_ns=clock),
            detector_factory=Detector,mapper=SlowMap(),navigator=Navigator(),guard=Guard(),now_ns=clock,**kwargs)
    monkeypatch.setattr(client,'HabitatPoseSource',Sensor)
    monkeypatch.setattr(launcher,'_checked',lambda _: (cfg,dict(sensor=(sys.executable,Path(__file__)) ,scene=Path(__file__))))
    monkeypatch.setattr(launcher,'_pipeline',compose)
    if raw_reject:
        original=launcher.ReplayWriter
        monkeypatch.setattr(launcher,'ReplayWriter',lambda *a,**kw:original(*a,max_frames=1,**kw))
    result=launcher.run(path,duration_s=.08,out=tmp_path/'out')
    if raw_reject:
        assert result['outcome']=='incomplete'
        assert result['admission_stop']=='raw_recording_rejected'
        assert len(captures)==2
        assert not result['recording_certificate']['complete']
        return
    assert pulses,'safe source_pending every cycle must not starve navigation'
    assert all(pulse.source.sensor_id=='depth' for pulse in pulses)
    assert result['recording_certificate']['complete']
    assert result['recording_policy']['archive_max_bytes']==256*1024**2


def test_appearance_profile_keeps_detector_and_encoder_worker_paths_distinct(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from neusymnav.runtime import launcher
    from neusymnav.runtime.configuration import Configuration
    from neusymnav.perception import detector_client,appearance_client
    from neusymnav.regions import backend
    from neusymnav.contracts import Taxonomy
    calls={}
    class Detector:
        def __init__(self,**kwargs):calls['detector']=kwargs
        def close(self):pass
    class Encoder:
        def __init__(self,*args,**kwargs):calls['encoder']=dict(args=args,**kwargs)
        def close(self):pass
    monkeypatch.setattr(detector_client,'DetectorClient',Detector)
    monkeypatch.setattr(detector_client,'validate_recipe',lambda r:r)
    monkeypatch.setattr(Taxonomy,'load',lambda _:SimpleNamespace(vocabulary_id='fixture'))
    monkeypatch.setattr(appearance_client,'AppearanceWorkerEncoder',Encoder)
    monkeypatch.setattr(backend,'RegionBackend',lambda *a,**kw:SimpleNamespace(close=lambda:None))
    data=json.loads(config(tmp_path).read_text());data.update(profile='appearance',mode='live',appearance_mode='openclip',
        detector={},workers=dict(detector=dict(timeout_s=2.),appearance={}),
        worker=dict(checkpoint_sha256='0'*64,model_name='ViT-B-32',preprocessing_id='pinned',timeout_s=7.))
    cfg=Configuration(tmp_path/'config.yaml',data)
    marker=tmp_path/'asset';marker.write_bytes(b'fixture')
    assets=dict(detector=(Path('/detector-python'),Path('/detector-script')),appearance=(Path('/appearance-python'),Path('/appearance-script')),
        checkpoint=marker,encoder=marker,taxonomy=marker,appearance_checkpoint=marker,region=marker)
    pipeline=launcher._pipeline(cfg,assets,tmp_path/'out','host_monotonic:test',lambda:1_000_000_000)
    try:
        assert calls['detector']['python']==Path('/detector-python')
        assert calls['detector']['worker_script']==Path('/detector-script')
        assert calls['detector']['timeout_s']==2.
        assert calls['encoder']['args'][0]==Path('/appearance-python')
    finally:pipeline.close(2)


def test_final_export_rejects_ui_retained_nav_mismatching_runtime_hierarchy(tmp_path):
    from test_runtime_scheduling import pipeline,source,nav_for,wait_for,DOMAIN
    from neusymnav.runtime.launcher import _export
    from neusymnav.visualization.publisher import DisplayPublisher
    from neusymnav.contracts.serialization import loads
    class Mapper:
        def update(self, obs): return nav_for(obs, obs.key.frame_index+1)
    class DroppingUi:
        # Reproduces UiProcess.publish's supported drop-on-image/IO-error path:
        # the runtime keeps advancing while its internal publisher stays old.
        def __init__(self):
            self.publisher=DisplayPublisher(clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
        def publish(self,hierarchy,metrics):
            if hierarchy.map_revision==1:self.publisher.publish(hierarchy,metrics)
    ui=DroppingUi()
    p,_,_=pipeline(tmp_path,mapper=Mapper(),publisher=ui)
    try:
        p.submit(source())
        # UI publication can precede the durable dispatch watermark. Wait for
        # commit before offering the next frame: admission intentionally rejects
        # offers during checkpoint I/O instead of blocking the caller.
        wait_for(lambda:p.telemetry()['committed']==1 and ui.publisher.read_latest() is not None)
        p.submit(source(1));wait_for(lambda:p.snapshot() is not None and p.snapshot().map_revision==2 and p.snapshot().object_revision==2)
    finally:report=p.close(2)
    assert report['clean_shutdown']
    # Legacy providers without canonical pair access still fail closed when
    # their retained display map does not match the hierarchy.
    p.snapshot_bundle=None
    result=_export(tmp_path,p,report,dict(outcome='completed',mode='live'))
    assert result['outcome']=='incomplete'
    assert not result['hierarchy_available']
    assert 'mismatch' in result['export_issue']
    assert not (tmp_path/'hierarchy.json').exists()
    assert not (tmp_path/'nav.json').exists()



@pytest.mark.parametrize('name',['baseline','geometry-only','appearance'])
def test_shipped_ui_script_sha_matches_local_package(name):
    import yaml
    from neusymnav.runtime.configuration import file_sha256
    root=Path(__file__).resolve().parents[1]
    path=root/'configs'/f'{name}.yaml'
    value=yaml.safe_load(path.read_text())
    ui=value['workers']['ui']['script']
    assert file_sha256(path.parent/ui['path'])==ui['sha256'], 'shipped UI worker checksum rejects bundled source'

