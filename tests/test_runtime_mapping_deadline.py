"""Fully drained late map work can be dropped without reusing it for control."""
import threading
import pytest
from neusymnav.mapping.gpu_raycast_client import CompletedRequestDeadline
from test_runtime_scheduling import pipeline,source,nav_for,wait_for


def pose(obs):
    return dict(source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain,pose_version=obs.pose_version,robot_xy=(0.,0.),yaw_rad=0.)


def test_completed_late_mapping_is_not_published_and_new_frame_recovers(tmp_path):
    class Mapper:
        def update(self,obs):
            if obs.key.frame_index==1:raise CompletedRequestDeadline('fully drained late map')
            return nav_for(obs,obs.key.frame_index+1)
    p,_,_=pipeline(tmp_path,mapper=Mapper(),guard=object(),navigator=object(),clock=lambda:1_000_000_010)
    try:
        first=source(0,modality='depth_only');p.submit_navigation(first,pose(first))
        wait_for(lambda:p.live_navigation_display() is not None)
        old=p.live_navigation_display()
        missed=source(1,modality='depth_only',stamp=1_000_000_001);p.submit_navigation(missed,pose(missed))
        wait_for(lambda:p.health.snapshot()['counts'].get('mapping_deadline_missed',0)==1 or bool(p.health.snapshot()['failed']))
        assert p.health.snapshot()['failed']=={}
        assert p.live_navigation_display() is old
        result=p.control_step(object())
        assert result==dict(executed=False,reason='navigation_source_pending')
        fresh=source(2,modality='depth_only',stamp=1_000_000_002);p.submit_navigation(fresh,pose(fresh))
        wait_for(lambda:p.live_navigation_display().source==fresh.key)
        assert p.health.snapshot()['counts']['mapping_deadline_missed']==1
    finally:assert p.close(2)['clean_shutdown']


def test_real_mapper_late_collect_leaves_no_observation_or_tile_commit(tmp_path):
    from test_navmap import mapper,down
    m=mapper(tmp_path);original=m._core._raycast_collector
    def late(*args,**kwargs):raise CompletedRequestDeadline('fully drained late map')
    m._core._raycast_collector=late
    with pytest.raises(CompletedRequestDeadline):m.update(down(size=9))
    assert m._revision==0 and m._core.version==0 and not m._frame_watermarks and not m._core.tile_keys
    assert m.overview_tiles() is None
    m._core._raycast_collector=original
    assert m.update(down(1,size=9)).revision==1
