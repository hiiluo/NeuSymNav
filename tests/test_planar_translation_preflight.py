"""A guarded upper bound may shrink to a host-valid native float32 move."""
from dataclasses import replace
import copy
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.sensors import habitat_worker as worker
from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof
from test_planar_fixed_y_adapter import planar_actuator, NativeTransform, NativeVector
from test_quantized_yaw_preflight import Float32Quaternion, turn_state
from test_sensor_actuation import execute


SAVED_WORLD_CASES = [
    (.001257687795403885, -.9999949932098389, .0031618205830454826),
    (.0018479669077715705, -.999969482421875, .007811988703906536),
    (.0023839655608383368, -.9999020099639893, .014000781811773777),
]


def saved_actuator(monkeypatch, case):
    requested,qy,qw=case
    w,c,calls,clock,state,filtered=planar_actuator(monkeypatch,anchor=.10685312747955322)
    state.position=np.array([-7.492470741271973,w._planar_anchor_y,11.001697540283203])
    state.quaternion=Float32Quaternion([0.,qy,0.],qw)
    w._navigation_state.update(body_source_xyz=tuple(state.position),**worker.canonical_robot_pose(state))
    c=replace(c,linear_mps=requested/.1)
    return w,c,calls,clock,state,filtered


def proof_source(w,c):
    return dict(schema_version='runtime_measurement_source_v1',key=dict(episode_id='ep',sensor_id='nav',frame_index=1),
        capture_monotonic_ns=c.source_capture_monotonic_ns,clock_domain=c.clock_domain,
        pose_version=4,calibration_id='planar-fixture')


@pytest.mark.parametrize('case',SAVED_WORLD_CASES)
def test_saved_zero_world_cases_select_positive_smaller_host_valid_motion(monkeypatch,case):
    w,c,calls,_,state,filtered=saved_actuator(monkeypatch,case)
    before=state.position.copy()
    result=execute(w,c)
    assert result['displacement_m']>0, 'native world rounding must be preflighted before the real filter/action'
    assert 0<calls[0][1]<=case[0]
    assert len(calls)==len(filtered)==1
    assert state.position[1]==before[1]
    assert validate_actuation_source_proof(w.last_actuation_proof,c,proof_source(w,c),modality='depth_only')['action_count']==1


@pytest.mark.parametrize('case,old_after,reason',[
    (SAVED_WORLD_CASES[0],[-7.492462635040283,-11.002955436706543],'translation bounds mismatch'),
    (SAVED_WORLD_CASES[1],[-7.492441654205322,-11.003544807434082],'outside forward segment'),
    (SAVED_WORLD_CASES[2],[-7.492403984069824,-11.004080772399902],'translation bounds mismatch'),
])
def test_original_unfiltered_world_endpoints_still_cannot_be_valid_proofs(monkeypatch,case,old_after,reason):
    w,c,_,_,_,_=saved_actuator(monkeypatch,case)
    execute(w,c)
    bad=copy.deepcopy(w.last_actuation_proof)
    bad['actions'][0]['amount']=case[0]
    bad['actions'][0]['body_after_xy']=old_after
    with pytest.raises(ValueError,match=reason):
        validate_actuation_source_proof(bad,c,proof_source(w,c),modality='depth_only')


def test_preparation_reads_body_once_and_exhausts_32_distances_without_native_side_effects(monkeypatch):
    w,_,_,_,state,_=planar_actuator(monkeypatch)
    state.position=np.array([1e9,3.,1e9])
    reads=[];w.agent.get_state=lambda:reads.append(True) or state
    w.agent.act=lambda *args:pytest.fail('trial native action during translation preparation')
    w.sim.step_filter=lambda *args:pytest.fail('trial native filter during translation preparation')
    w.sim.get_sensor_observations=lambda:pytest.fail('render during translation preparation')
    requested=.02;candidates=[];multiply=NativeVector.__mul__
    def record(self,other):
        candidates.append(-other)
        return multiply(self,other)
    monkeypatch.setattr(NativeVector,'__mul__',record)
    before=state.position.copy()
    assert w._planar_math.prepare_translation(w.agent,requested) is None
    assert reads==[True] and len(candidates)==32
    assert candidates==[requested*(step/32) for step in range(32,0,-1)]
    assert all(a>b>0 for a,b in zip(candidates,candidates[1:]))
    assert np.array_equal(state.position,before)


@pytest.mark.parametrize('amount',[True,None,'1',0.,-1.,float('nan'),float('inf'),1e-100])
def test_invalid_or_unrepresentable_distance_has_no_candidate(monkeypatch,amount):
    w,_,_,_,_,_=planar_actuator(monkeypatch)
    assert w._planar_math.prepare_translation(w.agent,amount) is None


@pytest.mark.parametrize('invalid',['agent','control','type','parent_scale','parent_rotation','parent_shear','parent_nan','tilt','world'])
def test_translation_preparation_rejects_unknown_native_body_or_parent(monkeypatch,invalid):
    w,_,_,_,state,_=planar_actuator(monkeypatch)
    if invalid=='agent':w._planar_math.agent_supported=lambda a:False
    elif invalid=='control':w._planar_math.action_supported=lambda:False
    elif invalid=='type':w._planar_math.body_math.mn.Vector3=tuple
    elif invalid.startswith('parent_'):
        parent=np.eye(4)
        if invalid=='parent_scale':parent[0,0]=2.
        elif invalid=='parent_rotation':parent[:2,:2]=[[0.,-1.],[1.,0.]]
        elif invalid=='parent_shear':parent[0,1]=.1
        else:parent[0,0]=float('nan')
        w.agent.scene_node.parent=SimpleNamespace(absolute_transformation=lambda:NativeTransform(parent))
    elif invalid=='tilt':state.quaternion=Float32Quaternion([1e-9,0.,0.],1.)
    else:state.position[0]=float('nan')
    assert w._planar_math.prepare_translation(w.agent,.02) is None


def test_final_ttl_after_translation_search_prevents_any_action_or_query(monkeypatch):
    w,c,calls,clock,_,filtered=saved_actuator(monkeypatch,SAVED_WORLD_CASES[0])
    prepare=w._planar_math.prepare_translation
    def slow(*args):
        prepared=prepare(*args);clock[0]+=101_000_000;return prepared
    w._planar_math.prepare_translation=slow
    result=execute(w,c)
    assert result['reason']=='expired_before_step' and not calls and not filtered
    assert w._navigation_state is None and w.last_actuation_proof['actions']==[]


@pytest.mark.parametrize('yaw_velocity',[0.,.2])
def test_exact_selected_amount_binds_native_action_and_proof_with_mixed_yaw(monkeypatch,yaw_velocity):
    w,c,calls,_,state,filtered=saved_actuator(monkeypatch,SAVED_WORLD_CASES[0])
    requested=SAVED_WORLD_CASES[0][0];chosen=[];prepare=w._planar_math.prepare_translation
    def record(*args):
        result=prepare(*args);chosen.append(result['amount']);return result
    w._planar_math.prepare_translation=record
    act=w.agent.act
    def mixed(action):
        spec=w.agent.agent_config.action_space[action]
        if spec.name=='move_forward':act(action)
        else:
            calls.append((spec.name,spec.actuation.amount));turn_state(state,spec.name,spec.actuation.amount)
    w.agent.act=mixed
    c=replace(c,yaw_radps=yaw_velocity)
    monkeypatch.setattr(Path,'read_bytes',lambda path:pytest.fail('file I/O in actuation preparation'))
    result=execute(w,c)
    assert result['executed'] and len(chosen)==1 and len(filtered)==1
    assert chosen[0]==calls[0][1]==result['actions'][0]['amount']==w.last_actuation_proof['actions'][0]['amount']
    assert 0<chosen[0]<=requested/(2 if yaw_velocity else 1)
    assert validate_actuation_source_proof(w.last_actuation_proof,c,proof_source(w,c),modality='depth_only')['action_count']==(2 if yaw_velocity else 1)


def test_native_amount_representation_change_cannot_invalidate_preflight(monkeypatch):
    w,c,calls,_,_,filtered=saved_actuator(monkeypatch,SAVED_WORLD_CASES[0])
    class RoundingSpec:
        def __init__(self,amount):self.amount=amount
        @property
        def amount(self):return self._amount
        @amount.setter
        def amount(self,value):self._amount=float(np.float32(value))
    w.habitat_sim.agent.ActuationSpec=RoundingSpec
    with pytest.raises(RuntimeError,match='amount changed after prediction'):
        execute(w,c)
    assert not calls and not filtered and w.last_actuation_proof is None


def test_unreversible_translated_parent_candidate_is_skipped_before_action(monkeypatch):
    w,_,calls,_,state,filtered=planar_actuator(monkeypatch)
    state.position=np.array([2.,3.,-2.])
    original=w.agent.scene_node
    transform=np.eye(4);transform[2,3]=-1.
    parent=NativeTransform(transform)
    class Translated(type(original)):
        @property
        def translation(self):return NativeVector(state.position-[0.,0.,-1.])
    w.agent.scene_node=Translated()
    w.agent.scene_node.parent=SimpleNamespace(absolute_transformation=lambda:parent)
    # Actual float32 translated-parent arithmetic: full requested candidate
    # rolls back to z=-1.9999998807907104 rather than the saved z=-2.
    prepared=w._planar_math.prepare_translation(w.agent,.005)
    assert prepared is not None and 0<prepared['amount']<.005
    rollback=parent.transform_point(prepared['local_end']+(prepared['start']-prepared['end']))
    assert np.array_equal(rollback,prepared['start'])
    assert not calls and not filtered and state.position.tolist()==[2.,3.,-2.]
