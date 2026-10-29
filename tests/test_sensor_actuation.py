"""P07 actuator tests use real worker logic, fake native physics, and real IPC."""
from dataclasses import asdict, replace
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import numpy as np
import pytest

from neusymnav.contracts import FrameKey, MotionCommand
from neusymnav.sensors.client import HabitatPoseSource
from neusymnav.sensors.habitat_worker import HabitatCapture, canonical_robot_pose, host_clock_domain


def actuator(monkeypatch, *, clip=1., slide=False):
    """Native act/filter and physics are separate; Simulator.step also renders."""
    clock = [1_000_000_000]
    monkeypatch.setattr('neusymnav.sensors.habitat_worker.time.monotonic_ns', lambda: clock[0])
    w = HabitatCapture.__new__(HabitatCapture)
    w.clock_domain, w.episode_id, w.pose_version = host_clock_domain(), 'ep', 4
    w._last_map_revision = -1
    from test_quantized_yaw_preflight import BodyState,attach_native_yaw,turn_state
    state = BodyState([2., 3., 4.])
    w.agent = SimpleNamespace(get_state=lambda: state, controls=SimpleNamespace(),
                             agent_config=SimpleNamespace(action_space={}))
    w.habitat_sim = SimpleNamespace(agent=SimpleNamespace(
        ActionSpec=lambda name, actuation: SimpleNamespace(name=name, actuation=actuation),
        ActuationSpec=lambda amount: SimpleNamespace(amount=amount)))
    calls = []
    def act(action):
        spec = w.agent.agent_config.action_space[action]
        calls.append((spec.name, spec.actuation.amount))
        if spec.name == 'move_forward':
            target = state.position + state.rotation @ np.array([0., 0., -spec.actuation.amount])
            state.position = np.asarray(w.agent.controls.move_filter_fn(state.position, target))
        else:
            turn_state(state,spec.name,spec.actuation.amount)
    def filter_pose(start, end):
        p = start + clip * (end-start)
        if slide:
            p[0] += .01
        return p
    world_time = [0.]
    def physics(dt):
        world_time[0] += dt
    def step(action):
        w.agent.act(action)
        w.sim.step_physics(1./60.)
        return w.sim.get_sensor_observations()
    w.agent.act = act
    attach_native_yaw(w,state)
    w.sim = SimpleNamespace(step_filter=filter_pose, step=step, step_physics=physics,
        get_world_time=lambda:world_time[0], get_sensor_observations=lambda:{})
    w._navigation_state = dict(episode_id='ep',sensor_id='nav',frame_index=1,
        capture_monotonic_ns=clock[0]-1,pose_version=4,clock_domain=w.clock_domain,
        **canonical_robot_pose(state))
    command = MotionCommand(FrameKey('ep','nav',1),3,clock[0],clock[0]+100_000_000,
        w.clock_domain,.2,0.,'test',clock[0]-1)
    return w, command, calls, clock, state


def execute(w, command, version=4):
    return w.execute(asdict(command),version)


def test_known_forward_units_and_capture_paired_robot_pose(monkeypatch):
    w,c,calls,clock,state = actuator(monkeypatch)
    pose = w.robot_pose()
    assert pose['robot_xy'] == [2.,-4.]
    assert pose['yaw_rad'] == pytest.approx(math.pi/2)
    # Camera extrinsics never enter the body-pose calculation.
    state.sensor_states = {'nav': SimpleNamespace(position=[99.,99.,99.], rotation=np.eye(3))}
    assert w.robot_pose() == pose
    result = execute(w,c)
    assert calls == [('move_forward',pytest.approx(.02))]
    assert result['displacement_m'] == pytest.approx(.02)
    assert state.position == pytest.approx([2.,3.,3.98])
    assert execute(w,c)['reason'] == 'source_replayed_or_mismatched'
    with pytest.raises(ValueError,match='fresh navigation'):
        w.robot_pose()


@pytest.mark.parametrize('sign',[1,-1])
def test_yaw_radps_converts_to_degrees_and_canonical_positive_left(monkeypatch,sign):
    w,c,calls,clock,state = actuator(monkeypatch)
    c=replace(c,linear_mps=0.,yaw_radps=sign*math.radians(30))
    result=execute(w,c)
    assert calls == [('turn_left' if sign>0 else 'turn_right',pytest.approx(3.))]
    assert result['yaw_rad'] == pytest.approx(sign*math.radians(3))


def test_simultaneous_motion_stays_on_initial_tangent_then_half_yaw(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    result=execute(w,replace(c,yaw_radps=math.radians(30)))
    assert calls == [('move_forward',pytest.approx(.01)),('turn_left',pytest.approx(1.5))]
    assert result['displacement_m'] <= .02+1e-9
    assert result['yaw_rad'] == pytest.approx(math.radians(1.5))


@pytest.mark.parametrize('clip,slide,expected',[(.25,False,.005),(1.,True,0.)])
def test_real_filter_hook_clips_and_rejects_sideways_slide(monkeypatch,clip,slide,expected):
    w,c,_,_,_=actuator(monkeypatch,clip=clip,slide=slide)
    assert execute(w,c)['displacement_m'] == pytest.approx(expected)


@pytest.mark.parametrize('change,reason',[
    ({'clock_domain':'host_monotonic:other'},'clock_domain_mismatch'),
    ({'deadline_monotonic_ns':1_000_000_000},'expired_or_zero'),
    ({'linear_mps':0.},'expired_or_zero'),
    ({'source':FrameKey('wrong','nav',1)},'source_replayed_or_mismatched'),
    ({'source':FrameKey('ep','primary',1)},'source_replayed_or_mismatched'),
    ({'source':FrameKey('ep','nav',2)},'source_replayed_or_mismatched'),
    ({'source_capture_monotonic_ns':999_999_998},'source_replayed_or_mismatched'),
    ({'issued_monotonic_ns':1_000_000_001},'future_or_invalid_command'),
    ({'linear_mps':.21},'motion_limits_exceeded'),
    ({'linear_mps':-.1},'motion_limits_exceeded'),
])
def test_worker_fail_closed_and_consumes_source(monkeypatch,change,reason):
    w,c,calls,_,_=actuator(monkeypatch)
    result=execute(w,replace(c,**change))
    assert not result['executed'] and result['reason']==reason
    assert not calls and w._navigation_state is None


def test_pose_revision_map_revision_and_stale_capture_block(monkeypatch):
    for case in ['pose','map','stale']:
        w,c,calls,clock,state=actuator(monkeypatch)
        if case=='pose': w.pose_version += 1
        if case=='map': w._last_map_revision = 5
        if case=='stale':
            clock[0] += 301_000_000
            c=replace(c,issued_monotonic_ns=clock[0],deadline_monotonic_ns=clock[0]+100_000_000)
        assert not execute(w,c)['executed'] and not calls


def test_deadline_rechecked_after_action_configuration(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    def slow_spec(name,actuation):
        clock[0] += 101_000_000
        return SimpleNamespace(name=name,actuation=actuation)
    w.habitat_sim.agent.ActionSpec=slow_spec
    assert execute(w,c)['reason']=='expired_before_step'
    assert not calls


@pytest.mark.parametrize('yaw', [0., .2])
def test_source_ttl_is_authoritative_during_action_configuration(monkeypatch, yaw):
    w,c,calls,clock,state=actuator(monkeypatch)
    capture=c.source_capture_monotonic_ns
    clock[0]=capture+295_000_000
    c=replace(c,issued_monotonic_ns=clock[0],deadline_monotonic_ns=clock[0]+100_000_000,
              yaw_radps=yaw)
    def slow_spec(name,actuation):
        clock[0] += 10_000_000
        return SimpleNamespace(name=name,actuation=actuation)
    w.habitat_sim.agent.ActionSpec=slow_spec
    result=execute(w,c)
    assert not result['executed'] and result['reason']=='expired_before_step'
    assert not calls and w._navigation_state is None


def test_source_ttl_bounds_simultaneous_budget_and_second_pulse(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    capture=c.source_capture_monotonic_ns
    clock[0]=capture+295_000_000
    c=replace(c,issued_monotonic_ns=clock[0],deadline_monotonic_ns=clock[0]+100_000_000,
              yaw_radps=.2)
    physics=w.sim.step_physics
    def slow_physics(dt):
        physics(dt)
        clock[0] += 6_000_000
    w.sim.step_physics=slow_physics
    result=execute(w,c)
    assert result['executed'] and result['reason']=='expired_before_step'
    # Five ms of source lifetime, split evenly: .2m/s * .0025s.
    assert calls == [('move_forward',pytest.approx(.0005))]
    assert w._navigation_state is None


def test_second_action_expiry_does_not_execute_and_partial_source_consumed(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    physics=w.sim.step_physics
    def slow_physics(dt):
        physics(dt)
        clock[0] += 101_000_000
    w.sim.step_physics=slow_physics
    result=execute(w,replace(c,yaw_radps=.2))
    assert result['executed'] and result['reason']=='expired_before_step'
    assert len(calls)==1 and w._navigation_state is None


def test_collision_filter_absence_blocks_and_never_teleports(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    del w.sim.step_filter
    with pytest.raises(RuntimeError,match='collision filter'):
        execute(w,c)
    assert not calls and w._navigation_state is None


@pytest.mark.parametrize('delay,expired',[(0.,False),(.12,True)])
def test_external_process_checks_deadline_after_ipc_and_source_is_one_use(delay,expired):
    path=Path(__file__).parent/'fixtures/actuation/worker.py'
    source=HabitatPoseSource(python=sys.executable,config={'delay_s':delay},worker_script=path,timeout_s=2.)
    try:
        obs=source.capture_navigation()
        pose=source.robot_pose(obs)
        assert pose['source']==obs.key and pose['robot_xy']==(1.,-3.)
        now=time.monotonic_ns()
        c=MotionCommand(obs.key,1,now,now+100_000_000,obs.clock_domain,.2,0.,'test',obs.capture_monotonic_ns)
        result=source.execute(c)
        assert result['executed'] is not expired
        assert result['displacement_m'] <= .02+1e-9
        assert not source.execute(c)['executed']
    finally:
        assert source.close()['clean_shutdown']


def test_actual_capture_stores_agent_body_pose_and_sensor_identity(monkeypatch):
    from neusymnav.sensors.client import observation_from_packet
    w,c,calls,clock,state=actuator(monkeypatch)
    spec=dict(sensor_id='nav',depth_uuid='depth',depth_min_m=.1,depth_max_m=10.)
    w.config={'navigation':spec}
    w.indices={'navigation':0}
    state.sensor_states={'depth':SimpleNamespace(position=np.array([8.,9.,10.]),
        rotation=np.array([[1.,0.,0.],[0.,0.,1.],[0.,-1.,0.]]))}
    w._K=lambda uuid,shape:np.eye(3)
    w.sim._sensors={'depth':SimpleNamespace(draw_observation=lambda:None, get_observation=lambda:np.ones((2,3),np.float32))}
    w.sim.get_world_time=lambda:0.
    obs=observation_from_packet(w.capture('navigation'))
    paired=w.robot_pose()
    assert paired['source']==asdict(obs.key)
    assert paired['capture_monotonic_ns']==obs.capture_monotonic_ns
    assert paired['pose_version']==obs.pose_version==4
    assert paired['robot_xy']==[2.,-4.]
    assert obs.T_world_camera[:2,3]==pytest.approx([8.,-10.])
    # Mutating actual body after capture cannot update the stored source pose.
    state.position=np.array([2.1,3.,4.])
    assert w.robot_pose()==paired
    command=replace(c,source=obs.key,source_capture_monotonic_ns=obs.capture_monotonic_ns)
    with pytest.raises(RuntimeError,match='pose changed'):
        execute(w,command)
    assert not calls


def test_step_exception_invalidates_source_and_partial_motion_cannot_replay(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    def broken(action):
        raise RuntimeError('native action failed')
    w.agent.act=broken
    with pytest.raises(RuntimeError,match='native action failed'):
        execute(w,c)
    assert w._navigation_state is None
    assert not execute(w,c)['executed']


def test_low_level_step_invalidates_navigation_source(monkeypatch):
    w,c,calls,clock,state=actuator(monkeypatch)
    w.agent.agent_config.action_space['test']=None
    w.sim.step=lambda action:None
    w.step('test')
    assert w._navigation_state is None and w.pose_version==5
    assert not execute(w,c)['executed']
