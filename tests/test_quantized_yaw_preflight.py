"""Native float32 prediction is preparation, never trial actuation or proof repair."""
from dataclasses import asdict, replace
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.sensors import habitat_worker as worker


class Float32Quaternion:
    """CPU fixture mirrors Magnum's stored quaternion and operation API."""
    def __init__(self, vector, scalar):
        self.vector=np.array(vector,np.float32);self.scalar=np.float32(scalar)

    def __mul__(self, other):
        return type(self)(self.scalar*other.vector+other.scalar*self.vector+np.cross(self.vector,other.vector),
                          self.scalar*other.scalar-np.dot(self.vector,other.vector))

    def normalized(self):
        length=np.sqrt(np.dot(self.vector,self.vector)+self.scalar*self.scalar)
        return type(self)(self.vector/length,self.scalar/length)

    @classmethod
    def rotation(cls, angle, axis):
        half=np.float32(angle)/np.float32(2)
        return cls(np.asarray(axis,np.float32)*np.sin(half),np.cos(half))


FAKE_MAGNUM=SimpleNamespace(Quaternion=Float32Quaternion,
    Vector3=SimpleNamespace(y_axis=lambda:np.array([0,1,0],np.float32)),
    Deg=lambda value:np.float32(value),
    Rad=lambda value:np.float32(value*np.float32(math.pi/180.)))


class BodyState:
    def __init__(self, position):
        self.position=np.array(position,float)
        self.quaternion=Float32Quaternion([0,0,0],1)

    @property
    def rotation(self):
        return worker._quaternion_matrix(np.r_[self.quaternion.vector,self.quaternion.scalar].astype(float))


def attach_native_yaw(worker_instance, state):
    class Node:
        parent=SimpleNamespace(absolute_transformation=lambda:np.eye(4))
        @property
        def rotation(self):return state.quaternion
    worker_instance.agent.scene_node=Node()
    worker_instance._yaw_math=worker._NativeYawMath(FAKE_MAGNUM,lambda action:True)


def turn_state(state, action, amount):
    direction=1 if action=='turn_left' else -1
    delta=Float32Quaternion.rotation(FAKE_MAGNUM.Rad(FAKE_MAGNUM.Deg(direction*amount)),[0,1,0])
    state.quaternion=(state.quaternion*delta).normalized()


def test_missing_yaw_native_profile_cannot_actuate(monkeypatch):
    from test_sensor_actuation import actuator,execute
    instance,command,calls,_,_=actuator(monkeypatch)
    instance._yaw_math=None
    result=execute(instance,replace(command,linear_mps=0.,yaw_radps=.2))
    assert not result['executed'] and not calls
    assert result['reason']=='yaw_preflight_unavailable'


def test_preflight_exists_and_never_enlarges_requested_float_amount():
    native=getattr(worker,'_NativeYawMath',None)
    assert native is not None,'quantized native yaw preflight is absent'
    state=BodyState([0,0,0]);instance=SimpleNamespace(agent=SimpleNamespace())
    attach_native_yaw(instance,state)
    for amount in [3.,2.99208522,.1,1e-30]:
        selected=instance._yaw_math.prepare(instance.agent,state,'turn_right',amount)
        if selected is not None:
            chosen,predicted=selected
            assert 0<chosen<=amount and float(np.float32(chosen))==chosen


def test_original_native_failed_proofs_are_still_rejected():
    from neusymnav.contracts import FrameKey,MotionCommand
    from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof
    # Exact immutable v1 command/source/proof witnesses from native indices85/97.
    witnesses=json.loads(r'''[{"command":{"source":{"episode_id":"p10-native-runtime6-00861-seed-0-yaw-proof-diagnostic","sensor_id":"downward-depth","frame_index":85},"map_revision":86,"issued_monotonic_ns":690269426916,"deadline_monotonic_ns":690369426916,"clock_domain":"host_monotonic:60e7b56f-47c5-4e34-9ea3-4f534e9acdb7","linear_mps":0.0,"yaw_radps":-0.5235987755982988,"reason":"bounded yaw proof diagnostic","source_capture_monotonic_ns":690267085641},"source":{"schema_version":"runtime_measurement_source_v1","key":{"episode_id":"p10-native-runtime6-00861-seed-0-yaw-proof-diagnostic","sensor_id":"downward-depth","frame_index":85},"capture_monotonic_ns":690267085641,"clock_domain":"host_monotonic:60e7b56f-47c5-4e34-9ea3-4f534e9acdb7","pose_version":85,"calibration_id":"habitat:1d4485d279858ff8b63435399682ff13e7697a024c1326e1af362d347b902683"},"proof":{"schema_version":1,"command_sha256":"259a2b7e853f4d26bc574062f376ef92195481b1b1828ffe7e796c401a24e7ec","source":{"schema_version":"runtime_measurement_source_v1","key":{"episode_id":"p10-native-runtime6-00861-seed-0-yaw-proof-diagnostic","sensor_id":"downward-depth","frame_index":85},"capture_monotonic_ns":690267085641,"clock_domain":"host_monotonic:60e7b56f-47c5-4e34-9ea3-4f534e9acdb7","pose_version":85,"calibration_id":"habitat:1d4485d279858ff8b63435399682ff13e7697a024c1326e1af362d347b902683"},"map_revision":86,"source_pose_version":85,"actions":[{"index":0,"action":"turn_right","amount":2.9920852199999994,"pre_step_monotonic_ns":690269829061,"post_step_monotonic_ns":690269886996,"pose_version_before":85,"pose_version_after":86,"body_before_xy":[0.0588863343000412,-0.2093828022480011],"body_after_xy":[0.0588863343000412,-0.2093828022480011],"yaw_before_rad":-2.6926975338059136,"yaw_after_rad":-2.7449194058642106}],"complete":true,"reason":"executed"}},{"command":{"source":{"episode_id":"p10-native-runtime6-00861-seed-0-yaw-proof-diagnostic","sensor_id":"downward-depth","frame_index":97},"map_revision":98,"issued_monotonic_ns":690321358281,"deadline_monotonic_ns":690421358281,"clock_domain":"host_monotonic:60e7b56f-47c5-4e34-9ea3-4f534e9acdb7","linear_mps":0.0,"yaw_radps":-0.5235987755982988,"reason":"bounded yaw proof diagnostic","source_capture_monotonic_ns":690318960414},"source":{"schema_version":"runtime_measurement_source_v1","key":{"episode_id":"p10-native-runtime6-00861-seed-0-yaw-proof-diagnostic","sensor_id":"downward-depth","frame_index":97},"capture_monotonic_ns":690318960414,"clock_domain":"host_monotonic:60e7b56f-47c5-4e34-9ea3-4f534e9acdb7","pose_version":97,"calibration_id":"habitat:d4990e3b7fe9d459fe4e887eb0a1a89c308ccf7bbacbaa658b6f8832efd83368"},"proof":{"schema_version":1,"command_sha256":"0340fc988171b9ab0dfabef70a272001319d1be54bcec569be9a7088348b2184","source":{"schema_version":"runtime_measurement_source_v1","key":{"episode_id":"p10-native-runtime6-00861-seed-0-yaw-proof-diagnostic","sensor_id":"downward-depth","frame_index":97},"capture_monotonic_ns":690318960414,"clock_domain":"host_monotonic:60e7b56f-47c5-4e34-9ea3-4f534e9acdb7","pose_version":97,"calibration_id":"habitat:d4990e3b7fe9d459fe4e887eb0a1a89c308ccf7bbacbaa658b6f8832efd83368"},"map_revision":98,"source_pose_version":97,"actions":[{"index":0,"action":"turn_right","amount":2.9919087899999997,"pre_step_monotonic_ns":690321767079,"post_step_monotonic_ns":690321827618,"pose_version_before":97,"pose_version_after":98,"body_before_xy":[0.0588863343000412,-0.2093828022480011],"body_after_xy":[0.0588863343000412,-0.2093828022480011],"yaw_before_rad":2.9639009402377288,"yaw_after_rad":2.911682176145984}],"complete":true,"reason":"executed"}}]''')
    for raw in witnesses:
        command=MotionCommand(**dict(raw['command'],source=FrameKey(**raw['command']['source'])))
        with pytest.raises(ValueError,match='yaw bounds mismatch'):
            validate_actuation_source_proof(raw['proof'],command,raw['source'],modality='depth_only')


@pytest.mark.parametrize('amount',[0.,-1.,float('nan'),float('inf'),4.,1e-100])
def test_invalid_or_float32_underflow_amount_has_no_candidate(amount):
    state=BodyState([0,0,0]);instance=SimpleNamespace(agent=SimpleNamespace())
    attach_native_yaw(instance,state)
    assert instance._yaw_math.prepare(instance.agent,state,'turn_left',amount) is None


@pytest.mark.parametrize('angle',[0.,3.13,-3.13,2.7])
@pytest.mark.parametrize('action',['turn_left','turn_right'])
def test_native_prediction_handles_wraparound_and_actual_nonunit_float32(angle,action):
    state=BodyState([0,0,0]);state.quaternion=Float32Quaternion([0,math.sin(angle/2),0],math.cos(angle/2))
    instance=SimpleNamespace(agent=SimpleNamespace());attach_native_yaw(instance,state)
    selected=instance._yaw_math.prepare(instance.agent,state,action,2.99208522)
    assert selected is not None
    amount,expected=selected
    turn_state(state,action,amount)
    assert instance._yaw_math.matches(instance.agent,state,expected)


@pytest.mark.parametrize('invalid',['parent','state','nan','nonunit','profile','native_type','api'])
def test_unknown_body_or_parent_cannot_yaw(invalid):
    state=BodyState([0,0,0]);instance=SimpleNamespace(agent=SimpleNamespace());attach_native_yaw(instance,state)
    supplied=state
    if invalid=='parent':instance.agent.scene_node.parent=SimpleNamespace(absolute_transformation=lambda:np.diag([2.,1.,1.,1.]))
    elif invalid=='state':supplied=SimpleNamespace(rotation=np.diag([-1.,1.,-1.]),position=np.zeros(3))
    elif invalid=='nan':state.quaternion.scalar=np.float32('nan')
    elif invalid=='nonunit':state.quaternion.scalar=np.float32(2)
    elif invalid=='profile':instance._yaw_math.agent_supported=lambda agent:False
    elif invalid=='api':instance._yaw_math.mn=SimpleNamespace(Quaternion=Float32Quaternion)
    else:instance._yaw_math.mn=SimpleNamespace(Quaternion=tuple)
    assert instance._yaw_math.prepare(instance.agent,supplied,'turn_left',3.) is None


def test_candidate_search_cap_is_no_step_not_trial_actuation(monkeypatch):
    from test_sensor_actuation import actuator,execute
    instance,command,calls,_,state=actuator(monkeypatch);attempts=[]
    before=worker.canonical_robot_pose(state)['yaw_rad']
    def excessive(values,action,amount):
        attempts.append(amount)
        return values,before+math.radians(amount)+2e-7
    instance._yaw_math.predict=excessive
    result=execute(instance,replace(command,linear_mps=0.,yaw_radps=.2))
    assert not result['executed'] and not calls and len(attempts)==32
    assert all(a>b>0 for a,b in zip(attempts,attempts[1:]))
    assert instance._navigation_state is None and instance.last_actuation_proof is None


def test_final_ttl_gate_follows_prediction_and_no_amount_is_mutated_after_prediction(monkeypatch):
    from test_actuation_proof_ipc import paired
    from test_sensor_actuation import execute
    instance,command,calls,clock,_=paired(monkeypatch)
    prepare=instance._yaw_math.prepare
    def slow(*args):
        value=prepare(*args);clock[0]+=101_000_000;return value
    instance._yaw_math.prepare=slow
    result=execute(instance,replace(command,linear_mps=0.,yaw_radps=.2))
    assert not result['executed'] and not calls
    assert result['reason']=='expired_before_step'


def test_configured_amount_is_exact_candidate_in_result_and_proof(monkeypatch):
    from test_actuation_proof_ipc import paired
    from test_sensor_actuation import execute
    from neusymnav.runtime.actuation_measurements import validate_actuation_proof
    instance,command,calls,_,obs=paired(monkeypatch)
    command=replace(command,linear_mps=0.,yaw_radps=.2)
    chosen=[];prepare=instance._yaw_math.prepare
    def record(*args):
        value=prepare(*args);chosen.append(value[0]);return value
    instance._yaw_math.prepare=record
    monkeypatch.setattr(Path,'read_bytes',lambda path:pytest.fail('file I/O in actuation preparation'))
    result=execute(instance,command)
    assert result['executed'] and chosen==[calls[0][1]]
    assert chosen[0]==result['actions'][0]['amount']==instance.last_actuation_proof['actions'][0]['amount']
    assert chosen[0]==instance.agent.agent_config.action_space['__neusymnav_guarded_pulse__'].actuation.amount
    assert validate_actuation_proof(instance.last_actuation_proof,command,obs)['action_count']==1


def test_actual_prediction_mismatch_clears_proof_and_consumes_source(monkeypatch):
    from test_sensor_actuation import actuator,execute
    instance,command,calls,_,state=actuator(monkeypatch);act=instance.agent.act
    def unexpected(action):
        act(action);turn_state(state,'turn_left',.001)
    instance.agent.act=unexpected
    with pytest.raises(RuntimeError,match='native yaw prediction mismatch'):
        execute(instance,replace(command,linear_mps=0.,yaw_radps=.2))
    assert len(calls)==1 and instance._navigation_state is None and instance.last_actuation_proof is None


def test_yaw_unavailable_after_translation_keeps_only_actual_partial_proof(monkeypatch):
    from test_actuation_proof_ipc import paired
    from test_sensor_actuation import execute
    from neusymnav.runtime.actuation_measurements import validate_actuation_proof
    instance,command,calls,_,obs=paired(monkeypatch);instance._yaw_math=None
    command=replace(command,yaw_radps=.2)
    result=execute(instance,command)
    assert result['executed'] and result['reason']=='yaw_preflight_unavailable' and len(calls)==1
    assert validate_actuation_proof(instance.last_actuation_proof,command,obs)['action_count']==1


@pytest.mark.parametrize('yaw',[1e-44,-1e-44])
def test_positive_float32_degree_that_underflows_native_increment_does_not_step(monkeypatch,yaw):
    from test_sensor_actuation import actuator,execute
    instance,command,calls,_,_=actuator(monkeypatch)
    version=instance.pose_version
    result=execute(instance,replace(command,linear_mps=0.,yaw_radps=yaw))
    assert not result['executed'] and not calls
    assert result['reason']=='yaw_preflight_unavailable'
    assert instance.pose_version==version and instance._navigation_state is None
    assert instance.last_actuation_proof is None


def test_nonzero_native_increment_with_unobservable_body_yaw_is_not_a_step():
    state=BodyState([0,0,0]);instance=SimpleNamespace(agent=SimpleNamespace());attach_native_yaw(instance,state)
    # This degree is represented, but adding its rotation to this stored native
    # state can have an exactly zero canonical delta; no proof may claim a step.
    state.quaternion=Float32Quaternion([0,.5,0],math.sqrt(.75))
    assert instance._yaw_math.prepare(instance.agent,state,'turn_left',1e-30) is None
