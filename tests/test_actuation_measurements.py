from dataclasses import asdict, replace
import copy
import pytest
from neusymnav.contracts import MotionCommand
from test_runtime_scheduling import source
from neusymnav.runtime.actuation_measurements import validate_actuation_proof, command_sha256, ActuationMeasurements


def evidence():
    obs=source(0,modality='depth_only');c=MotionCommand(obs.key,1,1_000_000_010,1_100_000_000,obs.clock_domain,.2,0.,'frontier',obs.capture_monotonic_ns)
    s=dict(schema_version='runtime_measurement_source_v1',key=asdict(obs.key),capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain,pose_version=obs.pose_version,calibration_id=obs.calibration_id)
    p=dict(schema_version=1,command_sha256=command_sha256(c),source=s,map_revision=1,source_pose_version=obs.pose_version,actions=[dict(index=0,action='move_forward',amount=.01,pre_step_monotonic_ns=1_000_000_020,post_step_monotonic_ns=1_001_000_000,pose_version_before=obs.pose_version,pose_version_after=obs.pose_version+1,body_before_xy=[0.,0.],body_after_xy=[.01,0.],yaw_before_rad=0.,yaw_after_rad=0.)],complete=True,reason='executed')
    return obs,c,p


def test_strict_proof_uses_measured_body_and_owns_result():
    obs,c,p=evidence();r=validate_actuation_proof(p,c,obs)
    assert r['body_translation_m']==pytest.approx(.01)
    p['actions'][0]['body_after_xy'][0]=99
    assert r['proof']['actions'][0]['body_after_xy']==[.01,0.]


@pytest.mark.parametrize('mutation',[
 lambda p:p.update(command_sha256='0'*64), lambda p:p.update(map_revision=2),
 lambda p:p['source'].update(calibration_id='other'),lambda p:p['source'].update(clock_domain='other'),
 lambda p:p['actions'][0].update(pre_step_monotonic_ns=1_300_000_000),
 lambda p:p['actions'][0].update(pose_version_after=99),
 lambda p:p['actions'][0].update(body_after_xy=[9.,0.]),
 lambda p:p['actions'][0].update(pre_step_monotonic_ns=True),
 lambda p:p.update(extra='x'),lambda p:p.update(complete=False),
])
def test_mismatched_or_incomplete_proof_rejected(mutation):
    obs,c,p=evidence();mutation(p)
    with pytest.raises(ValueError):validate_actuation_proof(p,c,obs)


def test_collection_no_double_count_and_missing_proof_not_zero_distance():
    obs,c,p=evidence();m=ActuationMeasurements(obs.key.episode_id,obs.clock_domain)
    assert m.try_record(c,obs,p,goal_id='frontier1',decision_map_revision=1,profile='baseline')
    assert not m.try_record(c,obs,p,goal_id='frontier1',decision_map_revision=1,profile='baseline')
    r=m.finalize();assert r['distance_m'] is None and r['observed_body_translation_lower_bound_m']==pytest.approx(.01)
    assert r['observed_frontier_translation_lower_bound_m']==pytest.approx(.01)
    assert not r['complete']


def test_sampled_no_progress_requires_dense_body_observations():
    obs,c,p=evidence();m=ActuationMeasurements(obs.key.episode_id,obs.clock_domain)
    for i in range(11):
        o=source(i,stamp=1_000_000_000+i*1_000_000_000,modality='depth_only')
        assert m.try_record_pose(o,dict(source=o.key,capture_monotonic_ns=o.capture_monotonic_ns,clock_domain=o.clock_domain,pose_version=o.pose_version,robot_xy=(0.,0.),yaw_rad=0.))
    r=m.finalize();assert r['sampled_no_progress']['interval_count']==1
    assert r['sampled_no_progress']['method']=='sampled_body_poses'
    m=ActuationMeasurements(obs.key.episode_id,obs.clock_domain)
    for i in (0,10):
        o=source(i,stamp=1_000_000_000+i*1_000_000_000,modality='depth_only')
        m.try_record_pose(o,dict(source=o.key,capture_monotonic_ns=o.capture_monotonic_ns,clock_domain=o.clock_domain,pose_version=o.pose_version,robot_xy=(0.,0.),yaw_rad=0.))
    assert m.finalize()['sampled_no_progress']['interval_count']==0


def test_wrong_clock_body_observation_cannot_create_no_progress_support():
    obs,c,p=evidence();m=ActuationMeasurements(obs.key.episode_id,obs.clock_domain)
    foreign=replace(obs,clock_domain='host_monotonic:foreign')
    pose=dict(source=foreign.key,capture_monotonic_ns=foreign.capture_monotonic_ns,clock_domain=obs.clock_domain,pose_version=foreign.pose_version,robot_xy=(0.,0.),yaw_rad=0.)
    assert not m.try_record_pose(foreign,pose)
    assert m.finalize()['sampled_no_progress']['pose_support']==0


@pytest.mark.parametrize('xy',[[-.01,0.],[0.,.01]])
def test_sideways_or_backwards_proof_is_not_forward_travel(xy):
    obs,c,p=evidence();p['actions'][0]['body_after_xy']=xy
    with pytest.raises(ValueError,match='forward'):validate_actuation_proof(p,c,obs)


def test_giant_builtin_integer_rejected_before_float_conversion():
    obs,c,p=evidence();p['actions'][0]['amount']=10**10000
    with pytest.raises(ValueError):validate_actuation_proof(p,c,obs)


@pytest.mark.parametrize('linear,yaw,turn_amount',[(.1,0.,0.),(0.,.2,.04),(.2,.2,.02)])
def test_nominal_duration_sum_cannot_exceed_100ms(linear,yaw,turn_amount):
    import math
    obs,c,p=evidence();c=replace(c,linear_mps=linear,yaw_radps=yaw,deadline_monotonic_ns=1_250_000_000)
    a=p['actions'][0]
    if not linear:
        a.update(action='turn_left',amount=math.degrees(turn_amount),body_after_xy=[0.,0.],yaw_after_rad=turn_amount)
    else:
        a.update(amount=.02,body_after_xy=[.02,0.])
        if yaw:
            p['actions'].append(dict(a,index=1,action='turn_left',amount=math.degrees(turn_amount),pre_step_monotonic_ns=1_001_000_001,post_step_monotonic_ns=1_002_000_000,pose_version_before=a['pose_version_after'],pose_version_after=a['pose_version_after']+1,body_before_xy=[.02,0.],body_after_xy=[.02,0.],yaw_before_rad=0.,yaw_after_rad=turn_amount))
    p['command_sha256']=command_sha256(c)
    with pytest.raises(ValueError):validate_actuation_proof(p,c,obs)


@pytest.mark.parametrize('change',[dict(linear_mps=.3),dict(linear_mps=-.1),dict(yaw_radps=1.)])
def test_proof_for_command_outside_native_motion_limits_is_rejected(change):
    obs,c,p=evidence();c=replace(c,**change);p['command_sha256']=command_sha256(c)
    with pytest.raises(ValueError):validate_actuation_proof(p,c,obs)


def test_offline_source_metadata_uses_same_proof_math_without_fabricated_observation():
    from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof,_source
    # Existing fixture produces a real typed capture/command and endpoint proof.
    obs,cmd,proof=evidence()
    assert validate_actuation_source_proof(proof,cmd,_source(obs),modality='depth_only')==validate_actuation_proof(proof,cmd,obs)


@pytest.mark.parametrize('field,value',[('schema_version','other'),('pose_version',True),('calibration_id','x'*129),('capture_monotonic_ns',10**10000)],ids=['schema','bool-pose','long-calibration','huge-time'])
def test_offline_metadata_helper_keeps_builtin_size_and_schema_guards(field,value):
    from neusymnav.runtime.actuation_measurements import validate_actuation_source_proof,_source
    obs,cmd,proof=evidence();metadata=_source(obs);metadata[field]=value
    with pytest.raises(ValueError):validate_actuation_source_proof(proof,cmd,metadata,modality='depth_only')


def test_shared_pose_summary_preserves_sampled_windows_and_gap_semantics():
    from neusymnav.runtime.actuation_measurements import summarize_body_poses
    dense=[(i*1_000_000_000,(0.,0.)) for i in range(11)]
    result=summarize_body_poses(dense)
    assert result['interval_count']==1 and result['pose_support']==11
    assert summarize_body_poses([dense[0],dense[-1]])['interval_count']==0
    with pytest.raises(ValueError):summarize_body_poses([dense[0],dense[0]])
    with pytest.raises(ValueError):summarize_body_poses([(True,(0.,0.))])
