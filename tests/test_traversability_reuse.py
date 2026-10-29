"""Borrowed masks stay immutable and invalidate on contents, not just revisions."""
from dataclasses import replace
import numpy as np
import pytest
from test_navigation import nav
from neusymnav.navigation._grid import adapt, footprint_mask
from neusymnav.navigation._planner_core import AStarPlanner,PlannerConfig


def test_same_observed_grid_reuses_immutable_mask_without_trusting_revision():
    planner=AStarPlanner(PlannerConfig(.1,.05));grid=adapt(nav(),1.,'cylinder-v1')
    first=planner.traversable(grid)
    assert planner.traversable(grid) is first
    with pytest.raises(ValueError):first.setflags(write=True)
    changed=grid.states.copy();changed[7,7]=100
    second=planner.traversable(replace(grid,states=changed))
    assert not second[7,7] and first[7,7]
    assert np.array_equal(second,footprint_mask(replace(grid,states=changed),.15))


def test_mask_reuse_matches_reference_on_random_new_frames_and_resolution():
    rng=np.random.default_rng(55);planner=AStarPlanner(PlannerConfig(.1,.05))
    for _ in range(30):
        values=rng.choice([-1,0,100],(25,25),p=[.05,.9,.05]).astype(np.int8)
        n=nav(values)
        for res in [.05,.1,.2]:
            grid=adapt(replace(n,resolution_m=res),1.,'cylinder-v1')
            assert np.array_equal(planner.traversable(grid),footprint_mask(grid,.15))
