"""Fresh historical map and new measured depth keep independent provenance."""
from dataclasses import replace
import pytest
from test_guard_goal_feedback import context, pipeline, fixed_navigator, Guard, Actuator, STAMP, DOMAIN
from neusymnav.contracts import NavigationDecision


def runtime(*, allow=True, map_age=100_000_000, case=None):
    obs, nav = context()
    obs = replace(obs, key=replace(obs.key, frame_index=2), capture_monotonic_ns=STAMP+map_age)
    if case == 'wrong_sensor':nav=replace(nav,source=replace(nav.source,sensor_id='other'))
    elif case == 'future_source':nav=replace(nav,source=replace(nav.source,frame_index=3))
    elif case == 'wrong_clock':nav=replace(nav,clock_domain='host_monotonic:other')
    elif case == 'same_key_wrong_stamp':nav=replace(nav,source=obs.key)
    elif case == 'wrong_episode':nav=replace(nav,episode_id='other',source=replace(nav.source,episode_id='other'))
    elif case == 'future_capture':nav=replace(nav,capture_monotonic_ns=obs.capture_monotonic_ns+1)
    decision=NavigationDecision('goal',((1.2,1.2),(1.65,1.2)),.1,0.,nav.revision,'tracking')
    p=pipeline(obs,nav,fixed_navigator(decision),Guard(moving=True),now=obs.capture_monotonic_ns)
    p.allow_fresh_map_lag=allow
    return p,obs,nav


def test_fresh_lag_uses_new_depth_pose_and_original_map_revision():
    p,obs,nav=runtime()
    actuator=Actuator()
    result=p.control_step(actuator)
    assert result['executed'] is True
    command=actuator.commands[-1]
    assert command.source == obs.key != nav.source
    assert command.source_capture_monotonic_ns == obs.capture_monotonic_ns
    assert command.map_revision == nav.revision
    assert p._latest_nav is nav and nav.capture_monotonic_ns == STAMP


@pytest.mark.parametrize('case',['wrong_sensor','future_source','wrong_clock','same_key_wrong_stamp','wrong_episode','future_capture'])
def test_lag_never_accepts_unrelated_or_relabelled_map(case):
    p,_,_=runtime(case=case)
    actuator=Actuator()
    assert not p.control_step(actuator)['executed']
    assert actuator.commands == []


def test_lag_with_real_guard_requires_current_measured_footprint(tmp_path):
    import numpy as np
    from test_navmap import mapper, down
    from neusymnav.navigation.safety import MotionGuard
    def capture(index, valid=True):
        obs=down(index,valid=valid,stamp=STAMP+index*50_000_000,domain=DOMAIN)
        return replace(obs,key=replace(obs.key,episode_id='episode'))
    m=mapper(tmp_path)
    m.update(capture(0));nav=m.update(capture(1));latest=capture(2)
    decision=NavigationDecision('goal',((0.,0.),(.3,0.)),.1,0.,nav.revision,'tracking')
    p=pipeline(latest,nav,fixed_navigator(decision),MotionGuard(m,clock_domain=DOMAIN),
               now=latest.capture_monotonic_ns)
    p.allow_fresh_map_lag=True
    class Body(Actuator):
        def robot_pose(self,obs):
            return dict(super().robot_pose(obs),robot_xy=(0.,0.),yaw_rad=0.)
    body=Body()
    assert p.control_step(body)['executed'] is True
    assert body.commands[-1].source == latest.key != nav.source
    invalid=capture(3,False)
    p._latest_depth=invalid;p.now_ns=lambda:invalid.capture_monotonic_ns
    result=p.control_step(body)
    assert result['executed'] is False and result['reason']=='bootstrap_blocked'
    assert p._latest_nav is nav and m._revision == nav.revision


def _real_capture(index, *, x=0., stamp=None, depth_m=2.):
    import numpy as np
    from test_navmap import down
    stamp=STAMP+index*50_000_000 if stamp is None else stamp
    obs=down(index,x=x,stamp=stamp,domain=DOMAIN)
    obs=replace(obs,key=replace(obs.key,episode_id='episode'),pose_version=index+1)
    if depth_m!=2.:obs=replace(obs,depth_m=np.full(obs.depth_m.shape,depth_m,np.float32))
    return obs


def _real_lag_run(tmp_path, *, latest_x=.15, latest_depth_m=2., now_ns=None):
    from test_navmap import mapper
    from neusymnav.navigation.safety import MotionGuard
    m=mapper(tmp_path)
    m.update(_real_capture(0))
    nav=m.update(_real_capture(1))
    latest=_real_capture(2,x=latest_x,depth_m=latest_depth_m)
    x=float(latest.T_world_camera[0,3])
    decision=NavigationDecision('goal',((x,0.),(x+.3,0.)),.1,0.,nav.revision,'tracking')
    issue_ns=latest.capture_monotonic_ns if now_ns is None else now_ns
    guard=MotionGuard(m,clock_domain=DOMAIN,now_ns=lambda:issue_ns)
    p=pipeline(latest,nav,fixed_navigator(decision),guard,now=issue_ns)
    p.allow_fresh_map_lag=True

    class CurrentPoseActuator(Actuator):
        def robot_pose(self,obs):
            pose=super().robot_pose(obs)
            pose.update(robot_xy=(float(obs.T_world_camera[0,3]),float(obs.T_world_camera[1,3])),yaw_rad=0.)
            return pose

    return m,p,latest,nav,CurrentPoseActuator()


def test_real_lag_guard_new_obstacle_in_footprint_blocks_against_free_prior_map(tmp_path):
    import numpy as np
    from neusymnav.contracts import GridState
    from test_navmap import mapper
    from neusymnav.navigation.safety import MotionGuard
    m=mapper(tmp_path)
    m.update(_real_capture(0));nav=m.update(_real_capture(1))
    latest=_real_capture(2,depth_m=1.5)
    row,col=m.world_to_snapshot(nav,(0.,0.))
    assert nav.states[row,col]==GridState.FREE
    local=m.measured_coverage(latest,required_bounds_xy=((-0.2,-0.2),(0.3,0.3)))
    local_row,local_col=m.world_to_snapshot(local,(0.,0.))
    assert local.states[local_row,local_col]!=GridState.FREE
    blocked=m.bootstrap(latest,robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.01)
    assert blocked.reason=='bootstrap_blocked'

    decision=NavigationDecision('goal',((0.,0.),(.3,0.)),.1,0.,nav.revision,'tracking')
    guard=MotionGuard(m,clock_domain=DOMAIN,now_ns=lambda:latest.capture_monotonic_ns)
    p=pipeline(latest,nav,fixed_navigator(decision),guard,now=latest.capture_monotonic_ns)
    p.allow_fresh_map_lag=True
    body=Actuator()
    prior_states=nav.states.copy();prior_floor=nav.floor_support.copy();prior_clearance=nav.clearance.copy()
    result=p.control_step(body)
    assert result==dict(executed=False,reason='bootstrap_blocked')
    assert len(body.commands)==1
    assert body.commands[0].linear_mps==body.commands[0].yaw_radps==0.
    assert body.commands[0].source==nav.source and body.commands[0].map_revision==nav.revision
    assert p._latest_nav is nav and m._revision==nav.revision
    assert np.array_equal(nav.states,prior_states)
    assert np.array_equal(nav.floor_support,prior_floor)
    assert np.array_equal(nav.clearance,prior_clearance)


@pytest.mark.parametrize('issue_from_nav_ns,expected_from_nav_ns',[
    (150_000_000,250_000_000),  # 100 ms horizon expires first
    (250_000_000,300_000_000),  # prior map TTL expires first
])
def test_real_lag_guard_preserves_current_pose_source_and_all_original_deadlines(
        tmp_path,issue_from_nav_ns,expected_from_nav_ns):
    m,p,latest,nav,body=_real_lag_run(tmp_path,latest_x=.15,
        now_ns=STAMP+50_000_000+issue_from_nav_ns)
    result=p.control_step(body)
    command=body.commands[-1]
    assert result['executed'] is True
    assert command.source==latest.key!=nav.source
    assert command.source_capture_monotonic_ns==latest.capture_monotonic_ns
    assert command.map_revision==nav.revision
    assert body.commands[-1].linear_mps==.1
    expected=min(nav.capture_monotonic_ns+300_000_000,
        latest.capture_monotonic_ns+300_000_000,command.issued_monotonic_ns+100_000_000)
    assert command.deadline_monotonic_ns==expected
    assert command.deadline_monotonic_ns==nav.capture_monotonic_ns+expected_from_nav_ns
    assert nav.capture_monotonic_ns==STAMP+50_000_000
    assert p._latest_nav is nav and m._revision==nav.revision


def test_real_lag_guard_stops_when_prior_map_ttl_expires_but_depth_is_fresh(tmp_path):
    from test_navmap import mapper
    from neusymnav.navigation.safety import MotionGuard
    m=mapper(tmp_path)
    m.update(_real_capture(0));nav=m.update(_real_capture(1))
    latest=_real_capture(2,stamp=nav.capture_monotonic_ns+250_000_000)
    now=nav.capture_monotonic_ns+300_000_001
    assert now-latest.capture_monotonic_ns==50_000_001
    decision=NavigationDecision('goal',((0.,0.),(.3,0.)),.1,0.,nav.revision,'tracking')
    p=pipeline(latest,nav,fixed_navigator(decision),
        MotionGuard(m,clock_domain=DOMAIN,now_ns=lambda:now),now=now)
    p.allow_fresh_map_lag=True
    body=Actuator()
    result=p.control_step(body)
    assert result==dict(executed=False,reason='navigation_source_pending')
    assert body.commands==[]
    assert p._latest_nav is nav and nav.capture_monotonic_ns<now


def test_concurrent_future_map_update_cannot_change_pinned_lag_guard_or_current_coverage(tmp_path):
    from threading import Event,Thread
    import numpy as np
    from neusymnav.contracts import GridState
    from test_navmap import mapper
    from neusymnav.navigation.safety import MotionGuard
    m=mapper(tmp_path)
    m.update(_real_capture(0));nav=m.update(_real_capture(1))
    latest=_real_capture(2,x=.15)
    future=_real_capture(3,x=.15,depth_m=1.5)
    x=float(latest.T_world_camera[0,3])
    decision=NavigationDecision('goal',((x,0.),(x+.3,0.)),.1,0.,nav.revision,'tracking')
    guard=MotionGuard(m,clock_domain=DOMAIN,now_ns=lambda:latest.capture_monotonic_ns)
    p=pipeline(latest,nav,fixed_navigator(decision),guard,now=latest.capture_monotonic_ns)
    p.allow_fresh_map_lag=True

    class CurrentPoseActuator(Actuator):
        def robot_pose(self,obs):
            pose=super().robot_pose(obs)
            pose.update(robot_xy=(float(obs.T_world_camera[0,3]),float(obs.T_world_camera[1,3])),yaw_rad=0.)
            return pose

    ready=Event();release=Event();coverage={}
    original=m._coverage_from_votes
    def gated_coverage(obs,votes):
        result=original(obs,votes)
        coverage[obs.key]=result
        if obs.key==latest.key:
            ready.set()
            if not release.wait(3.):raise TimeoutError('test did not release current coverage')
        return result
    m._coverage_from_votes=gated_coverage
    prior_states=nav.states.copy();outcomes=[];errors=[]
    def control():
        try:outcomes.append(p.control_step(CurrentPoseActuator()))
        except BaseException as exc:errors.append(exc)
    thread=Thread(target=control)
    thread.start()
    try:
        assert ready.wait(3.)
        future_nav=m.update(future)
        assert future_nav.source==future.key and future_nav.revision>nav.revision
        assert coverage[latest.key].source==latest.key
        assert coverage[future.key].source==future.key
    finally:
        release.set();thread.join(3.)
    assert not thread.is_alive() and not errors
    assert outcomes==[dict(executed=True,reason='tracking')]
    current_row,current_col=m.world_to_snapshot(coverage[latest.key],(x,0.))
    future_row,future_col=m.world_to_snapshot(coverage[future.key],(x,0.))
    assert coverage[latest.key].states[current_row,current_col]==GridState.FREE
    assert coverage[future.key].states[future_row,future_col]!=GridState.FREE
    assert p._latest_nav is nav and guard._bound[0] is nav
    assert np.array_equal(nav.states,prior_states)


@pytest.mark.parametrize('allow,age',[(False,100_000_000),(True,300_000_001)])
def test_old_mode_or_expired_map_keeps_actuator_stopped(allow,age):
    p,_,_=runtime(allow=allow,map_age=age)
    actuator=Actuator()
    assert not p.control_step(actuator)['executed']
    assert actuator.commands == []
