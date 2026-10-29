"""Reuse only identical mathematical searches, while binding fresh output revision."""
from dataclasses import replace
import numpy as np
import pytest
from test_navigation import nav
from neusymnav.navigation._grid import adapt
from neusymnav.navigation._planner_core import AStarPlanner,PlannerConfig


def test_same_search_does_not_repeat_wavefront_and_refreshes_revision(monkeypatch):
    from neusymnav.navigation import _planner_core
    planner=AStarPlanner(PlannerConfig(.1,.0));grid=adapt(nav(),1.,'cylinder-v1')
    goals=((6,6),(9,9));first=planner.plan_many(grid,(.35,.35),goals)
    assert all(r.success for r in first.values())
    monkeypatch.setattr(_planner_core.heapq,'heappop',lambda *_:pytest.fail('identical fresh grid repeated wavefront'))
    current=replace(grid,revision=2,as_of_frame_id='new',host_monotonic_s=1.1)
    second=planner.plan_many(current,(.36,.36),goals)
    assert all(r.map_revision==2 for r in second.values())
    assert [r.cells for r in second.values()]==[r.cells for r in first.values()]


def test_content_or_blocked_edges_change_invalidate_same_revision():
    planner=AStarPlanner(PlannerConfig(.001,0.));grid=adapt(nav(),1.,'cylinder-v1')
    goal=(5,5);start=(.35,.35)
    first=planner.plan_many(grid,start,(goal,))[goal];assert first.success
    a,b=first.cells[:2]
    blocked=frozenset({tuple(sorted((a,b)))})
    changed=planner.plan_many(grid,start,(goal,),blocked_edges=blocked)[goal]
    oracle=AStarPlanner(planner.config).plan(grid,start,goal,blocked_edges=blocked)
    assert changed.cost_m==pytest.approx(oracle.cost_m) and changed.cells!=first.cells
    states=grid.states.copy();states[goal]=100
    assert not planner.plan_many(replace(grid,states=states),start,(goal,))[goal].success


def test_cached_many_matches_independent_single_goal_on_random_frames():
    rng=np.random.default_rng(981);p=AStarPlanner(PlannerConfig(.001,0.))
    for index in range(30):
        states=rng.choice([-1,0,100],(15,15),p=[.05,.9,.05]).astype(np.int8);states[3,3]=0
        grid=adapt(nav(states),1.,'cylinder-v1');goals=((5,5),(8,8),(12,12))
        p.plan_many(grid,(.35,.35),goals)
        current=replace(grid,revision=index+2)
        many=p.plan_many(current,(.35,.35),goals)
        for goal in goals:
            single=AStarPlanner(p.config).plan(current,(.35,.35),goal)
            assert many[goal].success==single.success
            assert many[goal].cost_m==pytest.approx(single.cost_m)


def test_cache_key_snapshots_configuration_values_and_mutable_edge_sets():
    planner=AStarPlanner(PlannerConfig(.001,0.));grid=adapt(nav(),1.,'cylinder-v1')
    goal=(5,5);start=(.35,.35)
    initial=planner.plan_many(grid,start,(goal,))[goal]
    object.__setattr__(planner.config,'allow_diagonal',False)
    straight=planner.plan_many(grid,start,(goal,))[goal]
    assert straight.cost_m>initial.cost_m
    edges=set();first=planner.plan_many(grid,start,(goal,),blocked_edges=edges)[goal]
    edges.add(tuple(sorted(first.cells[:2])))
    reroute=planner.plan_many(grid,start,(goal,),blocked_edges=edges)[goal]
    assert reroute.cells!=first.cells
