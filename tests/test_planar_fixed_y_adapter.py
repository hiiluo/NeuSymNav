"""Opt-in constant-height simulator actuation keeps actual native Y unchanged."""
from dataclasses import replace
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.sensors import habitat_worker as worker
from test_sensor_actuation import actuator, execute
from test_quantized_yaw_preflight import FAKE_MAGNUM, Float32Quaternion


class NativeVector(np.ndarray):
    def __new__(cls,values):return np.asarray(values,np.float32).view(cls)
    @staticmethod
    def y_axis():return NativeVector([0.,1.,0.])
    def dot(self,other=None):return np.asarray(self).dot(np.asarray(self) if other is None else other)


class NativeTransform(np.ndarray):
    def __new__(cls,values):return np.asarray(values,np.float32).view(cls)
    def transform_point(self,point):return NativeVector(np.asarray(self)[:3,:3]@point+np.asarray(self)[:3,3])


def planar_actuator(monkeypatch, *, anchor=3., candidate_y=None):
    w,command,calls,clock,state=actuator(monkeypatch)
    state.position[1]=anchor
    w._motion_adapter='planar_fixed_y_v1';w._planar_anchor_y=anchor
    # Model the positively qualified native API, not a permissive numpy-only
    # state. Unknown qualification deliberately remains unavailable.
    node=w.agent.scene_node
    def to_matrix(q):
        # Native Quaternion.to_matrix uses its represented float32 components;
        # AgentState's numpy-quaternion conversion normalizes independently.
        x,y,z=q.vector;scalar=q.scalar;two=np.float32(2);one=np.float32(1)
        return np.array([[one-two*(y*y+z*z),two*(x*y-z*scalar),two*(x*z+y*scalar)],
            [two*(x*y+z*scalar),one-two*(x*x+z*z),two*(y*z-x*scalar)],
            [two*(x*z-y*scalar),two*(y*z+x*scalar),one-two*(x*x+y*y)]],np.float32)
    monkeypatch.setattr(Float32Quaternion,'to_matrix',to_matrix,raising=False)
    class NativeNode(type(node)):
        parent=SimpleNamespace(absolute_transformation=lambda:NativeTransform(np.eye(4)))
        @property
        def translation(self):return NativeVector(state.position)
        @property
        def absolute_translation(self):return NativeVector(state.position)
        @property
        def transformation(self):
            value=np.eye(4);value[:3,:3]=state.quaternion.to_matrix();value[:3,3]=state.position
            return value
    w.agent.scene_node=NativeNode()
    cls=getattr(worker,'_NativePlanarMath',None)
    native_math=SimpleNamespace(Quaternion=Float32Quaternion,Vector3=NativeVector,Matrix4=NativeTransform)
    w._planar_math=None if cls is None else cls(native_math,lambda agent:True,lambda:True)
    w._navigation_state.update(body_source_xyz=tuple(state.position),body_source_up=(0.,1.,0.),calibration_id='planar-fixture')
    filtered=[]
    def contact(start,end):
        candidate=np.asarray(end,dtype=np.float64).copy();candidate[1]=anchor if candidate_y is None else candidate_y
        filtered.append((start.copy(),end.copy(),candidate.copy()))
        return candidate
    w.sim.step_filter=contact
    # Habitat ObjectControls first moves, then corrects by filter_end-end_pos.
    # This is not a set_state repair after action or a nonnative pose shortcut.
    def act(action):
        spec=w.agent.agent_config.action_space[action];calls.append((spec.name,spec.actuation.amount))
        assert spec.name=='move_forward'
        start=NativeVector(state.position)
        end=NativeVector(start+NativeVector(state.quaternion.to_matrix()[:,2])*(-spec.actuation.amount))
        state.position=np.asarray(end,float)
        candidate=w.agent.controls.move_filter_fn(start,end)
        state.position=np.asarray(NativeVector(state.position)+(candidate-end),float)
    w.agent.act=act
    w._planar_initial_valid=True
    return w,command,calls,clock,state,filtered


def test_saved_00802_vertical_candidate_advances_only_xz_in_opt_in_mode(monkeypatch):
    witness=json.loads((Path(__file__).parent/'fixtures/regressions/collision-filter-00802.json').read_text())
    anchor=witness['initial_position'][1]
    w,command,calls,_,state,filtered=planar_actuator(monkeypatch,anchor=anchor,candidate_y=witness['calls'][0]['candidate'][1])
    # Retain exact immutable saved start/end/candidate, independent of a new
    # float32 forward rotation's rounding. The callback sees native moved body.
    saved=witness['calls'][0];state.position=np.asarray(saved['start'],float)
    state.quaternion=Float32Quaternion([0.,math.sqrt(.5),0.],math.sqrt(.5))
    w._navigation_state.update(body_source_xyz=tuple(state.position),**worker.canonical_robot_pose(state))
    def act(action):
        spec=w.agent.agent_config.action_space[action];calls.append((spec.name,spec.actuation.amount))
        start=np.asarray(saved['start']);end=np.asarray(saved['end']);state.position=end.copy()
        candidate=w.agent.controls.move_filter_fn(start,end)
        state.position+=np.asarray(candidate)-end
    w.agent.act=act
    w.sim.step_filter=lambda start,end:np.asarray(saved['candidate'])
    command=replace(command,linear_mps=.04970822)
    result=execute(w,command)
    assert result['displacement_m']>0.0049
    assert state.position[1]==anchor
    assert state.position[[0,2]]==pytest.approx(np.asarray(saved['end'])[[0,2]],abs=1e-12)
    assert result['actions'][0]['amount']<=.005 and w.last_actuation_proof['complete']
    assert len(calls)==1


@pytest.mark.parametrize('mode',[None,'strict_3d','planar_fixed_y_v1'])
def test_default_and_explicit_strict_keep_original_vertical_rejection(monkeypatch,mode):
    w,c,_,_,state,_=planar_actuator(monkeypatch,candidate_y=2.98)
    if mode is None:del w._motion_adapter
    else:w._motion_adapter=mode
    result=execute(w,c)
    assert result['displacement_m']==pytest.approx(.02 if mode=='planar_fixed_y_v1' else 0.)
    assert state.position[1]==3.


@pytest.mark.parametrize('height,accepted',[
    (-.05,True),(.05,True),
    (float(np.nextafter(-.05,-math.inf)),False),
    (float(np.nextafter(.05,math.inf)),False),
    (-.04,True),(.04,True),(.051,False),(-.051,False),
    (float('nan'),False),(float('inf'),False),
])
def test_fixed_launch_height_slab_is_closed_and_never_tracks_candidate(monkeypatch,height,accepted):
    w,c,_,_,state,_=planar_actuator(monkeypatch,anchor=0.,candidate_y=height)
    result=execute(w,c)
    assert result['displacement_m']==pytest.approx(.02 if accepted else 0.)
    assert state.position[1]==0.


@pytest.mark.parametrize('fraction,sideways,accepted',[
    (1.,0.,True),(.25,0.,True),(0.,0.,False),(-.1,0.,False),
    (float(np.nextafter(1.,math.inf)),0.,False),(1.01,0.,False),
    (.5,float(np.nextafter(np.float32(1e-7),np.float32(0.))),True),
    (.5,1e-7,False),(.5,float(np.nextafter(1e-7,math.inf)),False),
])
def test_only_same_certified_xz_segment_can_clip_translation(monkeypatch,fraction,sideways,accepted):
    w,c,_,_,state,_=planar_actuator(monkeypatch,anchor=0.)
    # Use binary-exact xz segment coordinates for exact fraction boundaries.
    state.position=np.zeros(3);w._navigation_state.update(body_source_xyz=(0.,0.,0.),**worker.canonical_robot_pose(state))
    c=replace(c,linear_mps=.15625)
    def filtered(start,end):
        start,end=np.asarray(start,dtype=np.float64),np.asarray(end,dtype=np.float64)
        candidate=start+fraction*(end-start);candidate[0]+=sideways;candidate[1]=-.02
        return candidate
    w.sim.step_filter=filtered
    result=execute(w,c)
    assert result['displacement_m']==pytest.approx(math.hypot(.015625*fraction,sideways) if accepted else 0.,abs=1e-12)
    assert state.position[1]==0.


@pytest.mark.parametrize('invalid',[
    'unsupported','initial','agent','control','native_type','parent_scale','parent_rotation',
    'parent_shear','parent_nan','tilt','tiny_tilt','local_scale','world_position','body_height','source_height',
    'missing_source','source_tilt','source_tiny_tilt','source_nan',
])
def test_unknown_tilted_transformed_or_changed_height_never_steps(monkeypatch,invalid):
    w,c,calls,_,state,_=planar_actuator(monkeypatch)
    node=w.agent.scene_node
    if invalid=='unsupported':w._planar_math=None
    elif invalid=='initial':w._planar_initial_valid=False
    elif invalid=='agent':w._planar_math.agent_supported=lambda agent:False
    elif invalid=='control':w._planar_math.action_supported=lambda:False
    elif invalid=='native_type':w._planar_math.body_math.mn=SimpleNamespace(Quaternion=tuple)
    elif invalid.startswith('parent_'):
        transform=np.eye(4)
        if invalid=='parent_scale':transform[0,0]=2.
        elif invalid=='parent_rotation':transform[:2,:2]=[[0.,-1.],[1.,0.]]
        elif invalid=='parent_shear':transform[0,1]=.1
        else:transform[0,0]=float('nan')
        node.parent=SimpleNamespace(absolute_transformation=lambda:transform)
    elif invalid=='tilt':state.quaternion=Float32Quaternion([math.sin(.01),0.,0.],math.cos(.01))
    elif invalid=='tiny_tilt':state.quaternion=Float32Quaternion([1e-9,0.,0.],1.)
    elif invalid=='local_scale':
        class Scaled(type(node)):
            @property
            def transformation(self):return np.diag([2.,1.,1.,1.])
        w.agent.scene_node=Scaled()
    elif invalid=='world_position':
        class Wrong(type(node)):
            @property
            def absolute_translation(self):return state.position+[.01,0.,0.]
        w.agent.scene_node=Wrong()
    elif invalid=='body_height':state.position[1]+=.000001
    elif invalid=='source_height':w._navigation_state['body_source_xyz']=(2.,3.000001,4.)
    elif invalid=='missing_source':w._navigation_state.pop('body_source_xyz')
    elif invalid=='source_tilt':w._navigation_state['body_source_up']=(0.,.999,.01)
    elif invalid=='source_tiny_tilt':w._navigation_state['body_source_up']=(0.,1.,1e-9)
    else:w._navigation_state['body_source_xyz']=(2.,float('nan'),4.)
    result=execute(w,c)
    assert not result['executed'] and result['reason']=='planar_adapter_unavailable'
    assert not calls and w.pose_version==4 and w._navigation_state is None
    assert w.last_actuation_proof is None


def test_translation_qualification_is_independent_of_yaw_preflight(monkeypatch):
    w,c,calls,_,state,_=planar_actuator(monkeypatch,candidate_y=2.98);w._yaw_math=None
    result=execute(w,c)
    assert result['executed'] and result['displacement_m']==pytest.approx(.02)
    assert state.position[1]==3. and len(calls)==1


@pytest.mark.parametrize('drift',[.001,5e-8])
def test_actual_vertical_mutation_is_rejected_without_pose_repair_or_proof(monkeypatch,drift):
    w,c,calls,_,state,_=planar_actuator(monkeypatch);act=w.agent.act
    def changed(action):act(action);state.position[1]+=drift
    w.agent.act=changed
    with pytest.raises(RuntimeError,match='planar body/height changed'):execute(w,c)
    assert state.position[1]==3.+drift and len(calls)==1 and w.last_actuation_proof is None


def test_source_body_height_change_within_anchor_band_cannot_be_hidden(monkeypatch):
    w,c,calls,_,state,_=planar_actuator(monkeypatch)
    state.position[1]+=5e-8
    result=execute(w,c)
    assert not result['executed'] and not calls and w.last_actuation_proof is None


def test_fixed_anchor_blocks_repeated_ramp_even_after_fresh_capture(monkeypatch):
    w,c,_,clock,state,_=planar_actuator(monkeypatch,anchor=0.,candidate_y=.04)
    assert execute(w,c)['displacement_m']==pytest.approx(.02)
    assert state.position[1]==0.
    clock[0]+=1_000_000
    w._navigation_state=dict(episode_id='ep',sensor_id='nav',frame_index=2,capture_monotonic_ns=clock[0]-1,
        pose_version=5,clock_domain=w.clock_domain,body_source_xyz=tuple(state.position),body_source_up=(0.,1.,0.),
        calibration_id='planar-fixture',**worker.canonical_robot_pose(state))
    c=replace(c,source=replace(c.source,frame_index=2),source_capture_monotonic_ns=clock[0]-1,
        issued_monotonic_ns=clock[0],deadline_monotonic_ns=clock[0]+100_000_000,map_revision=4)
    w.sim.step_filter=lambda start,end:np.array([end[0],.08,end[2]])
    assert execute(w,c,version=5)['displacement_m']==0.
    assert state.position[1]==0.


def test_planar_preflight_cannot_extend_final_ttl_or_reuse_source(monkeypatch):
    w,c,calls,clock,state,_=planar_actuator(monkeypatch,candidate_y=2.98)
    valid=w._planar_math.valid;count=[0]
    def slow(*args):
        count[0]+=1;result=valid(*args)
        if count[0]==2:clock[0]+=101_000_000
        return result
    w._planar_math.valid=slow
    result=execute(w,c)
    assert not result['executed'] and result['reason']=='expired_before_step' and not calls
    assert state.position[1]==3.
    assert execute(w,c)['reason']=='expired_or_zero'


def test_planar_raw_step_has_no_unguarded_action_or_pose_advance(monkeypatch):
    w,_,calls,_,_,_=planar_actuator(monkeypatch)
    version=w.pose_version
    w.agent.agent_config.action_space['move_forward']=SimpleNamespace(name='move_forward',actuation=SimpleNamespace(amount=.25))
    w.sim.step=lambda action:calls.append(('unguarded_step',action))
    with pytest.raises(ValueError,match='source-bound execute'):w.step('move_forward')
    assert not calls and w.pose_version==version


@pytest.mark.parametrize('mode',['strict_3d','planar_fixed_y_v1'])
@pytest.mark.parametrize('height,tilt,accepted',[(3.,False,True),(4.,False,False),(3.+5e-8,False,False),(3.,True,False),(float('nan'),False,False)])
def test_planar_reset_validates_before_native_reset_but_strict_reset_stays_legacy(monkeypatch,mode,height,tilt,accepted):
    w,_,_,_,_,_=planar_actuator(monkeypatch);w._motion_adapter=mode
    w._episodes={'ep'};w.execution_ack={'seed_applied':True};calls=[]
    w.sim.reset=lambda:calls.append('reset')
    w._set_pose=lambda position,rotation:calls.append(('set_pose',position,rotation))
    rotation=[math.sin(.01),0.,0.,math.cos(.01)] if tilt else [0.,0.,0.,1.]
    if mode=='strict_3d' or accepted:
        w.reset('ep-2',[2.,height,4.],rotation)
        assert calls[0]=='reset' and calls[1][0]=='set_pose'
        assert w.execution_ack is None and w.episode_id=='ep-2' and w.pose_version==0
        assert w._navigation_state is None and w._planar_anchor_y==3.
    else:
        with pytest.raises(ValueError,match='launch height and upright'):w.reset('ep-2',[2.,height,4.],rotation)
        assert calls==[] and w.episode_id=='ep' and w.pose_version==4
        assert w.execution_ack=={'seed_applied':True}


@pytest.mark.parametrize('mode',[None,'strict_3d','planar_fixed_y_v1'])
def test_startup_mode_anchor_and_unsupported_capture_only_backend(monkeypatch,mode):
    from test_sensor_execution_metadata import habitat_stub
    from neusymnav.sensors.client import observation_from_packet
    config,calls=habitat_stub(monkeypatch)
    if mode is not None:config['motion_adapter']=mode
    capture=worker.HabitatCapture(config)
    try:
        assert capture._motion_adapter==('strict_3d' if mode is None else mode)
        assert capture._planar_anchor_y==0.
        assert capture._planar_math is None and not capture._planar_initial_valid
        obs=observation_from_packet(capture.capture('navigation'))
        if mode=='planar_fixed_y_v1':
            assert capture._navigation_state['body_source_xyz']==(0.,0.,0.)
            assert capture._navigation_state['body_source_up']==(0.,1.,0.)
        else:assert 'body_source_xyz' not in capture._navigation_state
        assert obs.pose_version==0 and not any(row[0]=='reset' for row in calls)
    finally:capture.close()


@pytest.mark.parametrize('bad',['planar',True,None,1,{},[]])
def test_unknown_adapter_is_rejected_before_simulator_startup(monkeypatch,bad):
    from test_sensor_execution_metadata import habitat_stub
    config,calls=habitat_stub(monkeypatch);config['motion_adapter']=bad
    with pytest.raises(ValueError,match='motion_adapter'):worker.HabitatCapture(config)
    assert calls==[]


@pytest.mark.parametrize('position',[[0.,float('nan'),0.],[0.,float('inf'),0.],[0.,1.],[0.,1.,2.,3.]])
def test_nonfinite_or_malformed_anchor_rejected_before_simulator_startup(monkeypatch,position):
    from test_sensor_execution_metadata import habitat_stub
    config,calls=habitat_stub(monkeypatch);config.update(motion_adapter='planar_fixed_y_v1',initial_position=position)
    with pytest.raises(ValueError,match='finite source-world xyz'):worker.HabitatCapture(config)
    assert calls==[]


def test_planar_success_consumes_source_and_proof_v1_stays_exact(monkeypatch):
    from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof
    w,c,calls,_,state,_=planar_actuator(monkeypatch,candidate_y=2.98)
    source=dict(schema_version='runtime_measurement_source_v1',key=dict(episode_id='ep',sensor_id='nav',frame_index=1),
        capture_monotonic_ns=c.source_capture_monotonic_ns,clock_domain=c.clock_domain,
        pose_version=4,calibration_id='planar-fixture')
    result=execute(w,c)
    verified=validate_actuation_source_proof(w.last_actuation_proof,c,source,modality='depth_only')
    assert verified['action_count']==1 and result['displacement_m']==pytest.approx(.02)
    assert w.last_actuation_proof['schema_version']==1 and state.position[1]==3.
    assert execute(w,c)['reason']=='source_replayed_or_mismatched' and len(calls)==1


def test_actual_capture_keeps_native_source_height_and_up_separate_from_camera(monkeypatch):
    from neusymnav.sensors.client import observation_from_packet
    w,_,_,_,state,_=planar_actuator(monkeypatch)
    w.config={'navigation':dict(sensor_id='nav',depth_uuid='depth',depth_min_m=.1,depth_max_m=10.)}
    w.indices={'navigation':0}
    state.sensor_states={'depth':SimpleNamespace(position=[8.,9.,10.],rotation=np.array([[1.,0.,0.],[0.,0.,1.],[0.,-1.,0.]]))}
    w._K=lambda *args:np.eye(3)
    w.sim._sensors={'depth':SimpleNamespace(draw_observation=lambda:None,
        get_observation=lambda:np.ones((2,3),np.float32))}
    obs=observation_from_packet(w.capture('navigation'))
    assert w._navigation_state['body_source_xyz']==(2.,3.,4.)
    assert w._navigation_state['body_source_up']==(0.,1.,0.)
    assert obs.T_world_camera[:3,3]==pytest.approx([8.,-10.,9.])
    assert 'body_source_xyz' not in json.loads(obs.to_json())


def test_saved_runtime10_represented_endpoint_cannot_emit_invalid_forward_proof(monkeypatch):
    from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof
    proof_before=[2.7526586055755615,5.162430286407471]
    proof_after=[2.7514634132385254,5.162425994873047]
    yaw=-3.1380968235830613;amount=.0011951623508512177
    w,c,calls,_,state,_=planar_actuator(monkeypatch,anchor=.12399999797344208)
    state.position=np.array([proof_before[0],w._planar_anchor_y,-proof_before[1]])
    # Native -Z heading has canonical yaw=pi/2+native Y rotation.
    angle=math.remainder(yaw-math.pi/2,2*math.pi)
    state.quaternion=Float32Quaternion([0.,math.sin(angle/2),0.],math.cos(angle/2))
    measured=worker.canonical_robot_pose(state)
    w._navigation_state.update(body_source_xyz=tuple(state.position),**measured)
    source=dict(schema_version='runtime_measurement_source_v1',key=dict(episode_id='ep',sensor_id='nav',frame_index=1),
        capture_monotonic_ns=c.source_capture_monotonic_ns,clock_domain=c.clock_domain,pose_version=4,calibration_id='planar-fixture')
    end=np.array([proof_after[0],w._planar_anchor_y,-proof_after[1]])
    def act(action):
        spec=w.agent.agent_config.action_space[action];calls.append((spec.name,spec.actuation.amount))
        start=state.position.copy();state.position=end.copy()
        selected=w.agent.controls.move_filter_fn(NativeVector(start),NativeVector(end))
        state.position=np.asarray(NativeVector(state.position)+NativeVector(selected-NativeVector(end)),float)
    w.agent.act=act
    w.sim.step_filter=lambda start,end:NativeVector([end[0],.11060764640569687,end[2]])
    c=replace(c,linear_mps=amount/.1)
    result=execute(w,c)
    validate_actuation_source_proof(w.last_actuation_proof,c,source,modality='depth_only')
    assert result['displacement_m']==0. and list(state.position[[0,2]])==[proof_before[0],-proof_before[1]]


def test_retained_runtime10_invalid_proof_is_still_rejected():
    from neusymnav.contracts import MotionCommand, FrameKey
    from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof
    path=Path(__file__).parent/'fixtures/regressions/runtime10-invalid-proofs.json'
    raw=json.loads(path.read_text())[0]
    command=MotionCommand(**dict(raw['command'],source=FrameKey(**raw['command']['source'])))
    with pytest.raises(ValueError,match='body moved outside forward segment'):
        validate_actuation_source_proof(raw['proof'],command,raw['proof']['source'],modality='depth_only')


def test_unpredicted_native_endpoint_is_not_published_as_valid_proof(monkeypatch):
    w,c,_,_,state,_=planar_actuator(monkeypatch);act=w.agent.act
    def unexpected(action):
        act(action)
        state.position[0]=float(np.nextafter(np.float32(state.position[0]),np.float32(math.inf)))
    w.agent.act=unexpected
    with pytest.raises(RuntimeError,match='planar translation prediction mismatch'):execute(w,c)
    assert w.last_actuation_proof is None and w._navigation_state is None


def test_unrepresentable_native_translation_is_no_action_not_trial_move(monkeypatch):
    w,c,calls,_,state,_=planar_actuator(monkeypatch)
    before=state.position.copy()
    result=execute(w,replace(c,linear_mps=1e-20))
    assert not result['executed'] and result['reason']=='planar_translation_unavailable' and not calls
    assert np.array_equal(state.position,before) and w.pose_version==4
