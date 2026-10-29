"""Scalar geometry parity in a stable local frame, plus bounded allocation."""
import inspect
import itertools
import math

import numpy as np
import pytest

from neusymnav.mapping.occupancy import capsule_cells


def original_capsule_cells(origin_xy, resolution_m, start, end, radius, *, bounds=None):
    """Closed squares intersecting a world-space swept circular footprint."""
    a=np.asarray(start,float); b=np.asarray(end,float); d=b-a
    lo=np.floor((np.minimum(a,b)-radius-np.asarray(origin_xy))/resolution_m).astype(int)
    hi=np.floor((np.maximum(a,b)+radius-np.asarray(origin_xy))/resolution_m).astype(int)
    if bounds is not None:lo,hi=bounds
    for col in range(lo[0],hi[0]+1):
        for row in range(lo[1],hi[1]+1):
            low=np.asarray(origin_xy)+np.array([col,row])*resolution_m
            high=low+resolution_m
            # Slab intersection establishes zero distance to the rectangle.
            t0,t1=0.,1.
            for axis in (0,1):
                if abs(d[axis])<1e-15:
                    if a[axis]<low[axis] or a[axis]>high[axis]: t1=-1.;break
                else:
                    u,v=(low[axis]-a[axis])/d[axis],(high[axis]-a[axis])/d[axis]
                    t0=max(t0,min(u,v));t1=min(t1,max(u,v))
            distance=0. if t0<=t1 else math.inf
            for point in (a,b):
                distance=min(distance,float(np.linalg.norm(np.maximum(np.maximum(low-point,point-high),0))))
            for corner in (low,high,np.array([low[0],high[1]]),np.array([high[0],low[1]])):
                t=0. if d@d==0 else min(1.,max(0.,float((corner-a)@d/(d@d))))
                distance=min(distance,float(np.linalg.norm(corner-(a+t*d))))
            if distance<=radius+1e-12: yield row,col


def local_args(origin,resolution,a,b,radius):
    # The world-space legacy arithmetic is known to erase cell edges at huge
    # origins; preserve its scalar distance kernel in the same local geometry.
    return ((0.,0.),resolution,np.asarray(a,float)-np.asarray(origin,float),
            np.asarray(b,float)-np.asarray(origin,float),radius)


def corrected_scalar_cells(origin,resolution,a,b,radius):
    origin,resolution,a,b,radius=local_args(origin,resolution,a,b,radius)
    # Broad envelope plus the independent scalar kernel tests geometry;
    # fixed-window Fraction tests independently establish complete bounds.
    lo=np.floor((np.minimum(a,b)-(radius+1e-12))/resolution).astype(int)-2
    hi=np.floor((np.maximum(a,b)+(radius+1e-12))/resolution).astype(int)+2
    return original_capsule_cells(origin,resolution,a,b,radius,bounds=(lo,hi))


def assert_scalar_geometry(*args):
    actual=list(capsule_cells(*args))
    origin,resolution,a,b,radius=local_args(*args)
    lo=np.floor((np.minimum(a,b)-radius)/resolution).astype(int)
    hi=np.floor((np.maximum(a,b)+radius)/resolution).astype(int)
    in_legacy_box=[(r,c) for r,c in actual if lo[0]<=c<=hi[0] and lo[1]<=r<=hi[1]]
    assert in_legacy_box==list(original_capsule_cells(origin,resolution,a,b,radius)),args
    assert actual==list(corrected_scalar_cells(*args)),args
    assert actual==sorted(set(actual),key=lambda rc:(rc[1],rc[0]))


@pytest.mark.parametrize('origin',[(0.,0.),(-1.37,2.23),(1e5,-1e5)])
@pytest.mark.parametrize('resolution',[1.,.05,1e-7])
def test_random_capsules_match_local_scalar_geometry(origin,resolution):
    rng=np.random.default_rng(771612)
    for _ in range(60):
        a=np.asarray(origin)+rng.uniform(-3,3,2)*resolution
        b=a+rng.uniform(-4,4,2)*resolution
        radius=rng.uniform(0,2)*resolution
        assert_scalar_geometry(origin,resolution,a,b,radius)


@pytest.mark.parametrize('angle',[0.,math.pi/2,math.pi,-math.pi/2,.37,2.63])
def test_rotated_reversed_degenerate_and_parallel_slabs(angle):
    direction=np.array([math.cos(angle),math.sin(angle)])
    origin=(-.73,.29);resolution=.1
    for offset,radius,length in itertools.product([0.,.05,-.1],[0.,.05,.1],[0.,1e-16,.4]):
        a=np.asarray(origin)+offset
        b=a+length*direction
        assert_scalar_geometry(origin,resolution,a,b,radius)
        assert_scalar_geometry(origin,resolution,b,a,radius)


def test_closed_square_tangencies_and_boundary_epsilon():
    # The original distance comparison remains; its incomplete box is fixed.
    assert (0,0) in list(capsule_cells((0,0),1.,(.5,.5),(1.5,.5),.5))
    assert (1,0) in list(capsule_cells((0,0),1.,(.5,.5),(1.5,.5),.5))
    assert (1,1) in list(capsule_cells((0,0),1.,(.5,.5),(.5,.5),math.sqrt(.5)))
    for delta in [-2e-12,-1e-12,-.5e-12,0.,.5e-12,1e-12,2e-12]:
        for radius in [0.,.25,.5,math.sqrt(.5)]:
            for a,b in [((.5,.5),(.5,.5)),((.5,.5),(2.5,.5)),((.5,.5),(2.5,2.5))]:
                assert_scalar_geometry((0,0),1.,a,b,radius+delta)
    # A cell in the candidate box lies just outside the actual closed capsule.
    assert (1,0) in list(capsule_cells((0,0),1.,(.5,.5),(2.,.5-2e-12),.5))
    assert (1,1) not in list(capsule_cells((0,0),1.,(.5,.5-3e-12),(2.,.5-3e-12),.5))


def test_rounding_at_arbitrary_tangencies_matches_local_scalar():
    rng=np.random.default_rng(243881)
    for _ in range(300):
        origin=rng.uniform(-10,10,2)
        resolution=float(rng.choice([.005,.1,1.,10.]))
        a=origin+rng.uniform(-1,1,2)*resolution
        b=a+rng.uniform(-2,2,2)*resolution
        corner=origin+rng.integers(-2,3,2)*resolution
        d=b-a;t=min(1.,max(0.,float((corner-a)@d/(d@d))))
        radius=float(np.linalg.norm(corner-(a+t*d)))-1e-12
        for r in [radius,np.nextafter(radius,-math.inf),np.nextafter(radius,math.inf)]:
            assert_scalar_geometry(origin,resolution,a,b,r)


def test_float32_inputs_and_array_like_origins():
    assert_scalar_geometry(np.array([.2,-.7],np.float32),np.float32(.05),
                    np.array([-.13,.81],np.float32),[.19,.83],np.float32(.1))


def test_large_candidate_box_is_lazy_and_batches_are_bounded(monkeypatch):
    import neusymnav.mapping.occupancy as occupancy
    original_arange=occupancy.np.arange
    sizes=[]
    def bounded_arange(*args,**kwargs):
        value=original_arange(*args,**kwargs)
        sizes.append(value.size)
        assert value.size<=4096
        return value
    monkeypatch.setattr(occupancy.np,'arange',bounded_arange)
    stream=capsule_cells((0,0),.05,(0.,0.),(1e9,0.),.25)
    assert inspect.isgenerator(stream)
    assert not sizes
    prefix=list(itertools.islice(stream,50))
    assert prefix==list(itertools.islice(corrected_scalar_cells((0,0),.05,(0.,0.),(1e9,0.),.25),50))
    assert sizes and max(sizes)<=4096
    assert len(sizes)==1


def test_generator_defers_input_conversion_until_first_iteration():
    start=[.5,.5]
    stream=capsule_cells((0,0),1.,start,(.5,.5),0.)
    start[0]=1.5
    assert list(stream)==list(corrected_scalar_cells((0,0),1.,start,(.5,.5),0.))
    invalid=capsule_cells((0,0),0.,(0.,0.),(1.,1.),.5)
    assert inspect.isgenerator(invalid)


@pytest.mark.parametrize('end',[(12.,12.),(0.,250.)])
def test_multiple_chunks_preserve_geometry_and_column_row_order(end):
    assert_scalar_geometry((-.13,.17),.05,(0.,0.),end,.12)


def test_candidate_row_count_larger_than_int64_remains_lazy():
    args=((0,0),1.,(0.,-5e18),(0.,5e18),.25)
    prefix=list(itertools.islice(capsule_cells(*args),4))
    assert len(prefix)==4
    assert all(col==-1 for row,col in prefix)
    assert [row for row,col in prefix]==list(range(prefix[0][0],prefix[0][0]+4))
    for row,col in prefix:
        assert list(original_capsule_cells(*args,bounds=((col,row),(col,row))))==[(row,col)]


def test_large_coordinates_degenerate_and_overflowing_norms_match_local_scalar():
    for origin,resolution,a,b,radius in [
        ((1e16,-1e16),1.,(1e16,-1e16),(1e16+4,-1e16),2.),
        ((1e200,-1e200),1e200,(0.,0.),(1e200,1e200),1e199),
    ]:
        with np.errstate(over='ignore',invalid='ignore',under='ignore'):
            assert_scalar_geometry(origin,resolution,a,b,radius)


def test_epsilon_dominating_tiny_cells_still_has_bounded_lazy_allocation(monkeypatch):
    import neusymnav.mapping.occupancy as occupancy
    class BatchObserved(Exception):pass
    stream=capsule_cells((0.,0.),1e-160,(0.,0.),(1e-160,2e-160),1e-160)
    def observe_norm(value,axis=None):
        assert value.shape==(4096,2)
        assert value.dtype==np.float64
        raise BatchObserved
    monkeypatch.setattr(occupancy.np.linalg,'norm',observe_norm)
    with pytest.raises(BatchObserved):next(stream)
