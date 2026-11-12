"""Shorter measured lookahead still covers commanded sweep and robot footprint."""
from dataclasses import replace
import pytest
from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.safety import MotionGuard
from test_navigation import ready_guard
from test_navmap import down


@pytest.mark.parametrize('horizon,expected',[(100_000_000,.02),(1_000_000_000,.06)])
def test_measured_bootstrap_corridor_matches_command_distance(tmp_path,horizon,expected):
    previous,nav=ready_guard(tmp_path);mapper=previous.mapper;calls=[]
    bootstrap=mapper.bootstrap
    def record(obs,**kwargs):
        calls.append(kwargs)
        return bootstrap(obs,**kwargs)
    mapper.bootstrap=record
    guard=MotionGuard(mapper,clock_domain=nav.clock_domain,command_horizon_ns=horizon)
    guard.bind_nav(nav,robot_xy=(0.,0.),yaw_rad=0.)
    decision=NavigationDecision('goal',((0.,0.),(.1,0.)),.2,0.,nav.revision,'tracking')
    command=guard.filter(decision,down(2),1_000_000_000)
    assert command.linear_mps==.2
    assert calls[0]['corridor_m']==pytest.approx(expected)
    assert mapper.robot==previous.mapper.robot
    assert mapper.robot.radius_m==.10 and mapper.robot.margin_m==0.


def test_obstacle_beyond_actual_swept_footprint_does_not_block_short_pulse(tmp_path):
    guard,nav=ready_guard(tmp_path)
    observation=down(2)
    depth=observation.depth_m.copy()
    # This measured hit is outside the 2 cm pulse plus robot radius, but inside
    # the old, unrelated 10 cm minimum lookahead plus that same footprint.
    depth[40,45]=1.6
    observation=replace(observation,depth_m=depth)
    decision=NavigationDecision('goal',((0.,0.),(.05,0.)),.2,0.,nav.revision,'tracking')

    command=guard.filter(decision,observation,1_000_000_000)

    assert command.linear_mps==pytest.approx(.2)
    assert command.reason=='tracking'


def test_obstacle_inside_actual_swept_footprint_still_blocks_short_pulse(tmp_path):
    guard,nav=ready_guard(tmp_path)
    observation=down(2)
    depth=observation.depth_m.copy()
    depth[40,41]=1.6
    observation=replace(observation,depth_m=depth)
    decision=NavigationDecision('goal',((0.,0.),(.05,0.)),.2,0.,nav.revision,'tracking')

    command=guard.filter(decision,observation,1_000_000_000)

    assert command.linear_mps==command.yaw_radps==0.
    assert command.reason=='bootstrap_blocked'


def test_unknown_current_depth_still_blocks_with_shorter_corridor(tmp_path):
    guard,nav=ready_guard(tmp_path)
    decision=NavigationDecision('goal',((0.,0.),(.1,0.)),.1,0.,nav.revision,'tracking')
    command=guard.filter(decision,down(2,valid=False),1_000_000_000)
    assert command.reason=='bootstrap_blocked'
    assert command.linear_mps==command.yaw_radps==0.
