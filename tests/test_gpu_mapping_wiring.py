"""Explicit GPU selection keeps mapper semantics and owns worker cleanup."""
from dataclasses import replace
import numpy as np
import pytest
from contract_helpers import observation
from neusymnav.mapping.occupancy import NavMapper,RobotGeometry
from neusymnav.mapping._raycast_kernel import collect_ray_votes


class Backend:
    def __init__(self):self.calls=0;self.closed=0
    def collect(self,*a,**kw):
        self.calls+=1
        return collect_ray_votes(*a,**kw,backend='python')
    def close(self,timeout_s=1.):self.closed+=1;return dict(clean_shutdown=True)


def mapper(tmp_path,backend=None):
    return NavMapper(robot=RobotGeometry('cylinder',.1,1.),floor_z_m=0.,floor_datum_source='fixture',
        calibration_hash='a'*64,raycast_backend=backend,tile_archive_dir=tmp_path,snapshot_radius_m=1.)


def test_selected_backend_receives_exact_rays_and_map_matches_reference(tmp_path):
    b=Backend();gpu=mapper(tmp_path/'gpu',b);cpu=mapper(tmp_path/'cpu')
    obs=observation()
    a=gpu.update(obs);expected=cpu.update(obs)
    assert b.calls==1
    assert a.to_json()==expected.to_json()
    assert gpu.close(timeout_s=.5)['clean_shutdown'] and b.closed==1
    with pytest.raises(RuntimeError,match='closed'):gpu.update(replace(obs,key=replace(obs.key,frame_index=1)))


def test_worker_failure_does_not_fall_back_or_publish_map(tmp_path):
    class Broken(Backend):
        def collect(self,*a,**kw):raise RuntimeError('GPU lost')
    b=Broken();g=mapper(tmp_path/'gpu',b)
    with pytest.raises(RuntimeError,match='GPU lost'):g.update(observation())
    assert g._revision==0 and not g._frame_watermarks
    assert g.close()['clean_shutdown']


def test_failed_graph_startup_still_owns_mapper_shutdown(tmp_path):
    from neusymnav.runtime import Pipeline
    class Owned:
        def __init__(self):self.closed=0
        def close(self,timeout_s=1.):self.closed+=1;return dict(clean_shutdown=True)
    m=Owned()
    def broken():raise RuntimeError('injected graph startup failure')
    p=Pipeline(tmp_path,episode_id='episode',primary_sensor_id='rgbd',floor_id='f',
        clock_domain='host_monotonic:gpu-startup-test',owner_factory=broken,
        detector_factory=lambda:None,mapper=m)
    assert 'navigation' not in p._threads
    report=p.close(2.)
    assert m.closed==1
    assert report['failed'] and not report['workers_pending']


def test_failed_startup_mapper_pending_shutdown_can_be_retried(tmp_path):
    from neusymnav.runtime import Pipeline
    class Owned:
        def __init__(self):self.calls=0
        def close(self,timeout_s=1.):
            self.calls+=1;return dict(clean_shutdown=self.calls>1)
    m=Owned()
    def broken():raise RuntimeError('startup failed')
    p=Pipeline(tmp_path,episode_id='episode',primary_sensor_id='rgbd',floor_id='f',
        clock_domain='host_monotonic:gpu-startup-test',owner_factory=broken,
        detector_factory=lambda:None,mapper=m)
    assert 'mapper' in p.close(2.)['workers_pending']
    assert 'mapper' not in p.close(2.)['workers_pending']
