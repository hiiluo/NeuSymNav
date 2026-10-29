"""Native dependency is substituted; real seed ordering and source codec run."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import types
import numpy as np
import pytest
from neusymnav.sensors.habitat_worker import HabitatCapture
from neusymnav.sensors.client import observation_from_packet


def habitat_stub(monkeypatch, *, fail_seed=False):
    calls=[];native=types.ModuleType('habitat_sim');native.__version__='cpu-fixture-habitat-v1'
    native.SimulatorConfiguration=SimpleNamespace;native.CameraSensorSpec=SimpleNamespace;native.AgentState=SimpleNamespace
    native.SensorType=SimpleNamespace(COLOR='color',DEPTH='depth');native.SensorSubType=SimpleNamespace(PINHOLE='pinhole')
    native.agent=SimpleNamespace(AgentConfiguration=lambda:SimpleNamespace(action_space={}))
    native.Configuration=lambda simulator,agents:(simulator,agents)
    optical=SimpleNamespace(position=[0.,2.,0.],rotation=np.eye(3))
    down=SimpleNamespace(position=[0.,1.,0.],rotation=np.array([[1.,0.,0.],[0.,0.,1.],[0.,-1.,0.]]))
    class Sim:
        def __init__(self,config):
            calls.append(('construct',));self._sensors={name:SimpleNamespace(_sensor_object=SimpleNamespace(render_camera=SimpleNamespace(projection_matrix=np.diag([2.,2.,-1.,1.]))), draw_observation=lambda:None, get_observation=lambda name=name:self.get_sensor_observations()[name]) for name in ['rgb','depth','nav']}
            self.agent=SimpleNamespace(set_state=lambda *a,**kw:calls.append(('set_pose',)),get_state=lambda:SimpleNamespace(sensor_states={'rgb':optical,'depth':optical,'nav':down},position=[0.,0.,0.],rotation=np.eye(3)))
        def seed(self,value):
            calls.append(('seed',value))
            if fail_seed:raise RuntimeError('native seed failed')
        def get_agent(self,index):return self.agent
        def get_sensor_observations(self):
            calls.append(('capture',));return dict(rgb=np.ones((2,3,4),np.uint8),depth=np.ones((2,3),np.float32),nav=np.ones((4,5),np.float32))
        def get_world_time(self):return 0.
        def reset(self):calls.append(('reset',))
        def close(self):calls.append(('close',))
    native.Simulator=Sim
    utils=types.ModuleType('habitat_sim.utils');common=types.ModuleType('habitat_sim.utils.common');common.quat_from_coeffs=lambda values:values
    for name,module in [('habitat_sim',native),('habitat_sim.utils',utils),('habitat_sim.utils.common',common)]:monkeypatch.setitem(sys.modules,name,module)
    spec=dict(sensor_id='rgbd',rgb_uuid='rgb',depth_uuid='depth',resolution_hw=[99,99],position_xyz=[0.,1.,0.],orientation_xyz_rad=[0.,0.,0.],hfov_deg=90.,depth_min_m=.1,depth_max_m=10.)
    config=dict(scene_id='fixture-scene',episode_id='episode',seed=7,initial_position=[0.,0.,0.],initial_rotation_xyzw=[0.,0.,0.,1.],primary=spec,navigation=dict(spec,sensor_id='nav',depth_uuid='nav'))
    return config,calls


def test_native_seed_applied_before_pose_or_capture_and_ack_binds_exact_config(monkeypatch):
    import hashlib
    config,calls=habitat_stub(monkeypatch);capture=HabitatCapture(config)
    try:
        ack=capture.execution_ack
        assert calls[:3]==[('construct',),('seed',7),('set_pose',)]
        assert ack==dict(schema_version=1,episode_id='episode',clock_domain=capture.clock_domain,seed=7,seed_method='habitat_sim.Simulator.seed',seed_applied=True,
            config_sha256=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),runtime_version='cpu-fixture-habitat-v1')
        observation_from_packet(capture.capture('primary'))
        assert calls.index(('seed',7))<calls.index(('capture',))
    finally:capture.close()


def test_native_failed_seed_never_returns_ack_and_closes_simulator(monkeypatch):
    config,calls=habitat_stub(monkeypatch,fail_seed=True)
    with pytest.raises(RuntimeError,match='native seed failed'):HabitatCapture(config)
    assert calls==[('construct',),('seed',7),('close',)]


def test_unseeded_legacy_worker_does_not_claim_applied_seed(monkeypatch):
    config,calls=habitat_stub(monkeypatch);config.pop('seed');capture=HabitatCapture(config)
    try:
        assert capture.execution_ack is None
        assert not any(row[0]=='seed' for row in calls)
    finally:capture.close()


def actual_worker_script(tmp_path):
    script=tmp_path/'sensor.py'
    tests=Path(__file__).resolve().parent
    script.write_text(f'import sys\nsys.path.insert(0,{str(tests)!r})\nimport pytest\nfrom test_sensor_execution_metadata import habitat_stub\nhabitat_stub(pytest.MonkeyPatch())\nfrom neusymnav.sensors.habitat_worker import main\nraise SystemExit(main())\n')
    return script


def test_seeded_real_ipc_ack_and_actual_decoded_resolution_per_lane(tmp_path,monkeypatch):
    from neusymnav.sensors.client import HabitatPoseSource
    import hashlib
    config,_=habitat_stub(monkeypatch);script=actual_worker_script(tmp_path)
    source=HabitatPoseSource(python=sys.executable,config=config,worker_script=script,timeout_s=3)
    try:
        initial=source.runtime_metadata
        assert initial['execution']['seed']==7 and initial['seed_status']=='applied'
        assert initial['worker_script_sha256']==hashlib.sha256(script.read_bytes()).hexdigest()
        assert initial['actual_resolution_hw']=={}
        primary=source.capture();navigation=source.capture_navigation()
        actual=source.runtime_metadata['actual_resolution_hw']
        assert actual['primary']['resolution_hw']==[2,3]
        assert actual['navigation']['resolution_hw']==[4,5]
        assert actual['primary']['source']==dict(episode_id='episode',sensor_id='rgbd',frame_index=0)
        assert actual['navigation']['capture_monotonic_ns']==navigation.capture_monotonic_ns
        assert actual['primary']['clock_domain']==primary.clock_domain
        assert initial['actual_resolution_hw']=={} # independent metadata snapshot
    finally:assert source.close()['clean_shutdown']


def ready_worker(tmp_path,execution,*,packet=None):
    script=tmp_path/'bad-ready.py'
    ready=dict(ready=True,wire_version=1,pose_source='simulator_ground_truth',execution=execution)
    script.write_text('import json,sys\n'+f'print(json.dumps({ready!r}),flush=True)\n'+('for line in sys.stdin:\n if json.loads(line)["op"]=="close":break\n' if packet is None else f'packet=json.loads({json.dumps(json.dumps(packet))})\nfor line in sys.stdin:\n if json.loads(line)["op"]=="close":break\n print(json.dumps(dict(ok=True,packet=packet)),flush=True)\n'))
    return script


@pytest.mark.parametrize('field,bad',[(None,None),('seed',8),('seed',True),('schema_version',True),('seed_applied',1),('episode_id','other'),('clock_domain','host_monotonic:other'),('config_sha256','0'*64),('seed_method','requested_only'),('extra','unversioned')])
def test_seeded_ipc_rejects_absent_or_mismatched_ack(tmp_path,monkeypatch,field,bad):
    import hashlib
    from neusymnav.sensors.client import HabitatPoseSource
    from neusymnav.sensors.habitat_worker import host_clock_domain
    config,_=habitat_stub(monkeypatch)
    execution=dict(schema_version=1,seed=7,seed_applied=True,episode_id='episode',clock_domain=host_clock_domain(),seed_method='habitat_sim.Simulator.seed',config_sha256=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest(),runtime_version='cpu-fixture')
    if field is None:execution=None
    else:execution[field]=bad
    script=ready_worker(tmp_path,execution)
    with pytest.raises((ValueError,RuntimeError),match='seed|execution|ACK'):HabitatPoseSource(python=sys.executable,config=config,worker_script=script,timeout_s=2)


def test_seed_ack_cannot_survive_successful_reset_or_later_captures(tmp_path,monkeypatch):
    from neusymnav.sensors.client import HabitatPoseSource
    config,_=habitat_stub(monkeypatch);source=HabitatPoseSource(python=sys.executable,config=config,worker_script=actual_worker_script(tmp_path),timeout_s=3)
    try:
        original=source.runtime_metadata['execution'];source.capture()
        source.reset('episode-2',position=(0.,0.,0.),rotation_xyzw=(0.,0.,0.,1.))
        assert source.runtime_metadata['execution'] is None
        assert source.runtime_metadata['seed_status']=='unsupported_after_reset'
        assert source.capture().key.episode_id=='episode-2'
        assert source.runtime_metadata['execution'] is None
        assert original['episode_id']=='episode'
    finally:source.close()


def test_native_reset_invalidates_original_episode_ack(monkeypatch):
    config,calls=habitat_stub(monkeypatch);capture=HabitatCapture(config)
    # Add only the native reset dependency; exercise the actual worker reset.
    capture.sim.reset=lambda: calls.append(('reset',))
    try:
        capture.reset('episode-2',[0.,0.,0.],[0.,0.,0.,1.])
        assert capture.execution_ack is None
        capture.capture('primary')
        assert capture.execution_ack is None
    finally:capture.close()


def test_seeded_first_capture_must_share_ack_clock_and_reaps_bad_worker(tmp_path,monkeypatch):
    import hashlib
    from test_sensor_adapter import sample
    from neusymnav.sensors.habitat_worker import host_clock_domain,encode_packet
    from neusymnav.sensors.client import HabitatPoseSource
    config,_=habitat_stub(monkeypatch)
    execution=dict(schema_version=1,seed=7,seed_applied=True,episode_id='episode',clock_domain=host_clock_domain(),seed_method='habitat_sim.Simulator.seed',config_sha256=hashlib.sha256(json.dumps(config,sort_keys=True,separators=(',',':')).encode()).hexdigest(),runtime_version='cpu-fixture')
    source=HabitatPoseSource(python=sys.executable,config=config,worker_script=ready_worker(tmp_path,execution,packet=encode_packet(sample())),timeout_s=2)
    with pytest.raises(ValueError,match='clock domain'):source.capture()
    assert source.process.poll() is not None
    assert source.runtime_metadata['actual_resolution_hw']=={}


def test_metadata_publication_still_respects_whole_capture_deadline(tmp_path,monkeypatch):
    import time
    from neusymnav.sensors import client
    config,_=habitat_stub(monkeypatch)
    source=client.HabitatPoseSource(python=sys.executable,config=config,worker_script=actual_worker_script(tmp_path),timeout_s=3)
    original=client.asdict
    def slow_key(value):time.sleep(.04);return original(value)
    monkeypatch.setattr(client,'asdict',slow_key);source.timeout_s=.03
    try:
        with pytest.raises(TimeoutError):source.capture()
        assert source.process.poll() is not None
    finally:source.close()


def test_ready_ack_validation_overrun_never_publishes_applied_seed_and_reaps_worker(tmp_path,monkeypatch):
    import hashlib,time
    from neusymnav.sensors import client
    from neusymnav.sensors.habitat_worker import _canonical,host_clock_domain
    config=dict(seed=7,episode_id='episode')
    ack=dict(schema_version=1,seed=7,seed_applied=True,episode_id='episode',clock_domain=host_clock_domain(),seed_method='habitat_sim.Simulator.seed',config_sha256=hashlib.sha256(_canonical(config)).hexdigest(),runtime_version='cpu-fixture')
    script=ready_worker(tmp_path,ack)
    real_clock=time.monotonic;offset=[0.]
    monkeypatch.setattr(client.time,'monotonic',lambda:real_clock()+offset[0])
    original=client.host_clock_domain
    def clock_proof_past_deadline():
        result=original();offset[0]+=4.;return result
    monkeypatch.setattr(client,'host_clock_domain',clock_proof_past_deadline)
    # Retain the failed constructor instance to inspect its public proof state.
    source=client.HabitatPoseSource.__new__(client.HabitatPoseSource)
    try:
        with pytest.raises(TimeoutError):
            source.__init__(python=sys.executable,config=config,worker_script=script,timeout_s=3.)
        assert source.runtime_metadata['execution'] is None
        assert source.runtime_metadata['seed_status']!='applied'
        assert source.process.poll() is not None
    finally:source.close()
