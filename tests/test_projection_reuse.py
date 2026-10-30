"""Exact local measured projection reuse without changing rejection or map evidence."""
from dataclasses import replace
import numpy as np
import pytest
from test_navmap import mapper, down


def legacy_update(m, obs):
    """Retain the original adapter path, explicitly discarding preflight output."""
    check=m._check_ray_budget
    def no_reuse(frame):
        check(frame)
        return None
    m._check_ray_budget=no_reuse
    return m.update(obs)


def assert_map_bytes(a,b):
    assert a.to_json()==b.to_json()


def test_measured_projection_constructed_once(tmp_path,monkeypatch):
    # Reconstructing pixel columns in core would reintroduce the measured work.
    original=np.column_stack;calls=[]
    def record(*args,**kwargs):
        calls.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(np,'column_stack',record)
    result=mapper(tmp_path).update(down(size=9))
    assert result.revision==1
    assert not calls,'core reconstructed the measured projection after preflight'


@pytest.mark.parametrize('kind',['measured','empty','no_return','near_pinhole'])
def test_reused_map_matches_original_path_exactly(tmp_path,kind):
    a=mapper(tmp_path/'a');b=mapper(tmp_path/'b')
    rng=np.random.default_rng(1030)
    for i in range(3):
        obs=down(i,size=9,focal=13.,x=.013*i)
        depth=rng.uniform(.05,5.1,(9,9)).astype(np.float32)
        valid=rng.random((9,9))>.25
        if kind=='empty':valid[:]=False
        if kind=='no_return':
            valid[:,::2]=False
            obs=replace(obs,valid_depth=valid,no_return=~valid,no_return_range_m=2.)
        if kind=='near_pinhole':
            k=obs.K.copy();k[2,0]=1e-12;obs=replace(obs,K=k)
        obs=replace(obs,depth_m=depth,valid_depth=valid)
        assert_map_bytes(a.update(obs),legacy_update(b,obs))
        assert a._core.tile_keys==b._core.tile_keys
        for key in a._core.tile_keys:
            for field in ('planar_log_odds','height_log_odds','floor_support'):
                assert getattr(a._core._tiles[key],field).tobytes()==getattr(b._core._tiles[key],field).tobytes()


@pytest.mark.parametrize('kind',['extent','count','height'])
def test_budget_rejections_leave_no_state_or_collector_call(tmp_path,kind):
    m=mapper(tmp_path,height_bin_m=.00001 if kind=='height' else .05)
    obs=down(size=317 if kind=='count' else 81 if kind=='height' else 9,focal=.0001 if kind=='extent' else 40.)
    def forbidden(*a,**k):raise AssertionError('collector called before budget validation')
    m._core._raycast_collector=forbidden
    with pytest.raises(MemoryError):m.update(obs)
    assert m._revision==0 and not m._frame_watermarks and m._clock_domain is None
    assert m._core.version==0 and not m._core._seen_frames and not m._core.tile_keys


def test_collector_failure_retry_and_reset_never_reuse_old_projection(tmp_path):
    m=mapper(tmp_path);obs=down(size=9)
    collector=m._core._raycast_collector
    def fail(*a,**k):raise RuntimeError('collector failure')
    m._core._raycast_collector=fail
    with pytest.raises(RuntimeError,match='collector failure'):m.update(obs)
    assert not m._frame_watermarks and not m._core._seen_frames
    m._core._raycast_collector=collector
    changed=replace(obs,depth_m=np.full((9,9),1.5,np.float32))
    assert_map_bytes(m.update(changed),mapper(tmp_path/'fresh').update(changed))
    m.reset('ep')
    assert_map_bytes(m.update(obs),mapper(tmp_path/'reset').update(obs))


def test_call_local_projection_cannot_be_replayed_for_another_observation(tmp_path):
    from neusymnav.mapping._occupancy_core import _PreparedMeasuredProjection
    m=mapper(tmp_path);first=m._adapt(down(size=9));other=m._adapt(down(1,size=9))
    points=m._check_ray_budget(down(size=9))
    with pytest.raises(ValueError,match='call-local'):
        m._core._integrate(other,_PreparedMeasuredProjection(first,points))
    assert not m._core._seen_frames and not m._core.tile_keys


def test_exact_measured_count_limit_and_no_return_count_rejection(tmp_path):
    from contract_helpers import observation
    m=mapper(tmp_path)
    n=100_000
    obs=observation(rgb=np.zeros((1,n,3),np.uint8),depth_m=np.ones((1,n),np.float32),
        valid_depth=np.ones((1,n),bool),K=np.diag([1e5,1e5,1.]))
    assert m._check_ray_budget(obs).shape==(n,3)
    n+=1
    obs=observation(rgb=np.zeros((1,n,3),np.uint8),depth_m=np.ones((1,n),np.float32),
        valid_depth=np.zeros((1,n),bool),no_return=np.ones((1,n),bool),no_return_range_m=2.,
        K=np.diag([1e5,1e5,1.]))
    with pytest.raises(MemoryError,match='ray count'):m.update(obs)
    assert m._revision==0 and not m._core.tile_keys
