"""Reuse exact current-frame ray proof; never historical map or changed samples."""
from dataclasses import replace
import numpy as np
from test_navmap import mapper,down


def assert_same(first,second):
    for name in ('states','floor_support','clearance'):assert np.array_equal(getattr(first,name),getattr(second,name)),name
    for name in ('source','capture_monotonic_ns','clock_domain','resolution_m','origin_xy','robot_geometry_id','floor_z_m','calibration_hash'):assert getattr(first,name)==getattr(second,name)


def test_guard_reuses_exact_frame_coverage_without_second_ray_traversal(tmp_path,monkeypatch):
    from neusymnav.mapping import _occupancy_core
    obs=down();m=mapper(tmp_path);expected=m.measured_coverage(obs);m.update(obs)
    def duplicate(*a,**k):raise AssertionError('second traversal of the same registered measured frame')
    monkeypatch.setattr(_occupancy_core,'collect_ray_votes',duplicate)
    actual=m.measured_coverage(obs);assert_same(expected,actual)
    assert m.bootstrap(obs,robot_xy=(0.,0.),yaw_rad=0.,corridor_m=.3).ready


def test_new_invalid_capture_cannot_inherit_historical_free_coverage(tmp_path):
    m=mapper(tmp_path);m.update(down());m.update(down(1));obs=down(2,valid=False);m.update(obs)
    coverage=m.measured_coverage(obs)
    assert not coverage.floor_support.any() and np.all(coverage.states==-1)


def test_changed_samples_with_same_source_cannot_reuse_cached_proof(tmp_path):
    m=mapper(tmp_path);original=down();m.update(original)
    changed=replace(original,valid_depth=np.zeros_like(original.valid_depth))
    coverage=m.measured_coverage(changed)
    assert not coverage.floor_support.any() and np.all(coverage.states==-1)


def test_certified_no_return_rays_do_not_become_measured_coverage(tmp_path):
    m=mapper(tmp_path);obs=replace(down(valid=False),no_return=np.ones((81,81),bool),no_return_range_m=2.)
    m.update(obs);actual=m.measured_coverage(obs)
    assert not actual.floor_support.any() and np.all(actual.states==-1)


def test_reused_votes_match_independent_fresh_mapper_on_mixed_returns(tmp_path):
    rng=np.random.default_rng(1028)
    for index in range(40):
        obs=down(size=13,focal=float(rng.uniform(8,25)),x=float(rng.uniform(-2,2)))
        pose=obs.T_world_camera.copy();pose[1,3]=rng.uniform(-2,2)
        obs=replace(obs,depth_m=rng.uniform(.1,4,(13,13)).astype(np.float32),
            valid_depth=rng.random((13,13))>.2,T_world_camera=pose)
        m=mapper(tmp_path/str(index));expected=m.measured_coverage(obs)
        m.update(obs);actual=m.measured_coverage(obs);assert_same(expected,actual)
        assert not actual.states.flags.writeable


def test_reset_releases_cached_proof_and_metadata_changes_miss_cache(tmp_path):
    m=mapper(tmp_path);obs=down();m.update(obs);old=m.measured_coverage(obs)
    for changed in (replace(obs,capture_monotonic_ns=obs.capture_monotonic_ns+1),
                    replace(obs,clock_domain='host_monotonic:other'),
                    replace(obs,calibration_id='changed-calibration')):
        actual=m.measured_coverage(changed)
        assert actual is not old
        assert actual.capture_monotonic_ns==changed.capture_monotonic_ns
        assert actual.clock_domain==changed.clock_domain
    m.reset('next');assert m._current_coverage is None
