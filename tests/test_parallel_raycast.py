"""Parallelism may change scheduling, never the observed occupancy votes."""
import numpy as np
import pytest
from neusymnav.mapping import _raycast_kernel as kernel


def case(seed=1,n=300):
    rng=np.random.default_rng(seed)
    return rng.uniform([-.7,-.1,-.7],[.7,1.6,.7],(n,3)),dict(camera_origin_world=np.array([0.,1.5,0.]),has_return=rng.choice([False,True],n),resolution_m=.1,origin_x_m=-.03,origin_z_m=.07,floor_y_m=0.,robot_height_m=1.5,height_bin_m=.1,ray_step_m=.05)


@pytest.mark.parametrize("workers", [2, 4])
def test_two_chunks_have_exact_reference_votes(workers):
    endpoints,kwargs=case()
    expected=kernel.collect_ray_votes(endpoints,**kwargs,backend='python')
    actual=kernel.collect_ray_votes(endpoints,**kwargs,workers=workers)
    assert (actual.min_row,actual.min_col)==(expected.min_row,expected.min_col)
    for name in ['planar_free','planar_hit','floor_hit','height_free','height_hit']:
        assert np.array_equal(getattr(actual,name),getattr(expected,name))


@pytest.mark.parametrize('workers',[True,0,5,-1,1.5,'2',None])
def test_parallel_budget_is_explicit_and_bounded(workers):
    endpoints,kwargs=case(n=4)
    with pytest.raises(ValueError,match='workers'):kernel.collect_ray_votes(endpoints,**kwargs,workers=workers)


def test_two_workers_write_separate_vote_arrays_and_are_joined(monkeypatch):
    import threading
    barrier=threading.Barrier(2);seen=[]
    def native(*args):
        barrier.wait(timeout=3)
        result=kernel._collect_votes_impl(*args);seen.append(result)
        return result
    monkeypatch.setattr(kernel,'_numba_collect_votes',native)
    endpoints,kwargs=case()
    actual=kernel.collect_ray_votes(endpoints,**kwargs,workers=2)
    expected=kernel.collect_ray_votes(endpoints,**kwargs,backend='python')
    assert len(seen)==2 and not np.shares_memory(seen[0][0],seen[1][0])
    assert np.array_equal(actual.height_free,expected.height_free)
    assert barrier.n_waiting==0


@pytest.mark.parametrize('workers',[1,2,4])
def test_runtime_config_propagates_bounded_workers(tmp_path,workers):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    path=config(tmp_path,navigation=dict(mapper=dict(raycast_workers=workers)))
    assert load_config(path).data['navigation']['mapper']['raycast_workers']==workers


@pytest.mark.parametrize('workers',[True,0,5,2.0,'4'])
def test_runtime_config_rejects_unbounded_or_noninteger_workers(tmp_path,workers):
    from test_launcher import config
    from neusymnav.runtime.configuration import load_config
    path=config(tmp_path,navigation=dict(mapper=dict(raycast_workers=workers)))
    with pytest.raises(ValueError):load_config(path)
