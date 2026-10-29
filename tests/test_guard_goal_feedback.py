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


def test_runtime_feedback_enables_existing_frontier_policy_to_choose_an_alternative():
    obs,nav=context();navigator=real_navigator();p=pipeline(obs,nav,navigator,Guard());actuator=Actuator()
    p.control_step(actuator);first=p._step_decision
    assert first.goal_id and first.path and first.desired_linear_mps+abs(first.desired_yaw_radps)>0
    assert navigator.policy._failed_viewpoints==[(first.path[-1],nav.revision+100)]
    # A second genuine source/map identity keeps the same observed geometry.
    obs=replace(obs,key=replace(obs.key,frame_index=2));nav=replace(nav,source=obs.key,revision=8)
    p._latest_depth=obs;p._latest_nav=nav
    p.control_step(actuator);second=p._step_decision
    assert second.goal_id and second.goal_id!=first.goal_id
    assert second.path[-1]!=first.path[-1]
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
    p.control_step(actuator)
    assert actuator.commands[-1].reason=='runtime_stopped'
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
