"""Local bootstrap is fresh, conservative, and never mutates historical mapping."""
from dataclasses import replace
import math
import numpy as np
from test_navmap import mapper, down


def test_local_bootstrap_matches_full_measured_coverage_without_map_mutation(tmp_path):
    m=mapper(tmp_path)
    m.update(down());m.update(down(1))
    fresh=replace(down(2),capture_monotonic_ns=1_100_000_000)
    revision=m._revision
    full=m.measured_coverage(fresh)
    local=m.measured_coverage(fresh,required_bounds_xy=((-0.2,-0.2),(.4,.2)))
    from neusymnav.mapping.occupancy import capsule_cells
    cells=tuple(capsule_cells(full.origin_xy,full.resolution_m,(0.,0.),(.1,0.),.1))
    for r,c in cells:
        assert local.states[r,c] == full.states[r,c]
        assert local.floor_support[r,c] == full.floor_support[r,c]
        assert local.clearance[r,c] == full.clearance[r,c]
    assert local.source == fresh.key and local.capture_monotonic_ns == fresh.capture_monotonic_ns
    assert m._revision == revision and m._frame_watermarks['navigation'] == 1
    assert m.bootstrap(fresh,robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.1).ready
    invalid=replace(fresh,key=replace(fresh.key,frame_index=3),valid_depth=np.zeros_like(fresh.valid_depth))
    assert not m.bootstrap(invalid,robot_xy=(0.,0.),yaw_rad=math.pi/4,corridor_m=.1).ready
