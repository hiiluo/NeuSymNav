"""Guard geometry refusals reach existing policy memory without moving the body."""
from dataclasses import replace
from threading import RLock
from types import SimpleNamespace

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import FrameKey,MotionCommand,NavigationDecision,NavSnapshot
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.navigation.controller import Navigator
from neusymnav.runtime import Pipeline
from neusymnav.runtime.health import Health

DOMAIN='host_monotonic:guard-feedback-test'
STAMP=1_000_000_000


def context():
    obs=observation(key=FrameKey('episode','nav',1),capture_monotonic_ns=STAMP,clock_domain=DOMAIN,modality='depth_only')
    states=np.full((24,24),100,np.int8);states[2:22,2:22]=0
    states[8:16,1]=-1;states[8:16,22]=-1
    nav=NavSnapshot('episode',7,obs.key,STAMP,DOMAIN,.1,(0.,0.),states,
        states==0,np.where(states==0,1.,0.).astype(np.float32),'cylinder',0.,'fixture','a'*64)
    return obs,nav


class Guard:
    def __init__(self,reason='bootstrap_blocked',*,raises=False,moving=False):
        self.reason=reason;self.raises=raises;self.moving=moving
    def bind_nav(self,nav,**pose):self.nav=nav
    def filter(self,decision,latest,now):
        if self.raises:raise ValueError('guard fixture failure')
        return MotionCommand(latest.key,self.nav.revision,now,now+100_000_000,DOMAIN,
            .01 if self.moving else 0.,0.,self.reason,latest.capture_monotonic_ns)


class Actuator:
    def __init__(self):self.commands=[]
    def robot_pose(self,obs):
        return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain,
            pose_version=obs.pose_version,robot_xy=(1.2,1.2),yaw_rad=0.)
    def execute(self,command):
        self.commands.append(command)
        return dict(executed=bool(command.linear_mps or command.yaw_radps),reason=command.reason)


def pipeline(obs,nav,navigator,guard,*,now=STAMP):
    # Exercise the production control seam without starting unrelated graph/model workers.
    p=Pipeline.__new__(Pipeline)
    p._lock=RLock();p._control_lock=RLock();p._latest_depth=obs;p._latest_nav=nav
    p.navigator=navigator;p.guard=guard;p.now_ns=lambda:now;p.clock_domain=DOMAIN
    p._paused=False;p._closing=False;p.measurements=None;p.health=Health('baseline')
    return p


def real_navigator():
    return Navigator(RobotGeometry('cylinder',.05,1.,0.),clock_domain=DOMAIN)


def fixed_navigator(decision):
    navigator=real_navigator()
    navigator.step=lambda *args:decision
    return navigator


@pytest.mark.parametrize('reason',['bootstrap_blocked','footprint_not_observed','path_segment_blocked'])
def test_geometric_stop_marks_original_goal_failed_and_resets_controller(reason):
    obs,nav=context();decision=NavigationDecision('original',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking')
    navigator=fixed_navigator(decision);navigator.controller._linear=.1;navigator.controller._yaw_rate=.2
    p=pipeline(obs,nav,navigator,Guard(reason));actuator=Actuator()
    result=p.control_step(actuator)
    assert result==dict(executed=False,reason=reason)
    assert navigator.policy._failed_until_revision['original']>nav.revision
    assert navigator.policy._failed_viewpoints==[((1.65,1.2),nav.revision+100)]
    assert navigator.controller._linear==navigator.controller._yaw_rate==0.
    assert actuator.commands[0].linear_mps==actuator.commands[0].yaw_radps==0.


def test_runtime_feedback_stops_and_retains_committed_target():
    obs,nav=context();navigator=real_navigator();p=pipeline(obs,nav,navigator,Guard());actuator=Actuator()
    p.control_step(actuator);first=p._step_decision
    assert first.goal_id and first.path and first.desired_linear_mps+abs(first.desired_yaw_radps)>0
    assert navigator.policy._failed_viewpoints==[(first.path[-1],nav.revision+100)]
    # A second genuine source/map identity keeps the same observed geometry.
    obs=replace(obs,key=replace(obs.key,frame_index=2));nav=replace(nav,source=obs.key,revision=8)
    p._latest_depth=obs;p._latest_nav=nav
    p.control_step(actuator);second=p._step_decision
    assert second.goal_id is None and second.path==()
    assert second.reason=='committed_goal_waiting_after_collision'
    assert navigator.policy._goal.frontier_id==first.goal_id
    assert navigator.policy._goal_world_xy==first.path[-1]
    assert all(command.linear_mps==command.yaw_radps==0. for command in actuator.commands)


@pytest.mark.parametrize('reason',[
    'depth_stale','nav_stale','clock_domain_mismatch','depth_future','sensor_replay',
    'path_map_revision_stale','navigation_unavailable','runtime_stopped','tracking',
])
def test_non_geometric_stop_does_not_penalize_goal(reason):
    obs,nav=context();navigator=fixed_navigator(NavigationDecision('original',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking'))
    p=pipeline(obs,nav,navigator,Guard(reason));p.control_step(Actuator())
    assert not navigator.policy._failed_until_revision and not navigator.policy._failed_viewpoints


@pytest.mark.parametrize('change',[
    dict(goal_id=None),dict(path=(),desired_linear_mps=0.),dict(map_revision=6),
    dict(desired_linear_mps=0.,desired_yaw_radps=0.),
])
def test_guard_refusal_without_a_coherent_requested_goal_does_not_penalize(change):
    obs,nav=context();decision=NavigationDecision('original',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking')
    navigator=fixed_navigator(replace(decision,**change))
    pipeline(obs,nav,navigator,Guard()).control_step(Actuator())
    assert not navigator.policy._failed_until_revision


def test_paused_control_does_not_reuse_previous_goal_decision():
    obs,nav=context();navigator=fixed_navigator(NavigationDecision('previous',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking'))
    p=pipeline(obs,nav,navigator,Guard('tracking'));actuator=Actuator();p.control_step(actuator)
    p._paused=True;p.guard.reason='bootstrap_blocked'
    before=len(actuator.commands)
    assert p.control_step(actuator)==dict(executed=False,reason='runtime_paused')
    assert len(actuator.commands)==before
    assert p._step_decision is None and not navigator.policy._failed_until_revision


def test_geometry_reason_overwritten_by_expired_source_does_not_penalize():
    obs,nav=context();navigator=fixed_navigator(NavigationDecision('original',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking'))
    p=pipeline(obs,nav,navigator,Guard(),now=STAMP+300_000_001)
    result=p.control_step(Actuator())
    assert result['reason']=='depth_stale' and not navigator.policy._failed_until_revision


@pytest.mark.parametrize('field',['source','source_capture_monotonic_ns','map_revision','clock_domain'])
def test_incoherent_geometric_guard_command_does_not_mutate_goal_memory(field):
    obs,nav=context();navigator=fixed_navigator(NavigationDecision('original',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking'))
    class IncoherentGuard(Guard):
        def filter(self,decision,latest,now):
            command=super().filter(decision,latest,now)
            values=dict(source=replace(obs.key,frame_index=9),source_capture_monotonic_ns=STAMP+1,
                map_revision=6,clock_domain='host_monotonic:other')
            return replace(command,**{field:values[field]})
    pipeline(obs,nav,navigator,IncoherentGuard()).control_step(Actuator())
    assert not navigator.policy._failed_until_revision and not navigator.policy._failed_viewpoints


@pytest.mark.parametrize('guard',[Guard(raises=True),Guard(moving=True)])
def test_error_or_nonzero_command_does_not_penalize(guard):
    obs,nav=context();navigator=fixed_navigator(NavigationDecision('original',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking'))
    pipeline(obs,nav,navigator,guard).control_step(Actuator())
    assert not navigator.policy._failed_until_revision


def test_legacy_navigator_without_feedback_capability_keeps_safe_zero_command():
    obs,nav=context();decision=NavigationDecision('original',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking')
    p=pipeline(obs,nav,SimpleNamespace(step=lambda *args:decision),Guard());actuator=Actuator()
    assert p.control_step(actuator)['reason']=='bootstrap_blocked'
    assert actuator.commands[-1].linear_mps==actuator.commands[-1].yaw_radps==0.


def test_existing_failure_api_resets_velocity_and_preserves_bounded_cooldown():
    navigator=real_navigator();navigator.controller._linear=.15;navigator.controller._yaw_rate=.25
    navigator.report_goal_failure('original',7,goal_world_xy=(1.65,1.2))
    assert navigator.controller._linear==navigator.controller._yaw_rate==0.
    assert navigator.policy._failed_until_revision=={'original':107}
    assert navigator.policy._failed_viewpoints==[((1.65,1.2),107)]


def test_paused_control_with_new_sensor_capture_never_requests_stale_pose():
    obs,nav=context()
    navigator=fixed_navigator(NavigationDecision('goal',((1.2,1.2),(1.65,1.2)),.1,.2,nav.revision,'tracking'))
    p=pipeline(obs,nav,navigator,Guard())
    p._paused=True
    class NewerCapture:
        def robot_pose(self,source):
            raise AssertionError('paused runtime must not request a superseded pose')
        def execute(self,command):
            raise AssertionError('paused runtime must not issue another pulse')
    assert p.control_step(NewerCapture())==dict(executed=False,reason='runtime_paused')
    assert p._step_command is None and p._step_decision is None


def test_runtime_goal_is_fixed_until_arrival_then_next_goal():
    _,nav=context();navigator=real_navigator()
    first=navigator.step(nav,(1.2,1.2),0.,STAMP)
    assert first.goal_id and first.path
    # Re-observation changes map revision but not the committed target.
    second=navigator.step(replace(nav,revision=8),(1.2,1.2),0.,STAMP)
    assert second.goal_id==first.goal_id and second.path[-1]==first.path[-1]
    reached=navigator.step(replace(nav,revision=9),first.path[-1],0.,STAMP)
    assert reached.reason=='frontier_viewpoint_reached'
    assert reached.desired_linear_mps==reached.desired_yaw_radps==0.
    following=navigator.step(replace(nav,revision=10),first.path[-1],0.,STAMP)
    assert following.goal_id and following.path[-1]!=first.path[-1]


def test_runtime_stale_source_stops_without_forgetting_goal_and_episode_resets():
    _,nav=context();navigator=real_navigator()
    first=navigator.step(nav,(1.2,1.2),0.,STAMP)
    target=first.path[-1]
    stale=navigator.step(nav,(1.2,1.2),0.,STAMP+300_000_001)
    assert stale.reason=='nav_stale' and stale.path==()
    assert navigator.policy._goal_world_xy==target
    # An episode reset intentionally discards the previous episode's commitment.
    states=np.full(nav.states.shape,100,np.int8)
    newnav=replace(nav,episode_id='next',source=replace(nav.source,episode_id='next'),
                   states=states,floor_support=states==0)
    navigator.step(newnav,(1.2,1.2),0.,STAMP)
    assert navigator.policy._goal_world_xy is None


def test_runtime_goal_arrival_threshold_is_five_cm():
    _,nav=context();navigator=real_navigator()
    first=navigator.step(nav,(1.2,1.2),0.,STAMP);target=first.path[-1]
    assert navigator.policy.config.reached_distance_m==.05
    outside=navigator.step(replace(nav,revision=8),(target[0]+.051,target[1]),0.,STAMP)
    assert outside.reason!='frontier_viewpoint_reached'
    inside=navigator.step(replace(nav,revision=9),(target[0]+.049,target[1]),0.,STAMP)
    assert inside.reason=='frontier_viewpoint_reached'


def test_blocked_commitment_remains_visible_without_an_executable_route():
    class FollowingGuard(Guard):
        def filter(self,decision,latest,now):
            command=super().filter(decision,latest,now)
            return (replace(command,reason=decision.reason)
                    if not decision.desired_linear_mps and not decision.desired_yaw_radps else command)
    obs,nav=context();navigator=real_navigator();p=pipeline(obs,nav,navigator,FollowingGuard())
    p.control_step(Actuator());first=p._step_decision
    shown=p.navigation_display()
    assert shown.goal_id==first.goal_id and shown.goal_xy==first.path[-1]
    assert shown.path==() and 'bootstrap_blocked' in shown.status
    obs=replace(obs,key=replace(obs.key,frame_index=2));nav=replace(nav,source=obs.key,revision=8)
    p._latest_depth=obs;p._latest_nav=nav;p.control_step(Actuator())
    shown=p.navigation_display()
    assert shown.goal_id==first.goal_id and shown.goal_xy==first.path[-1]
    assert shown.path==() and 'committed_goal_waiting_after_collision' in shown.status
    status=p.navigation_status()
    assert status['goal_xy']==first.path[-1] and status['goal_id']==first.goal_id
    assert status['reason']=='committed_goal_waiting_after_collision'
    assert status['reason_counts']['bootstrap_blocked']==1
    p._paused=True
    assert p.navigation_display().goal_xy is None


def test_persistent_geometric_stop_abandons_only_after_time_and_fresh_map_evidence():
    _,nav=context();navigator=real_navigator()
    first=navigator.step(nav,(1.2,1.2),0.,STAMP);target=first.path[-1]
    for i in range(20):
        now=STAMP+i*400_000_000
        current=replace(nav,revision=8+i,capture_monotonic_ns=now)
        assert navigator.observe_navigation_result(current,(1.2,1.2),now,
            'path_segment_blocked',True) is None
        assert navigator.policy._goal_world_xy==target
    now=STAMP+8_000_000_000
    failure=navigator.observe_navigation_result(replace(nav,revision=28,capture_monotonic_ns=now),
        (1.2,1.2),now,'path_segment_blocked',True)
    assert failure['goal_id']==first.goal_id and failure['goal_xy']==target
    assert navigator.policy._goal_world_xy is None
    assert navigator.policy._failed_viewpoints
    replacement=navigator.step(replace(nav,revision=29,capture_monotonic_ns=now),(1.2,1.2),0.,now)
    assert replacement.goal_id and replacement.path[-1]!=target


@pytest.mark.parametrize('reason',['nav_stale','depth_stale','runtime_paused','clock_domain_mismatch','tracking'])
def test_non_geometric_stops_never_abandon_goal(reason):
    _,nav=context();navigator=real_navigator();first=navigator.step(nav,(1.2,1.2),0.,STAMP)
    for i in range(30):
        now=STAMP+i*1_000_000_000
        assert navigator.observe_navigation_result(replace(nav,revision=8+i,capture_monotonic_ns=now),
            (1.2,1.2),now,reason,True) is None
    assert navigator.policy._goal_world_xy==first.path[-1]


def test_repeated_revision_and_measured_progress_do_not_trigger_early_abandonment():
    _,nav=context();navigator=real_navigator();first=navigator.step(nav,(1.2,1.2),0.,STAMP)
    target=first.path[-1]
    for i in range(25):
        now=STAMP+i*500_000_000
        assert navigator.observe_navigation_result(replace(nav,capture_monotonic_ns=now),
            (1.2,1.2),now,'path_segment_blocked',True) is None
    assert navigator.policy._goal_world_xy==target
    navigator._goal_failure_watch=None
    import math
    start=(1.2,1.2);distance=math.dist(start,target)
    closer=tuple(a+.04*(b-a)/distance for a,b in zip(start,target))
    for i in range(25):
        now=STAMP+i*400_000_000
        xy=start if i<19 else closer
        assert navigator.observe_navigation_result(replace(nav,revision=8+i,capture_monotonic_ns=now),
            xy,now,'path_segment_blocked',True) is None
    assert navigator.policy._goal_world_xy==target


def test_control_wires_confirmed_failure_then_selects_different_target():
    obs,nav=context();navigator=real_navigator();p=pipeline(obs,nav,navigator,Guard());actuator=Actuator()
    first=None
    for i in range(21):
        now=STAMP+i*400_000_000
        current=replace(obs,key=replace(obs.key,frame_index=i+1),capture_monotonic_ns=now)
        p._latest_depth=current;p._latest_nav=replace(nav,source=current.key,revision=7+i,capture_monotonic_ns=now)
        p.now_ns=lambda:now
        p.control_step(actuator)
        if i==0:first=p._step_decision
        if i<20:assert navigator.policy._goal_world_xy==first.path[-1]
    assert navigator.policy._goal_world_xy is None
    status=p.navigation_status()
    assert status['last_goal_failure']['goal_id']==first.goal_id
    assert status['reason'].startswith('goal_failed_no_progress:')
    now+=400_000_000
    current=replace(current,key=replace(current.key,frame_index=22),capture_monotonic_ns=now)
    p._latest_depth=current;p._latest_nav=replace(p._latest_nav,source=current.key,revision=28,capture_monotonic_ns=now)
    p.control_step(actuator)
    assert p._step_decision.goal_id and p._step_decision.path[-1]!=first.path[-1]
    assert all(command.linear_mps==command.yaw_radps==0. for command in actuator.commands)


def test_failed_tick_does_not_report_abandoned_path_endpoint_as_current_goal():
    obs,nav=context();navigator=real_navigator();p=pipeline(obs,nav,navigator,Guard())
    p.control_step(Actuator())
    source,frontiers,decision,reason,computed,rejected,held=p._navigation_display
    assert decision.goal_id and decision.path and rejected and held
    p._navigation_display=(source,frontiers,decision,'goal_failed_no_progress:'+reason,computed,rejected,None)
    assert p.navigation_status()['goal_id'] is None
    assert p.navigation_display().goal_id is None


@pytest.mark.parametrize('interruption',['pause','source_pending','exception'])
def test_control_interruption_resets_failure_confirmation_without_dropping_goal(interruption):
    obs,nav=context();navigator=real_navigator();p=pipeline(obs,nav,navigator,Guard());actuator=Actuator()
    p.control_step(actuator);target=navigator.policy._goal_world_xy
    assert navigator._goal_failure_watch is not None
    if interruption=='pause':p._paused=True
    elif interruption=='source_pending':p._latest_nav=replace(nav,source=replace(nav.source,frame_index=9))
    else:
        p.guard=Guard(raises=True)
    p.control_step(actuator)
    assert navigator._goal_failure_watch is None
    assert navigator.policy._goal_world_xy==target


def test_long_gap_without_control_observations_starts_new_failure_window():
    _,nav=context();navigator=real_navigator();first=navigator.step(nav,(1.2,1.2),0.,STAMP)
    for i in range(19):
        now=STAMP+i*400_000_000
        navigator.observe_navigation_result(replace(nav,revision=8+i,capture_monotonic_ns=now),
            (1.2,1.2),now,'path_segment_blocked',True)
    now+=30_000_000_000
    assert navigator.observe_navigation_result(replace(nav,revision=28,capture_monotonic_ns=now),
        (1.2,1.2),now,'path_segment_blocked',True) is None
    assert navigator.policy._goal_world_xy==first.path[-1]
    assert navigator._goal_failure_watch['count']==1
