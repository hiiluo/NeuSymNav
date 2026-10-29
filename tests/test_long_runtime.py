"""Fresh multirate capture must preserve real sensor/source provenance."""
from types import SimpleNamespace
import json
import sys

import numpy as np
import pytest

from neusymnav.runtime import launcher
from neusymnav.sensors.habitat_worker import HabitatCapture, sensor_pose
from neusymnav.sensors.client import HabitatPoseSource
from test_sensor_adapter import sample
from neusymnav.sensors.habitat_worker import encode_packet


def test_capture_draws_and_reads_only_requested_lane():
    events=[]
    class Sensor:
        def __init__(self,name,value):self.name=name;self.value=value
        def draw_observation(self):events.append(('draw',self.name))
        def get_observation(self):events.append(('read',self.name));return self.value
    optical=SimpleNamespace(position=[0.,1.,0.],rotation=[0.,0.,0.,1.])
    down=SimpleNamespace(position=[0.,1.,0.],rotation=np.array([[1.,0.,0.],[0.,0.,1.],[0.,-1.,0.]]))
    state=SimpleNamespace(position=[0.,0.,0.],rotation=[0.,0.,0.,1.],sensor_states={'rgb':optical,'depth':optical,'nav':down})
    worker=HabitatCapture.__new__(HabitatCapture)
    spec=dict(sensor_id='primary',rgb_uuid='rgb',depth_uuid='depth',depth_min_m=.1,depth_max_m=10.)
    worker.config=dict(primary=spec,navigation=dict(spec,sensor_id='nav',depth_uuid='nav'))
    worker.sim=SimpleNamespace(_sensors={'rgb':Sensor('rgb',np.ones((2,3,4),np.uint8)),
        'depth':Sensor('depth',np.ones((2,3),np.float32)),'nav':Sensor('nav',np.ones((2,3),np.float32))},
        get_world_time=lambda:0.,get_sensor_observations=lambda:pytest.fail('render-all used'))
    worker.agent=SimpleNamespace(get_state=lambda:state)
    worker._K=lambda *_:np.array([[3.,0.,1.],[0.,3.,.5],[0.,0.,1.]])
    worker.episode_id='episode';worker.clock_domain='host_monotonic:test';worker.indices=dict(primary=0,navigation=0);worker.pose_version=0
    worker.capture('primary');worker.capture('navigation')
    assert events==[('draw','rgb'),('draw','depth'),('read','rgb'),('read','depth'),('draw','nav'),('read','nav')]
    assert worker.indices==dict(primary=1,navigation=1)
    assert worker.robot_pose()['source']['sensor_id']=='nav'


def test_navigation_pose_arrives_in_capture_transaction_without_extra_rpc(tmp_path):
    capture=sample('depth_only');packet=encode_packet(capture);m=capture['metadata']
    pose=dict(source={k:m[k] for k in ('episode_id','sensor_id','frame_index')},
        capture_monotonic_ns=m['capture_monotonic_ns'],clock_domain=m['clock_domain'],
        pose_version=m['pose_version'],robot_xy=[2.,3.],yaw_rad=.2)
    script=tmp_path/'sensor.py'
    script.write_text('import sys,json\nprint(json.dumps(dict(ready=True,wire_version=1)),flush=True)\n'
        'for line in sys.stdin:\n op=json.loads(line)["op"]\n'
        ' if op=="close":break\n'
        ' print('+repr(json.dumps(dict(ok=True,packet=packet,pose=pose)))+' if op=="capture_navigation" else '+repr(json.dumps(dict(ok=False,error='unexpected extra RPC')))+',flush=True)\n')
    with HabitatPoseSource(python=sys.executable,config={},worker_script=script,timeout_s=2.) as source:
        obs=source.capture_navigation()
        assert source.robot_pose(obs)['robot_xy']==(2.,3.)
        assert source.robot_pose(obs)['source']==obs.key


def test_multirate_cadence_skips_missed_slots_without_catchup():
    cadence=launcher._CaptureCadence(primary_hz=5.,navigation_hz=20.)
    assert cadence.primary_due(0.)
    assert not cadence.primary_due(.05)
    assert cadence.primary_due(.21)
    assert cadence.navigation_delay(.21)==0.
    cadence.navigation_started(.21)
    assert cadence.navigation_delay(.211)==pytest.approx(.049)
    assert cadence.navigation_delay(.4)==0.
    cadence.navigation_started(.4)
    assert cadence.navigation_delay(.401)==pytest.approx(.049)
    assert not cadence.primary_due(.22)


def test_navigation_only_tick_captures_raw_pose_then_admits_without_old_primary():
    events=[];nav=object();pose=object()
    sensor=SimpleNamespace(capture=lambda:pytest.fail('unexpected primary capture'),
        capture_navigation=lambda:(events.append('capture'),nav)[1],
        robot_pose=lambda obs:(events.append('pose'),pose)[1])
    pipeline=SimpleNamespace(measurements=None,submit_navigation=lambda *args:events.append(('submit',args)))
    result=launcher._capture_navigation(sensor,pipeline,lambda obs:events.append(('raw',obs)))
    assert result is nav
    assert events==['capture',('raw',nav),'pose',('submit',(nav,pose))]


def test_control_invocation_trace_retains_actual_starts_and_reports_overflow():
    trace=launcher._ControlInvocations(3)
    for value in (1,50_000_002,150_000_003,250_000_004):trace.record(value)
    result=trace.snapshot('host_monotonic:test')
    assert result['starts_monotonic_ns']==[1,50_000_002,150_000_003]
    assert result['total']==4 and result['dropped']==1 and not result['complete']
    assert result['intervals']['count']==3
    assert result['intervals']['miss_50ms']==3 and result['intervals']['miss_100ms']==2


def test_navigation_transaction_rejects_old_primary_and_keeps_pose_pinned(tmp_path):
    from dataclasses import replace
    from neusymnav.contracts import FrameKey
    from test_runtime_scheduling import pipeline,source,wait_for
    from test_runtime_places import Map,pose
    p,detector,_=pipeline(tmp_path,mapper=Map())
    try:
        rgb=source();p.submit(rgb);wait_for(lambda:p.telemetry()['committed']==1)
        for i in range(3):
            nav=source(i,modality='depth_only')
            p.submit_navigation(nav,pose(nav))
            wait_for(lambda:p._latest_nav.source==nav.key)
        assert detector.calls==[0]
        assert p._latest_nav.source==nav.key and p._latest_nav.capture_monotonic_ns==nav.capture_monotonic_ns
        with pytest.raises(ValueError,match='replay|order'):p.submit_navigation(nav,pose(nav))
        wrong=replace(nav,key=FrameKey('episode','rgbd',4))
        with pytest.raises(ValueError,match='distinct'):p.submit_navigation(wrong,pose(wrong))
        assert p._latest_depth.key==nav.key
    finally:assert p.close(2)['clean_shutdown']


@pytest.mark.parametrize('mutation',[lambda p:p.update(pose_version=999),lambda p:p.update(capture_monotonic_ns=0),lambda p:p.update(robot_xy=[float('nan'),0.])])
def test_capture_transaction_rejects_mismatched_pose_before_publication(tmp_path,mutation):
    capture=sample('depth_only');packet=encode_packet(capture);m=capture['metadata']
    pose=dict(source={k:m[k] for k in ('episode_id','sensor_id','frame_index')},capture_monotonic_ns=m['capture_monotonic_ns'],
        clock_domain=m['clock_domain'],pose_version=m['pose_version'],robot_xy=[0.,0.],yaw_rad=0.)
    mutation(pose)
    script=tmp_path/'invalid_pose.py'
    script.write_text('import sys,json\nprint(json.dumps(dict(ready=True,wire_version=1)),flush=True)\n'
        'for line in sys.stdin: print('+repr(json.dumps(dict(ok=True,packet=packet,pose=pose)))+',flush=True)\n')
    with HabitatPoseSource(python=sys.executable,config={},worker_script=script,timeout_s=2.) as source:
        with pytest.raises(ValueError,match='pose|nonfinite'):source.capture_navigation()
        assert source._navigation is None and not source.is_alive
        assert source._last_capture_ns==-1


@pytest.mark.parametrize('long_mode',[False,True])
def test_live_multirate_records_every_capture_and_never_reuses_primary(tmp_path,monkeypatch,long_mode):
    import time
    from dataclasses import replace
    from pathlib import Path
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.contracts import FrameKey,DetectionBatch,MotionCommand,NavigationDecision
    from neusymnav.objects.store import ObjectOwner
    from neusymnav.recording import ReplayReader
    from contract_helpers import observation
    from test_runtime_places import Map
    from neusymnav.sensors import client
    path=config(tmp_path)
    data=json.loads(path.read_text());data.update(mode='live',sensor_config={},workers={'sensor':{}},
        runtime=dict(primary_hz=5,navigation_hz=20,control_sample_cap=100))
    if long_mode:
        data['long_demo']=dict(max_duration_s=600,payload_format='npz_v2')
    data['episode']['id']='episode';path.write_text(json.dumps(data));cfg=load_config(path)
    captures=[];commands=[]
    class Sensor:
        def __init__(self,**kwargs):self.indices={};self.pose_version=0
        def _capture(self,modality,sensor):
            index=self.indices.get(sensor,0);self.indices[sensor]=index+1
            obs=observation(key=FrameKey('episode',sensor,index),capture_monotonic_ns=time.monotonic_ns(),
                clock_domain='host_monotonic:multirate-fixture',modality=modality,pose_version=self.pose_version)
            captures.append(obs);return obs
        def capture(self):return self._capture('rgbd','rgbd')
        def capture_navigation(self):return self._capture('depth_only','nav')
        def robot_pose(self,obs):return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,
            clock_domain=obs.clock_domain,pose_version=obs.pose_version,robot_xy=(.75,.75),yaw_rad=0.)
        def execute(self,command):commands.append(command);self.pose_version+=1;return dict(executed=True)
        def close(self,timeout_s):return dict(clean_shutdown=True)
    class Mapper(Map):
        def __init__(self):self.revision=0
        def update(self,obs):self.revision+=1;return replace(super().update(obs),revision=self.revision)
    class Detector:
        def infer(self,obs):return DetectionBatch(obs.key,obs.geometry_hash,'v1',(),'complete',False)
        def close(self):pass
    class Guard:
        def bind_nav(self,nav,**kwargs):self.nav=nav
        def filter(self,decision,latest,now):return MotionCommand(latest.key,self.nav.revision,now,now+1000,
            latest.clock_domain,.1,0.,'fixture',latest.capture_monotonic_ns)
    class Navigator:
        def step(self,nav,*args):return NavigationDecision(None,((0.,0.),),.1,0.,nav.revision,'fixture')
    def compose(c,a,root,domain,clock,**kwargs):
        return Pipeline(root,episode_id='episode',primary_sensor_id='rgbd',floor_id='f',clock_domain=domain,
            owner_factory=lambda:ObjectOwner(root/'objects',episode_id='episode',primary_sensor_id='rgbd',floor_id='f',
                clock_domain=domain,detector_profile_id='fixture',vocabulary_id='v1',now_ns=clock),
            detector_factory=Detector,mapper=Mapper(),navigator=Navigator(),guard=Guard(),now_ns=clock,**kwargs)
    monkeypatch.setattr(client,'HabitatPoseSource',Sensor)
    monkeypatch.setattr(launcher,'_checked',lambda _:(cfg,dict(sensor=(sys.executable,Path(__file__)),scene=Path(__file__))))
    monkeypatch.setattr(launcher,'_pipeline',compose)
    result=launcher.run(path,duration_s=.36,out=tmp_path/'run')
    primary=[obs for obs in captures if obs.modality=='rgbd'];navigation=[obs for obs in captures if obs.modality=='depth_only']
    assert len(primary)==2 and len(navigation)>=8
    assert len(commands)>=6
    assert len({cmd.source for cmd in commands})==len(commands)
    assert {cmd.source.sensor_id for cmd in commands}=={'nav'}
    assert result['recording_certificate']['complete']
    reader=ReplayReader(tmp_path/'run/keyframes/recording')
    assert reader.manifest['format_version']==(2 if long_mode else 1)
    replay=list(reader.frames())
    assert [o.key for o in replay]==[o.key for o in captures]
    assert [r['source_capture_monotonic_ns'] for r in reader.manifest['records']]==[o.capture_monotonic_ns for o in captures]
    trace=json.loads((tmp_path/'run/control-invocations.json').read_text())
    assert trace['complete'] and trace['total']>=len(commands)
    assert trace['total']==len(navigation)-2  # two startup sources have no control invocation
    assert len(set(trace['starts_monotonic_ns']))==trace['total']
    assert result['control_invocations_artifact']['complete']


def test_invocation_counts_separate_unmatched_waits_stop_and_executed_results():
    trace=launcher._ControlInvocations(4)
    trace.record(1,navigation_ready=False);trace.result(dict(executed=False,reason='navigation_source_pending'))
    trace.record(50_000_001,navigation_ready=True);trace.result(dict(executed=False,reason='bootstrap_blocked'))
    trace.record(100_000_001,navigation_ready=True);trace.result(dict(executed=True,reason='executed'))
    value=trace.snapshot('host_monotonic:test')
    assert value['navigation_wait']==dict(matched=2,unmatched=1,unspecified=0)
    assert value['executed_results']==1 and value['result_total']==3 and value['result_missing']==0
    assert value['control_results']==dict(navigation_source_pending=1,bootstrap_blocked=1,executed=1)


def test_long_demo_disk_budget_rejects_before_worker_startup(tmp_path,monkeypatch):
    import shutil
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    path=config(tmp_path);data=json.loads(path.read_text())
    data.update(mode='live',long_demo=dict(max_duration_s=600,payload_format='npz_v2'))
    path.write_text(json.dumps(data));cfg=load_config(path)
    monkeypatch.setattr(launcher,'_checked',lambda _:(cfg,{}))
    monkeypatch.setattr(shutil,'disk_usage',lambda _:SimpleNamespace(free=0))
    with pytest.raises(ValueError,match='free disk'):launcher.run(path,duration_s=600,out=tmp_path/'run')


def test_legacy_profile_cannot_silently_request_600s(tmp_path):
    from test_launcher import config
    with pytest.raises(ValueError,match='profile ceiling'):launcher.run(config(tmp_path),duration_s=600,out=tmp_path/'run')


def test_explicit_long_measurement_proof_budget_retains_more_than_4096_poses():
    from test_runtime_measurement_wiring import session
    from test_runtime_scheduling import source
    from test_runtime_places import pose
    from neusymnav.runtime.observability import RunMeasurements
    context=session().context
    legacy=RunMeasurements(context,capture_cap=5000)
    long=RunMeasurements(context,capture_cap=5000,proof_record_cap=5000)
    for index in range(4100):
        obs=source(index,stamp=1_000_000_000+index,modality='depth_only')
        assert long.pose(obs,pose(obs))
        legacy.pose(obs,pose(obs))
    runtime=dict(clean_shutdown=True,pending=0)
    a=legacy.finalize(runtime_report=runtime,resources=None)
    b=long.finalize(runtime_report=runtime,resources=None)
    assert a['actuation']['record_cap']==4096 and a['actuation']['record_overflow']==4
    assert b['actuation']['record_cap']==5000 and b['actuation']['record_overflow']==0
    assert len(b['actuation']['body_pose_records'])==4100


@pytest.mark.parametrize('value',[0,True,20001,1.5])
def test_measurement_proof_budget_rejects_unbounded_requests(value):
    from test_runtime_measurement_wiring import session
    from neusymnav.runtime.observability import RunMeasurements
    with pytest.raises(ValueError,match='proof_record_cap'):RunMeasurements(session().context,proof_record_cap=value)


def test_explicit_long_trace_budget_retains_more_than_8192_events():
    from test_runtime_measurements import context,source
    from neusymnav.runtime.measurements import BoundedMeasurements
    meter=BoundedMeasurements(context(),trace_byte_cap=512*1024**2)
    for index in range(8200):assert meter.try_record_capture(source(index,capture=100+index),width=640,height=480)
    meter.stop();value=meter.finalize()
    assert value['trace']['dropped']==0 and value['trace']['byte_cap']==512*1024**2
    assert len(value['trace']['records'])==8200
    with pytest.raises(ValueError,match='trace_byte_cap'):BoundedMeasurements(context(),trace_byte_cap=512*1024**2+1)


def test_long_measurement_export_preserves_payload_that_exceeds_legacy_cap():
    from test_runtime_measurement_wiring import session
    artifact=session().finalize(runtime_report=dict(clean_shutdown=True,pending=0),resources=None)
    artifact['collector']['trace']['records']=[dict(blob='x'*(17*1024**2))]
    result=json.loads(launcher._measurement_payload(artifact,max_bytes=64*1024**2))
    assert len(result['collector']['trace']['records'])==1
    assert not result['completion']['export_byte_overflow']
    with pytest.raises(ValueError,match='export'):launcher._measurement_payload(artifact,max_bytes=64*1024**2+1)
