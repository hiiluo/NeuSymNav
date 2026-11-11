"""Oracle is full traversal followed by an independent world-cell crop."""
import numpy as np
import pytest
from neusymnav.mapping._raycast_kernel import collect_ray_votes, numba_available

FIELDS=('planar_free','planar_hit','floor_hit','height_free','height_hit')

def assert_crop(full,bounded,bounds):
    r0,c0,r1,c1=bounds
    for name in FIELDS:
        original=getattr(full,name)
        expected=np.zeros((r1-r0,c1-c0)+original.shape[2:],bool)
        for r in range(r0,r1):
            for c in range(c0,c1):
                if full.min_row<=r<full.min_row+original.shape[0] and full.min_col<=c<full.min_col+original.shape[1]:
                    expected[r-r0,c-c0]=original[r-full.min_row,c-full.min_col]
        assert bounded.min_row==r0 and bounded.min_col==c0
        np.testing.assert_array_equal(getattr(bounded,name),expected,err_msg=name)

@pytest.mark.parametrize('backend',['python','numba'])
@pytest.mark.parametrize('seed',range(4))
def test_original_lattice_masks_equal_full_crop(backend,seed):
    if backend=='numba' and not numba_available():pytest.skip('optional numba')
    rng=np.random.default_rng(seed)
    ends=rng.uniform([-3,-.4,-3],[3,2.5,3],(300,3))
    # Exact grid faces, endpoint boundaries, vertical and zero-length rays.
    ends[:8]=[[0,0,0],[.2,.2,.2],[-.2,1.,-.2],[0,1.01,0],
              [0,1.19,0],[0,1.2,0],[0,-.2,0],[0,2,0]]
    origin=np.array([0.,2.,0.])
    kw=dict(has_return=rng.random(300)>.2,trace_free=rng.random(300)>.1,
            resolution_m=.1,origin_x_m=-.13,origin_z_m=.07,floor_y_m=0.,
            robot_height_m=1.01,height_bin_m=.2,ray_step_m=.05,backend=backend)
    full=collect_ray_votes(ends,origin,**kw)
    bounds=(-7,-8,9,10)
    for workers in ([1,4] if backend=='numba' else [1]):
        bounded=collect_ray_votes(ends,origin,**kw,workers=workers,grid_bounds=bounds)
        assert_crop(full,bounded,bounds)

@pytest.mark.parametrize('bounds',[(100,100,103,104),(-1,-1,2,2)])
def test_empty_or_disjoint_votes_are_bounded_unknown(bounds):
    for ends in (np.empty((0,3)),np.array([[0.,0.,0.]])):
        kw=dict(resolution_m=.1,origin_x_m=0.,origin_z_m=0.,floor_y_m=0.,
                robot_height_m=1.,height_bin_m=.2,ray_step_m=.05,backend='python')
        full=collect_ray_votes(ends,np.array([0.,2.,0.]),**kw)
        bounded=collect_ray_votes(ends,np.array([0.,2.,0.]),**kw,grid_bounds=bounds)
        assert_crop(full,bounded,bounds)

@pytest.mark.parametrize('bounds',[(0,0,0,2),(0,0,2,0),(0.,0,2,2),(False,0,2,2),(0,0,2)])
def test_invalid_bounds_rejected(bounds):
    with pytest.raises(ValueError,match='bounds'):
        collect_ray_votes(np.array([[0.,0.,0.]]),np.array([0.,2.,0.]),
            resolution_m=.1,origin_x_m=0.,origin_z_m=0.,floor_y_m=0.,
            robot_height_m=1.,height_bin_m=.2,ray_step_m=.05,grid_bounds=bounds)

@pytest.mark.parametrize('bounds,height', [((0,0,1001,1000),1.),((0,0,1000,1000),100.)])
def test_bounded_output_has_cell_and_byte_budgets_before_allocation(monkeypatch,bounds,height):
    from neusymnav.mapping import _raycast_kernel as kernel
    def forbidden(*args,**kwargs):raise AssertionError('must reject before kernel allocation')
    monkeypatch.setattr(kernel,'_collect_votes_impl',forbidden)
    with pytest.raises(MemoryError,match='bounded vote'):
        kernel.collect_ray_votes(np.empty((0,3)),np.array([0.,2.,0.]),
            resolution_m=.1,origin_x_m=0.,origin_z_m=0.,floor_y_m=0.,
            robot_height_m=height,height_bin_m=.2,ray_step_m=.05,backend='python',grid_bounds=bounds)
