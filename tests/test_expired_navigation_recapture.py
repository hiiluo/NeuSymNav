"""Expired acquisition is recorded, skipped for control, then reacquired."""
from types import SimpleNamespace
import pytest
from neusymnav.runtime import launcher
from test_runtime_scheduling import pipeline, source, wait_for, nav_for
from test_runtime_places import pose
from test_capture_pair_publication import Observer


@pytest.mark.parametrize('paired',[False,True])
def test_expired_navigation_is_recorded_once_and_next_fresh_source_can_run(tmp_path, paired):
    observer=Observer();clock=[1_400_000_001]
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    p,_,_=pipeline(tmp_path,clock=lambda:clock[0],mapper=Mapper(),measurements=observer)
    old=source(0,modality='depth_only');rgb=source(0)
    fresh=source(1,stamp=clock[0],modality='depth_only')
    sensor=SimpleNamespace(capture=lambda:rgb,capture_navigation=lambda:old,robot_pose=pose)
    raw=[];display=[]
    try:
        if paired:
            result=launcher._capture_sensor_pair(sensor,p,raw.append,lambda *args:display.append(args))
            assert result==(rgb,None)
            assert raw==[rgb,old] and observer.captures==[rgb.key,old.key]
        else:
            assert launcher._capture_navigation(sensor,p,raw.append,lambda *args:display.append(args)) is None
            assert raw==[old] and observer.captures==[old.key]
        assert not display and p._latest_depth is None
        sensor.capture_navigation=lambda:fresh
        assert launcher._capture_navigation(sensor,p,raw.append) is fresh
        wait_for(lambda:p._latest_nav is not None)
        assert p._latest_nav.source == fresh.key
        assert observer.captures.count(old.key) == 1
        assert p.health.snapshot()['counts']['navigation_capture_expired'] == 1
    finally:
        assert p.close(3.)['clean_shutdown']


def test_expiration_after_partial_pair_admission_is_not_retried_or_double_counted():
    from neusymnav.runtime.coordinator import StaleNavigationCapture
    rgb=source(0);nav=source(0,modality='depth_only');observer=Observer()
    p=SimpleNamespace(measurements=observer,_last_index=-1)
    def partial(*args):
        p._last_index=rgb.key.frame_index
        observer.capture(rgb)
        raise StaleNavigationCapture('body pose source is stale')
    p.submit_sensor_pair=partial
    sensor=SimpleNamespace(capture=lambda:rgb,capture_navigation=lambda:nav,robot_pose=pose)
    raw=[];display=[]
    with pytest.raises(StaleNavigationCapture):
        launcher._capture_sensor_pair(sensor,p,raw.append,lambda *args:display.append(args))
    assert raw==[rgb,nav] and observer.captures==[rgb.key]
    assert len(display)==1 and display[0][1] is nav


def test_other_pose_admission_errors_remain_fatal():
    nav=source(0,modality='depth_only')
    def fail(*args):raise ValueError('body pose source/time/domain/version mismatch')
    p=SimpleNamespace(measurements=Observer(),submit_navigation=fail)
    sensor=SimpleNamespace(capture_navigation=lambda:nav,robot_pose=pose)
    with pytest.raises(ValueError,match='mismatch'):
        launcher._capture_navigation(sensor,p,lambda obs:None)


def test_capture_expiring_during_ui_observer_cannot_replace_accepted_map_marker(tmp_path):
    from neusymnav.visualization.robot_overlay import RobotTrailBuffer
    clock=[1_000_000_000];buffer=RobotTrailBuffer()
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    p,_,_=pipeline(tmp_path,clock=lambda:clock[0],mapper=Mapper(),measurements=Observer())
    first=source(0,modality='depth_only');late=source(1,stamp=1_100_000_000,modality='depth_only')
    sensor=SimpleNamespace(capture_navigation=lambda:first,robot_pose=pose)
    try:
        launcher._capture_navigation(sensor,p,lambda obs:None,buffer.observe)
        wait_for(lambda:p._latest_nav is not None)
        accepted=p._latest_nav;clock[0]=late.capture_monotonic_ns
        sensor.capture_navigation=lambda:late
        def delayed(*args):
            buffer.observe(*args)
            clock[0]=late.capture_monotonic_ns+300_000_001
        assert launcher._capture_navigation(sensor,p,lambda obs:None,delayed) is None
        assert p._latest_nav is accepted
        track=buffer.for_nav(accepted)
        assert track is not None and track.samples[-1].source == first.key
    finally:assert p.close(3.)['clean_shutdown']
