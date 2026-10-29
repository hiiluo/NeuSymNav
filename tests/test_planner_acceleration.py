"""The optional compiled engine preserves Python paths, ties and partial-budget results."""
from dataclasses import replace
import numpy as np
from test_navigation import nav
from neusymnav.navigation._grid import adapt
from neusymnav.navigation._planner_core import AStarPlanner,PlannerConfig


def test_compiled_and_python_search_match_exactly_including_partial_goals():
    rng=np.random.default_rng(193)
    for case in range(60):
        size=7+case%9;states=rng.choice([-1,0,100],(size,size),p=[.05,.88,.07]).astype(np.int8)
        states[2,2]=0
        grid=adapt(nav(states),1.,'cylinder-v1');config=PlannerConfig(.001,0.,case%2==0,[1,4,15,500000][case%4])
        fast=AStarPlanner(config);slow=AStarPlanner(config,accelerate_many=False)
        edges=frozenset({((2,2),(2,3)),((3,3),(4,4))}) if case%3==0 else frozenset()
        goals=((1,1),(size-2,size-2),(size//2,size//2),(-1,4))
        actual=fast.plan_many(grid,(.25,.25),goals,blocked_edges=edges)
        expected=slow.plan_many(grid,(.25,.25),goals,blocked_edges=edges)
        assert tuple(actual.items())==tuple(expected.items())


def test_noncanonical_blocked_edges_retain_reference_semantics():
    grid=adapt(nav(),1.,'cylinder-v1');config=PlannerConfig(.001,0.)
    first=AStarPlanner(config,accelerate_many=False).plan_many(grid,(.25,.25),((6,6),))[(6,6)]
    a,b=first.cells[:2];edges=frozenset({tuple(reversed(tuple(sorted((a,b)))))})
    fast=AStarPlanner(config).plan_many(grid,(.25,.25),((6,6),),blocked_edges=edges)
    slow=AStarPlanner(config,accelerate_many=False).plan_many(grid,(.25,.25),((6,6),),blocked_edges=edges)
    assert fast==slow
