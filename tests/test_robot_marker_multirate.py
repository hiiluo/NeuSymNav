"""Every admitted depth map needs its own measured body overlay."""
from types import SimpleNamespace
from neusymnav.runtime.launcher import _capture_sensor_pair, _capture_navigation
from neusymnav.visualization.robot_overlay import RobotTrailBuffer
from test_robot_map_overlay import pair, nav_for


def test_rgb_then_depth_only_captures_keep_exact_robot_marker_at_map_admission():
    buffer=RobotTrailBuffer();current=[pair(0,100)]
    def admitted(nav,pose):
        track=buffer.for_nav(nav_for(nav))
        assert track is not None, 'new map became visible without its measured robot marker'
        assert track.samples[-1].source==nav.key
        assert track.samples[-1].xy==pose['robot_xy']
    sensor=SimpleNamespace(capture=lambda:current[0][0],capture_navigation=lambda:current[0][1],robot_pose=lambda nav:current[0][2])
    pipeline=SimpleNamespace(measurements=None,submit_sensor_pair=lambda rgb,nav,pose:admitted(nav,pose),submit_navigation=admitted)
    _capture_sensor_pair(sensor,pipeline,lambda obs:None,display_observer=buffer.observe)
    for i in range(1,7):
        current[0]=pair(i,100+i)
        _capture_navigation(sensor,pipeline,lambda obs:None,display_observer=buffer.observe)
    track=buffer.for_nav(nav_for(current[0][1]))
    assert len(track.samples)==7 and track.camera is not None
    assert track.camera.calibration_source==pair(0,100)[0].key


def test_depth_only_body_has_no_fabricated_rgb_camera_cone():
    buffer=RobotTrailBuffer();rgb,nav,pose=pair()
    buffer.observe(None,nav,pose)
    track=buffer.for_nav(nav_for(nav))
    assert track is not None and track.camera is None
    assert track.samples[-1].capture_monotonic_ns==nav.capture_monotonic_ns
