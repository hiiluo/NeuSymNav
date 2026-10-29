"""Independent exact-rational closed-square safety oracle, including bounds."""
from fractions import Fraction as F
from itertools import product
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.contracts import GridState
from neusymnav.mapping.occupancy import capsule_cells
from neusymnav.navigation.safety import MotionGuard


def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return a[0]*b[1]-a[1]*b[0]


def point_segment_distance2(p,a,b):
    d=sub(b,a);v=sub(p,a);length2=dot(d,d)
    t=F(0) if length2==0 else max(F(0),min(F(1),dot(v,d)/length2))
    delta=tuple(v[k]-t*d[k] for k in range(2))
    return dot(delta,delta)


def segments_intersect(a,b,c,d):
    def sign(x):return (x>0)-(x<0)
    u,v=sub(b,a),sub(d,c)
    x,y=cross(u,sub(c,a)),cross(u,sub(d,a))
    z,w=cross(v,sub(a,c)),cross(v,sub(b,c))
    if x==y==z==w==0:
        return all(max(min(a[k],b[k]),min(c[k],d[k]))<=min(max(a[k],b[k]),max(c[k],d[k])) for k in range(2))
    return sign(x)*sign(y)<=0 and sign(z)*sign(w)<=0


def rational_cells(origin,resolution,a,b,radius,window=range(-6,7)):
    """Fixed broad window: no implementation candidate-box formula is reused."""
    origin=tuple(map(F,origin));resolution=F(resolution)
    a=tuple(map(F,a));b=tuple(map(F,b));threshold=F(radius)+F(1,10**12)
    result=[]
    for col,row in product(window,repeat=2):
        low=(origin[0]+col*resolution,origin[1]+row*resolution)
        high=tuple(x+resolution for x in low)
        corners=(low,(high[0],low[1]),high,(low[0],high[1]))
        edges=tuple(zip(corners,corners[1:]+corners[:1]))
        inside=any(all(low[k]<=p[k]<=high[k] for k in range(2)) for p in (a,b))
        if inside or any(segments_intersect(a,b,c,d) for c,d in edges):distance2=F(0)
        else:
            distance2=min([point_segment_distance2(p,c,d) for p in (a,b) for c,d in edges]
                          +[point_segment_distance2(p,a,b) for p in corners])
        if threshold>=0 and distance2<=threshold**2:result.append((row,col))
    return result


def assert_rational(origin,resolution,a,b,radius):
    expected=rational_cells(origin,resolution,a,b,radius)
    actual=list(capsule_cells(tuple(map(float,origin)),float(resolution),tuple(map(float,a)),tuple(map(float,b)),float(radius)))
    assert actual==expected,(origin,resolution,a,b,radius,actual,expected)
    return actual


def test_point_disc_includes_all_four_closed_tangencies():
    assert assert_rational((0,0),1,(F(1,2),F(1,2)),(F(1,2),F(1,2)),F(1,2))==[(0,-1),(-1,0),(0,0),(1,0),(0,1)]


@pytest.mark.parametrize('axis',[0,1])
@pytest.mark.parametrize('direction',[-1,1])
def test_candidate_bounds_include_epsilon_on_both_sides(axis,direction):
    a=[F(1,2),F(1,2)];a[axis]-=direction*F(1,2*10**12)
    actual=assert_rational((0,0),1,a,a,F(1,2))
    required=[0,0];required[1-axis]=direction
    assert tuple(required) in actual


@pytest.mark.parametrize('origin',[(0,0),(F(1,4),F(-1,2))])
def test_rational_segment_geometry_covers_boundaries_in_fixed_window(origin):
    rng=np.random.default_rng(11823)
    for _ in range(18):
        a=tuple(F(int(x),4) for x in rng.integers(-4,5,2))
        b=tuple(F(int(x),4) for x in rng.integers(-4,5,2))
        radius=F(int(rng.integers(0,5)),4)
        assert_rational(origin,1,a,b,radius)


@pytest.mark.parametrize('cell',[(2,1),(1,2)])
@pytest.mark.parametrize('missing',['unknown','occupied','floor','clearance'])
def test_lower_tangent_missing_evidence_blocks_motion_guard(cell,missing):
    nav=SimpleNamespace(origin_xy=(-2.,-2.),resolution_m=1.,states=np.full((5,5),GridState.FREE,np.int8),floor_support=np.ones((5,5),bool),clearance=np.ones((5,5)))
    guard=MotionGuard.__new__(MotionGuard)
    guard.mapper=SimpleNamespace(robot=SimpleNamespace(radius_m=.5,margin_m=0.,height_m=.5))
    point=(.5,.5)
    assert guard._clear(nav,point,point)
    if missing=='unknown':nav.states[cell]=GridState.UNKNOWN
    elif missing=='occupied':nav.states[cell]=GridState.OCCUPIED
    elif missing=='floor':nav.floor_support[cell]=False
    else:nav.clearance[cell]=0.
    assert not guard._clear(nav,point,point)


def test_lower_tangent_outside_snapshot_is_not_free():
    nav=SimpleNamespace(origin_xy=(0.,0.),resolution_m=1.,states=np.full((3,3),GridState.FREE,np.int8),floor_support=np.ones((3,3),bool),clearance=np.ones((3,3)))
    guard=MotionGuard.__new__(MotionGuard)
    guard.mapper=SimpleNamespace(robot=SimpleNamespace(radius_m=.5,margin_m=0.,height_m=.5))
    assert not guard._clear(nav,(.5,.5),(.5,.5))


@pytest.mark.parametrize("origin",[(1e16,1e16),(-1e16,-1e16)])
def test_huge_translated_origin_cannot_omit_exact_rational_tangencies(origin):
 # Inputs .25 and integers are exact binary rationals; broad fixed-window oracle
 # does not share implementation candidate bounds or world float arithmetic.
 expected=rational_cells(tuple(map(F,origin)),F(1,4),tuple(map(F,origin)),tuple(map(F,origin)),F(1,4),window=range(-4,5))
 actual=list(capsule_cells(origin,.25,origin,origin,.25))
 assert actual==expected,(actual,expected)

@pytest.mark.parametrize("missing",["unknown","occupied","floor","clearance"])
def test_large_origin_guard_must_block_omitted_tangent_cell(missing):
 origin=(1e16,1e16);point=(1e16+2.,1e16+2.)
 nav=SimpleNamespace(origin_xy=origin,resolution_m=.25,states=np.full((20,20),GridState.FREE,np.int8),floor_support=np.ones((20,20),bool),clearance=np.ones((20,20)))
 guard=MotionGuard.__new__(MotionGuard);guard.mapper=SimpleNamespace(robot=SimpleNamespace(radius_m=.25,margin_m=0.,height_m=.5))
 assert guard._clear(nav,point,point)
 cell=(8,6) # square high-x at origin+1.75, tangent .25 from point origin+2
 if missing=="unknown":nav.states[cell]=GridState.UNKNOWN
 elif missing=="occupied":nav.states[cell]=GridState.OCCUPIED
 elif missing=="floor":nav.floor_support[cell]=False
 else:nav.clearance[cell]=0.
 assert not guard._clear(nav,point,point)



@pytest.mark.parametrize('origin',[(0.,0.),(-.125,.25),(1e16,1e16),(-1e16,1e16)])
def test_representable_translation_preserves_complete_rational_segment(origin):
    # Offsets 0,+/-2 remain represented even at +/-1e16. The rational oracle
    # retains all cell edges and radii exactly instead of adding them in float.
    a=origin;b=(origin[0]+2.,origin[1]-2.)
    expected=rational_cells(tuple(map(F,origin)),F(1,2),tuple(map(F,a)),tuple(map(F,b)),F(1,2),window=range(-7,8))
    actual=list(capsule_cells(origin,.5,a,b,.5))
    assert actual==expected
    assert actual==list(capsule_cells((0.,0.),.5,(0.,0.),(2.,-2.),.5))
