import pytest

from contract_helpers import observation


def test_offline_replay_actuator_joins_pose_by_exact_frame_and_never_acts():
    from neusymnav.runtime.replay_control import OfflineReplayActuator, ReplayPose
    from neusymnav.contracts import MotionCommand

    source = observation(key=__import__('neusymnav.contracts', fromlist=['FrameKey']).FrameKey('episode','nav',3),
        capture_monotonic_ns=500,clock_domain='replay:session',pose_version=2,modality='depth_only')
    pose = ReplayPose(source.key,500,'replay:session',2,(1.25,2.5),.4)
    command = MotionCommand(source.key,1,500,700,'replay:session',.1,0.,'test',500)
    actuator = OfflineReplayActuator({('episode','nav',3):pose},clock_domain='replay:session',now_ns=lambda:550)

    assert actuator.robot_pose(source)['robot_xy'] == pose.robot_xy
    assert actuator.execute(command) == {'executed':True,'reason':'offline_replay_ack'}
    assert actuator.calls == 1

    wrong = observation(key=source.key,capture_monotonic_ns=501,clock_domain='replay:session',
        pose_version=2,modality='depth_only')
    with pytest.raises(ValueError,match='metadata mismatch'):
        actuator.robot_pose(wrong)


def test_offline_replay_actuator_requires_replay_clock_and_replays_zero_reason():
    from neusymnav.runtime.replay_control import OfflineReplayActuator, ReplayPose
    from neusymnav.contracts import FrameKey, MotionCommand

    key=FrameKey('episode','nav',4)
    pose=ReplayPose(key,600,'replay:session',0,(0.,0.),0.)
    with pytest.raises(ValueError,match='isolated replay clock'):
        OfflineReplayActuator({}, clock_domain='host_monotonic:live',now_ns=lambda:600)
    actuator=OfflineReplayActuator({('episode','nav',4):pose},clock_domain='replay:session',now_ns=lambda:600)
    command=MotionCommand(key,0,600,700,'replay:session',0.,0.,'blocked',600)
    assert actuator.execute(command)=={'executed':False,'reason':'expired_or_zero'}


def test_coordinator_rejects_replay_pose_unless_offline_control_mode_is_explicit():
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.contracts import FrameKey

    obs=observation(key=FrameKey('episode','nav',5),capture_monotonic_ns=700,
        clock_domain='replay:session',pose_version=0,modality='depth_only')
    pose=dict(source=obs.key,capture_monotonic_ns=700,clock_domain='replay:session',
        pose_version=0,robot_xy=(0.,0.),yaw_rad=0.)
    pipeline=object.__new__(Pipeline)
    pipeline.episode_id='episode';pipeline.clock_domain='replay:session';pipeline.now_ns=lambda:700
    pipeline.offline_replay_control=False
    with pytest.raises(ValueError,match='current live episode clock'):
        pipeline._validated_robot_pose(obs,pose)
    pipeline.offline_replay_control=True
    assert pipeline._validated_robot_pose(obs,pose)[0]==(obs.key,700,'replay:session',0)


def test_offline_pipeline_refuses_any_non_replay_actuator():
    from neusymnav.runtime.coordinator import Pipeline
    from neusymnav.runtime.replay_control import OfflineReplayActuator

    pipeline=object.__new__(Pipeline)
    pipeline.offline_replay_control=True
    with pytest.raises(TypeError,match='OfflineReplayActuator'):
        pipeline.control_step(object())
    class DerivedFake(OfflineReplayActuator):
        def execute(self,command):return {'executed':True,'reason':'external-actuation'}
    fake=object.__new__(DerivedFake)
    with pytest.raises(TypeError,match='OfflineReplayActuator'):
        pipeline.control_step(fake)


def test_navigator_and_guard_keep_live_clock_default_and_allow_explicit_replay_only():
    from neusymnav.mapping.occupancy import RobotGeometry
    from neusymnav.navigation.controller import Navigator
    from neusymnav.navigation.safety import MotionGuard

    robot=RobotGeometry('cylinder-v1',.2,1.5,.05)
    with pytest.raises(ValueError,match='pinned live host clock'):
        Navigator(robot,clock_domain='replay:session')
    with pytest.raises(ValueError,match='pinned live host domain'):
        MotionGuard(object(),clock_domain='replay:session')
    with pytest.raises(ValueError,match='isolated replay clock'):
        Navigator(robot,clock_domain='host_monotonic:test',offline_replay=True)
    Navigator(robot,clock_domain='replay:session',offline_replay=True)
    MotionGuard(object(),clock_domain='replay:session',offline_replay=True)
