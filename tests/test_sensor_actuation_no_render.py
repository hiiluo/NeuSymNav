"""Guarded native actions retain physics/source proof without rendering images."""
from dataclasses import replace
import math
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.runtime.actuation_measurements import validate_actuation_proof
from neusymnav.sensors.client import observation_from_packet
from neusymnav.sensors.habitat_worker import canonical_robot_pose
from test_actuation_proof_ipc import paired
from test_sensor_actuation import actuator,execute


@pytest.mark.parametrize('linear,yaw,actions',[(.2,0.,1),(0.,.2,1),(.2,-.2,2)])
def test_guarded_actions_advance_physics_and_body_proof_without_render(monkeypatch,linear,yaw,actions):
    worker,command,calls,clock,obs=paired(monkeypatch)
    command=replace(command,linear_mps=linear,yaw_radps=yaw)
    events=[]
    native_act=worker.agent.act
    physics=worker.sim.step_physics
    def act(action):
        events.append(('act',action,clock[0]))
        native_act(action)
        clock[0]+=1_000_000
    def step_physics(dt):
        events.append(('physics',dt,clock[0]))
        physics(dt)
        clock[0]+=2_000_000
    def forbidden_render():
        raise AssertionError('guarded actuation rendered sensor arrays')
    worker.agent.act=act
    worker.sim.step_physics=step_physics
    worker.sim.get_sensor_observations=forbidden_render
    result=execute(worker,command)
    checked=validate_actuation_proof(worker.last_actuation_proof,command,obs)
    assert result['executed'] and checked['action_count']==actions
    assert [event[0] for event in events]==['act','physics']*actions
    assert all(event[1]=='__neusymnav_guarded_pulse__' for event in events[::2])
    assert all(event[1]==pytest.approx(1./60.) for event in events[1::2])
    assert worker.sim.get_world_time()==pytest.approx(actions/60.)
    assert worker.pose_version==4+actions
    assert checked['body_translation_m']==pytest.approx(result['displacement_m'])
    assert result['displacement_m']<=.02+1e-9 and abs(result['yaw_rad'])<=math.radians(3.)+1e-9
    for index,proof in enumerate(worker.last_actuation_proof['actions']):
        assert proof['pre_step_monotonic_ns']==events[index*2][2]
        assert proof['post_step_monotonic_ns']==events[index*2+1][2]+2_000_000
    assert len(calls)==actions
    assert not execute(worker,command)['executed']
    assert worker.last_actuation_proof is None and worker._navigation_state is None


@pytest.mark.parametrize('owner,name',[('agent','act'),('sim','step_physics')])
@pytest.mark.parametrize('value',[None,False])
def test_missing_public_no_render_api_blocks_before_any_native_movement(monkeypatch,owner,name,value):
    worker,command,calls,_,_=actuator(monkeypatch)
    setattr(getattr(worker,owner),name,value)
    worker.last_actuation_proof={'old':True}
    with pytest.raises(RuntimeError,match='actuation blocked'):
        execute(worker,command)
    assert not calls and worker.sim.get_world_time()==0.
    assert worker._navigation_state is None and worker.last_actuation_proof is None


@pytest.mark.parametrize('clip,slide,distance',[(.25,False,.005),(1.,True,0.)])
def test_no_render_action_preserves_native_collision_filter(monkeypatch,clip,slide,distance):
    worker,command,calls,_,_=actuator(monkeypatch,clip=clip,slide=slide)
    worker.sim.step=lambda _:pytest.fail('rendering simulator step used')
    result=execute(worker,command)
    assert result['displacement_m']==pytest.approx(distance)
    assert len(calls)==1 and worker.sim.get_world_time()==pytest.approx(1./60.)


def test_physics_latency_expires_second_action_without_extending_source_ttl(monkeypatch):
    worker,command,calls,clock,obs=paired(monkeypatch)
    clock[0]=command.source_capture_monotonic_ns+295_000_000
    command=replace(command,issued_monotonic_ns=clock[0],deadline_monotonic_ns=clock[0]+100_000_000,yaw_radps=.2)
    physics=worker.sim.step_physics
    def slow_physics(dt):
        physics(dt)
        clock[0]+=6_000_000
    worker.sim.step_physics=slow_physics
    worker.sim.step=lambda _:pytest.fail('rendering simulator step used')
    result=execute(worker,command)
    assert result['executed'] and result['reason']=='expired_before_step'
    assert calls==[('move_forward',pytest.approx(.0005))]
    assert worker.sim.get_world_time()==pytest.approx(1./60.)
    assert validate_actuation_proof(worker.last_actuation_proof,command,obs)['action_count']==1
    assert worker._navigation_state is None


@pytest.mark.parametrize('owner,name',[('agent','act'),('sim','step_physics')])
def test_native_or_physics_error_leaves_no_reusable_source_or_old_proof(monkeypatch,owner,name):
    worker,command,calls,_,_=actuator(monkeypatch)
    def broken(_):
        raise RuntimeError('native failure')
    setattr(getattr(worker,owner),name,broken)
    worker.last_actuation_proof={'old':True}
    with pytest.raises(RuntimeError,match='native failure'):
        execute(worker,command)
    assert worker.last_actuation_proof is None and worker._navigation_state is None
    assert not execute(worker,command)['executed']
    assert len(calls)==(1 if owner=='sim' else 0)


def test_explicit_capture_after_no_render_action_reads_current_body_sensor_pose_and_sim_time(monkeypatch):
    worker,command,calls,_,state=actuator(monkeypatch)
    renders=[]
    down=np.array([[1.,0.,0.],[0.,0.,1.],[0.,-1.,0.]])
    def get_state():
        sensor=SimpleNamespace(position=state.position+state.rotation@np.array([.2,.5,0.]),rotation=state.rotation@down)
        return SimpleNamespace(position=state.position.copy(),rotation=state.rotation.copy(),sensor_states={'depth':sensor})
    def render():
        renders.append('explicit capture')
        return {'depth':np.ones((2,3),np.float32)}
    worker.agent.get_state=get_state
    worker.sim._sensors={'depth':SimpleNamespace(draw_observation=lambda:None, get_observation=lambda:render()['depth'])}
    worker.config={'navigation':dict(sensor_id='nav',depth_uuid='depth',depth_min_m=.1,depth_max_m=10.)}
    worker.indices={'navigation':2}
    worker._K=lambda uuid,shape:np.eye(3)
    result=execute(worker,command)
    assert result['executed'] and len(calls)==1 and not renders
    obs=observation_from_packet(worker.capture('navigation'))
    pose=worker.robot_pose()
    assert renders==['explicit capture']
    assert obs.sim_time_s==pytest.approx(1./60.) and obs.pose_version==5
    assert obs.key.frame_index==2 and pose['source']['frame_index']==2
    assert pose['robot_xy']==pytest.approx(canonical_robot_pose(state)['robot_xy'])
    assert obs.T_world_camera[:3,3]==pytest.approx([2.2,-3.98,3.5])
    assert pose['robot_xy']!=list(obs.T_world_camera[:2,3])
