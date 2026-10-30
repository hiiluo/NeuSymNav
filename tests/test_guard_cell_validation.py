"""Guard optimization preserves scalar safety while bounding geometry work."""
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.contracts import GridState
from neusymnav.mapping.occupancy import RobotGeometry, capsule_cells
from neusymnav.navigation import safety
from neusymnav.navigation.safety import MotionGuard
from test_navigation import nav


def guard(*,radius=.08,height=.5):
    mapper=SimpleNamespace(robot=RobotGeometry('cylinder-v1',radius,height,0.))
    return MotionGuard(mapper,clock_domain='host_monotonic:test')


def scalar_clear(g,n,start,end,margin=0.):
    # Retained pre-optimization predicate, independent of new cache/batching.
    radius=g.mapper.robot.radius_m+g.mapper.robot.margin_m+margin
    return all(0<=r<n.states.shape[0] and 0<=c<n.states.shape[1]
        and n.states[r,c]==GridState.FREE and n.floor_support[r,c]
        and n.clearance[r,c]>=g.mapper.robot.height_m
        for r,c in capsule_cells(n.origin_xy,n.resolution_m,start,end,radius))


def test_repeated_small_clear_geometry_is_reused_without_reenumeration(monkeypatch):
    # Catches removal of the bounded geometry reuse (the requested performance seam).
    original=safety.capsule_cells;calls=[]
    def observed(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(safety,'capsule_cells',observed)
    g=guard();n=nav();a=(.45,.45);b=(.75,.45)
    assert g._clear(n,a,b)
    assert g._clear(replace(n,revision=2),a,b)
    assert len(calls)==1


@pytest.mark.parametrize('field,value',[
    ('states',-1),('states',100),('floor_support',False),('clearance',.49),
])
def test_cached_geometry_reads_fresh_map_safety_arrays(field,value):
    g=guard();n=nav();a=(.45,.45);b=(.75,.45)
    assert g._clear(n,a,b)
    array=getattr(n,field).copy();array[4,5]=value
    changed=replace(n,revision=2,**{field:array})
    assert not g._clear(changed,a,b)
    assert g._clear(n,a,b)


def test_cached_indices_validate_current_map_shape_and_height():
    g=guard();n=nav();a=(.45,.45);b=(.75,.45)
    assert g._clear(n,a,b)
    small=replace(n,states=n.states[:3,:3],floor_support=n.floor_support[:3,:3],clearance=n.clearance[:3,:3])
    assert not g._clear(small,a,b)
    g.mapper.robot=replace(g.mapper.robot,height_m=1.00000001)
    assert not g._clear(n,a,b)


@pytest.mark.parametrize('dtype',[np.float16,np.float32,np.float64,np.longdouble])
def test_clearance_comparison_preserves_scalar_promotion_at_threshold(dtype):
    measured=dtype(.1)
    height=float(measured)+1e-10
    g=guard(height=height)
    n=replace(nav(),clearance=np.full((15,15),measured,dtype=dtype))
    assert not scalar_clear(g,n,(.45,.45),(.65,.45))
    assert not g._clear(n,(.45,.45),(.65,.45))
    equal=guard(height=float(measured))
    assert equal._clear(n,(.45,.45),(.65,.45))


def test_exact_geometry_key_includes_origin_resolution_endpoints_radius():
    g=guard();n=nav();a=(.45,.45);b=(.75,.45)
    states=n.states.copy();states[4,9]=100;n=replace(n,states=states)
    assert g._clear(n,a,b)
    cases=[(replace(n,origin_xy=(-.3,0.)),a,b,0.),
        (replace(n,resolution_m=.05),a,b,0.),
        (n,(.95,.45),b,0.),(n,a,(.95,.45),0.),(n,a,b,.2)]
    for changed,start,end,margin in cases:
        assert bool(g._clear(changed,start,end,swept_margin_m=margin))==bool(scalar_clear(g,changed,start,end,margin))
    # Sub-ULP scale shifts are not rounded to an earlier cached key.
    n=nav();g=guard(radius=.05)
    for delta in (0.,1e-13,-1e-13):
        start=(.3+delta,.3);end=(.6+delta,.3)
        assert bool(g._clear(n,start,end))==bool(scalar_clear(g,n,start,end))


def test_random_paths_match_old_scalar_on_all_safety_fields():
    rng=np.random.default_rng(61029);g=guard()
    for i in range(240):
        n=nav(origin=tuple(rng.uniform(-1.,1.,2)),revision=i)
        if i%4:
            states=rng.choice([-1,0,100],size=n.states.shape,p=[.02,.96,.02]).astype(np.int8)
            support=rng.random(n.states.shape)>.03
            clearance=rng.choice([.49,.5,1.],size=n.states.shape).astype(np.float32)
            n=replace(n,states=states,floor_support=support,clearance=clearance)
        start=tuple(np.asarray(n.origin_xy)+rng.uniform(-.2,1.7,2))
        end=tuple(np.asarray(n.origin_xy)+rng.uniform(-.2,1.7,2));margin=float(rng.uniform(0.,.15))
        expected=bool(scalar_clear(g,n,start,end,margin))
        assert bool(g._clear(n,start,end,swept_margin_m=margin))==expected
        assert bool(g._clear(n,start,end,swept_margin_m=margin))==expected


def test_geometry_cache_evicts_and_never_holds_more_than_64_small_capsules(monkeypatch):
    original=safety.capsule_cells;calls=[]
    def observed(*args):
        calls.append(args)
        return original(*args)
    monkeypatch.setattr(safety,'capsule_cells',observed)
    g=guard();n=nav()
    for i in range(80):
        a=(.4+i*.001,.4);b=(.6+i*.001,.4)
        assert g._clear(n,a,b)
    assert len(g._geometry_cache)<=64
    assert all(len(cells)<=512 for cells in g._geometry_cache.values())
    assert g._clear(n,(.4,.4),(.6,.4))
    assert len(calls)==81 # first geometry was evicted, rather than retained forever


def test_large_capsules_stream_without_cache_and_stop_before_next_blocked_batch(monkeypatch):
    # A generator with a blocked first cell must not be drained to build a cache.
    yielded=[]
    def large(*args):
        for i in range(1000000):
            if i>=512:raise AssertionError('consumed beyond first blocked batch')
            yielded.append(i)
            yield (4,4)
    monkeypatch.setattr(safety,'capsule_cells',large)
    values=nav().states.copy();values[4,4]=100
    g=guard();assert not g._clear(nav(values),(.45,.45),(.75,.45))
    assert len(yielded)<=512


def test_large_clear_capsule_is_not_cached_and_batches_read_at_most_512_cells(monkeypatch):
    reads=[]
    class TracedArray:
        def __init__(self,array):self.array=array;self.shape=array.shape
        def __getitem__(self,key):
            reads.append(1 if np.isscalar(key[0]) else len(key[0]))
            return self.array[key]
    original=nav();n=SimpleNamespace(**original.__dict__)
    n.states=TracedArray(n.states)
    monkeypatch.setattr(safety,'capsule_cells',lambda *args:iter([(4,4)]*1025))
    g=guard()
    assert g._clear(n,(.45,.45),(.75,.45))
    assert all(size<=512 for size in reads)
    assert not g._geometry_cache


def test_actual_large_capsule_matches_scalar_through_later_blocked_batches():
    values=np.zeros((300,300),np.int8)
    n=replace(nav(),states=values,floor_support=np.ones(values.shape,bool),
        clearance=np.ones(values.shape,np.float32))
    g=guard();start=(1.,1.);end=(25.,25.)
    assert scalar_clear(g,n,start,end)
    assert g._clear(n,start,end)
    assert not g._geometry_cache
    # This endpoint cell occurs after the first 512 cells in column/row order.
    values[249,249]=-1
    blocked=replace(n,states=values)
    assert not scalar_clear(g,blocked,start,end)
    assert not g._clear(blocked,start,end)


@pytest.mark.parametrize('cell',[(-1,4),(4,-1),(15,4),(4,15),(2**100,4),(4,-2**100)])
def test_out_of_bounds_cells_fail_before_array_indexing(monkeypatch,cell):
    monkeypatch.setattr(safety,'capsule_cells',lambda *args:iter([cell]))
    assert not guard()._clear(nav(),(.45,.45),(.75,.45))
