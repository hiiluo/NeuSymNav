"""P03 planning/controller parity and safety gates over CPU fixtures."""
from dataclasses import replace
import math
import numpy as np
import pytest
from neusymnav.contracts import NavSnapshot, FrameKey, GridState, NavigationDecision
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.navigation.planner import Planner
from neusymnav.navigation.controller import Navigator
from neusymnav.navigation.safety import MotionGuard
from test_navmap import down, mapper, geometry


def nav(states=None, *, revision=1, origin=(0.,0.),episode='ep'):
    values=np.zeros((15,15),np.int8) if states is None else states
    return NavSnapshot(episode,revision,FrameKey(episode,'nav',0),1_000_000_000,'host_monotonic:test',.1,origin,
        values,np.ones(values.shape,bool),np.full(values.shape,1.,np.float32),'cylinder-v1',3.,'scene:v1','a'*64)


def test_many_matches_astar_exact_cost_and_unreachable():
    s=np.zeros((15,15),np.int8);s[7,2:13]=100;s[7,7]=0
    n=nav(s);p=Planner(geometry())
    goals=((2,12),(12,12),(7,7),(99,99),(7,3))
    batch=p.plan_many(n,(.35,.35),goals)
    for goal in goals:
        single=p.plan(n,(.35,.35),goal)
        assert batch[goal].success==single.success
        assert batch[goal].cost_m==pytest.approx(single.cost_m)
    assert not batch[(7,7)].success # door width .1 < diameter .2
    assert not batch[(12,12)].success


def test_footprint_unknown_boundary_and_missing_height_are_blocked():
    p=Planner(geometry());n=nav()
    assert not p.plan(n,(.05,.05),(3,3)).success
    assert not p.plan(replace(n,clearance=np.zeros_like(n.clearance)),(.35,.35),(5,5)).success
    assert not p.plan(replace(n,floor_support=np.zeros_like(n.floor_support)),(.35,.35),(5,5)).success
    s=n.states.copy();s[3,4]=-1
    assert not p.plan(replace(n,states=s),(.35,.35),(3,3)).success


def test_no_diagonal_corner_cut_and_grid_identity_invalidation():
    p=Planner(RobotGeometry('cylinder-v1',.001,1.,0.));s=np.full((5,5),100,np.int8)
    s[1,1]=s[2,2]=0;n=nav(s)
    assert not p.plan(n,(.15,.15),(2,2)).success
    n=nav();path=p.plan(n,(.35,.35),(5,5));assert path.success and path.valid_for(n)
    assert not path.valid_for(replace(n,revision=2))
    assert not path.valid_for(replace(n,origin_xy=(.1,0)))
    assert not path.valid_for(nav(episode='other'))


def test_navigator_stale_and_unknown_do_not_move():
    navigator=Navigator(geometry(),clock_domain='host_monotonic:test')
    for n,reason in [(nav(), 'nav_stale'),(nav(np.full((15,15),-1,np.int8)), 'no_frontiers')]:
        decision=navigator.step(n,(.75,.75),0.,1_400_000_000 if reason=='nav_stale' else 1_000_000_000)
        assert decision.desired_linear_mps==0 and decision.desired_yaw_radps==0
    assert navigator.step(replace(nav(),clock_domain='replay:test'),(.75,.75),0.,1_000_000_000).reason=='clock_domain_mismatch'


def ready_guard(tmp_path):
    m=mapper(tmp_path)
    m.update(down())
    n=m.update(down(1))
    guard=MotionGuard(m,clock_domain='host_monotonic:test')
    guard.bind_nav(n,robot_xy=(0.,0.),yaw_rad=0.)
    return guard,n


def test_guard_measured_bootstrap_and_missing_depth_stop(tmp_path):
    guard,n=ready_guard(tmp_path)
    d=NavigationDecision('g',((0.,0.),(.3,0.)),.15,0.,n.revision,'tracking')
    command=guard.filter(d,down(2),1_000_000_000)
    assert command.linear_mps>0 and command.deadline_monotonic_ns==1_100_000_000
    assert command.source==down(2).key and command.map_revision==n.revision
    stopped=guard.filter(d,down(3,valid=False),1_000_000_000)
    assert stopped.linear_mps==0 and stopped.reason=='bootstrap_blocked'


@pytest.mark.parametrize('latest,now,reason',[
    (down(2),1_300_000_001,'depth_stale'),
    (down(2,stamp=1_000_000_001),1_000_000_000,'depth_future'),
    (down(2,domain='replay:test'),1_000_000_000,'clock_domain_mismatch'),
    (down(2,domain='host_monotonic:other'),1_000_000_000,'clock_domain_mismatch'),
])
def test_guard_clock_rejections(tmp_path,latest,now,reason):
    guard,n=ready_guard(tmp_path)
    d=NavigationDecision('g',((0.,0.),(.3,0.)),.15,0.,n.revision,'tracking')
    cmd=guard.filter(d,latest,now)
    assert cmd.linear_mps==cmd.yaw_radps==0 and cmd.reason==reason


def test_guard_mismatched_revision_and_replayed_sensor_cannot_move(tmp_path):
    guard,n=ready_guard(tmp_path)
    d=NavigationDecision('g',((0.,0.),(.3,0.)),.15,0.,n.revision,'tracking')
    assert guard.filter(replace(d,map_revision=0),down(2),1_000_000_000).reason=='path_map_revision_stale'
    assert guard.filter(d,down(3),1_000_000_000).linear_mps>0
    cmd=guard.filter(d,down(2),1_000_000_000)
    assert cmd.linear_mps==0 and cmd.reason=='sensor_replay'


def test_future_guard_without_accepted_live_context_raises():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        guard=MotionGuard(mapper(directory),clock_domain='host_monotonic:test')
        d=NavigationDecision(None,(),0.,0.,0,'stop')
        with pytest.raises(ValueError,match='actuator must remain stopped'):
            guard.filter(d,down(stamp=1_000_000_001),1_000_000_000)


def test_future_stop_uses_real_bound_source_and_expired_deadline(tmp_path):
    guard,n=ready_guard(tmp_path)
    d=NavigationDecision('g',((0.,0.),(.3,0.)),.15,0.,n.revision,'tracking')
    command=guard.filter(d,down(2,stamp=1_000_000_001),1_000_000_000)
    assert command.source==n.source and command.source_capture_monotonic_ns==n.capture_monotonic_ns
    assert not command.is_valid(1_000_000_000,'host_monotonic:test')


def test_guard_revision_known_but_sensor_older_than_map_is_rejected(tmp_path):
    guard,n=ready_guard(tmp_path)
    d=NavigationDecision('g',((0.,0.),(.3,0.)),.15,0.,n.revision,'tracking')
    assert guard.filter(d,down(0),1_000_000_000).reason=='sensor_replay'


def test_guard_motion_deadline_limits_checked_swept_distance(tmp_path):
    guard,n=ready_guard(tmp_path)
    d=NavigationDecision('g',((0.,0.),(.3,0.)),.15,0.,n.revision,'tracking')
    command=guard.filter(d,down(2),1_000_000_000)
    assert command.deadline_monotonic_ns<=1_100_000_000


def test_rejected_input_stop_uses_bound_source_and_revision(tmp_path):
    guard,n=ready_guard(tmp_path)
    d=NavigationDecision('g',((0.,0.),(.3,0.)),.15,0.,0,'tracking')
    command=guard.filter(d,down(2,domain='replay:test'),1_000_000_000)
    assert command.source==n.source and command.map_revision==n.revision
    assert command.source_capture_monotonic_ns==n.capture_monotonic_ns


def test_live_input_without_bound_source_cannot_issue_command(tmp_path):
    guard=MotionGuard(mapper(tmp_path),clock_domain='host_monotonic:test')
    d=NavigationDecision(None,(),0.,0.,0,'stop')
    with pytest.raises(ValueError,match='actuator must remain stopped'):
        guard.filter(d,down(),1_000_000_000)


def oracle_fixture():
    import json
    from pathlib import Path
    return json.loads((Path(__file__).parent/'fixtures/navigation/oracles-v1.json').read_text())


def test_independent_source_astar_and_multi_goal_oracles():
    p=Planner(RobotGeometry('cylinder-v1',.001,1.,0.))
    for case in oracle_fixture()['planner']:
        n=nav(np.array(case['states'],np.int8),revision=7,origin=tuple(case['origin']))
        many=p.plan_many(n,tuple(case['start']),tuple(tuple(row['goal']) for row in case['expected']))
        for expected in case['expected']:
            goal=tuple(expected['goal'])
            for result in (p.plan(n,tuple(case['start']),goal),many[goal]):
                assert result.success==expected['success']
                assert result.reason==expected['reason']
                assert result.cost_m==pytest.approx(expected['cost_m']) if expected['cost_m'] is not None else math.isinf(result.cost_m)


def test_independent_source_frontier_and_controller_oracles():
    from neusymnav.navigation.frontiers import FrontierExtractor
    from neusymnav.navigation._grid import adapt
    from neusymnav.navigation._controller_core import Controller,ControllerConfig
    fixture=oracle_fixture()
    states=np.full((25,25),-1,np.int8);states[3:22,3:22]=0
    n=nav(states,revision=7)
    grid=adapt(n,1.,'cylinder-v1')
    frontiers=FrontierExtractor(agent_radius_m=.001,inflation_margin_m=0.).extract(grid,(1.25,1.25))
    assert frontiers.reason==fixture['frontier']['reason']
    assert len(frontiers.frontiers)==len(fixture['frontier']['frontiers'])
    for actual,expected in zip(frontiers.frontiers,fixture['frontier']['frontiers']):
        assert actual.frontier_id==expected['frontier_id']
        assert actual.boundary_cells==tuple(map(tuple,expected['boundary_cells']))
        assert actual.viewpoint_cell==tuple(expected['viewpoint_cell'])
        assert actual.predicted_gain_cells==expected['predicted_gain_cells']
    p=Planner(RobotGeometry('cylinder-v1',.001,1.,0.))
    goal=tuple(fixture['controller']['goal'])
    path=p.core.plan(grid,(1.25,1.25),goal)
    assert path.cells==tuple(map(tuple,fixture['controller']['path']))
    controller=Controller(ControllerConfig(),traversable=p.core.traversable)
    command=controller.tick(robot_xy=(1.25,1.25),yaw_rad=0.,now_monotonic_s=1.,dt_s=.1,
        depth_host_monotonic_s=1.,depth_front_min_m=None,depth_coverage_ok=True,
        snapshot=grid,path=path,frame_id='oracle')
    assert command.reason==fixture['controller']['reason']
    assert command.linear_mps==pytest.approx(fixture['controller']['linear_mps'])
    assert command.yaw_rate_radps==pytest.approx(fixture['controller']['yaw_radps'])


def test_independent_source_raycast_oracle():
    from neusymnav.mapping._raycast_kernel import collect_ray_votes
    case=oracle_fixture()['raycast']
    votes=collect_ray_votes(np.array(case['endpoints']),np.array(case['origin']),
        has_return=np.array(case['has_return'],bool),backend='python',**case['params'])
    assert (votes.min_row,votes.min_col)==(case['min_row'],case['min_col'])
    for name in ('planar_free','planar_hit','floor_hit','height_free','height_hit'):
        assert np.array_equal(getattr(votes,name),np.array(case[name],bool))


def test_swept_footprint_checks_cell_between_safe_endpoints(tmp_path):
    guard,_=ready_guard(tmp_path)
    states=np.zeros((15,15),np.int8);states[7,7]=-1
    n=nav(states)
    assert guard._clear(n,(.35,.75),(.35,.75))
    assert guard._clear(n,(1.15,.75),(1.15,.75))
    assert not guard._clear(n,(.35,.75),(1.15,.75))


def test_guard_checks_curved_pulse_outside_straight_capsule(tmp_path):
    guard,n=ready_guard(tmp_path)
    states=n.states.copy()
    row=round((.1-n.origin_xy[1])/n.resolution_m)
    states[row:,:]=-1
    n=replace(n,states=states)
    start=(0.,-.0001)
    guard.bind_nav(n,robot_xy=start,yaw_rad=0.)
    d=NavigationDecision('g',(start,(.3,start[1])),.2,.5,n.revision,'tracking')
    assert guard._clear(n,start,(.02,start[1]))
    command=guard.filter(d,down(2),1_000_000_000)
    assert command.linear_mps==0 and command.reason=='footprint_not_observed'


def test_viewpoint_memory_survives_rolling_origin():
    navigator=Navigator(geometry(),clock_domain='host_monotonic:test')
    navigator.step(nav(),(.75,.75),0.,1_000_000_000)
    navigator.report_goal_reached('visited',(.75,.75))
    navigator.report_goal_failure('failed',1,goal_world_xy=(.35,.35))
    navigator.step(nav(revision=2,origin=(.1,0.)),(.75,.75),0.,1_000_000_000)
    assert navigator.policy.visited_viewpoints()==((.75,.75),)
    assert navigator.policy._failed_viewpoints==[((.35,.35),101)]
