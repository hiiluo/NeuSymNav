"""Shorter measured lookahead still covers commanded sweep and robot footprint."""
from dataclasses import replace
import pytest
from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.safety import MotionGuard
from test_navigation import ready_guard
from test_navmap import down


@pytest.mark.parametrize('horizon,expected',[(100_000_000,.10),(1_000_000_000,.20)])
def test_default_measured_corridor_is_ten_cm_or_actual_command_distance(tmp_path,horizon,expected):
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


def test_unknown_current_depth_still_blocks_with_shorter_corridor(tmp_path):
    guard,nav=ready_guard(tmp_path)
    decision=NavigationDecision('goal',((0.,0.),(.1,0.)),.1,0.,nav.revision,'tracking')
    command=guard.filter(decision,down(2,valid=False),1_000_000_000)
    assert command.reason=='bootstrap_blocked'
    assert command.linear_mps==command.yaw_radps==0.
