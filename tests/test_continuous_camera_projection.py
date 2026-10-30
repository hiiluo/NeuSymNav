"""FOV persists through depth-only poses without borrowing old RGB timestamps."""
from dataclasses import replace
import math
import pytest
from neusymnav.visualization.robot_overlay import RobotTrailBuffer
from test_robot_map_overlay import pair,nav_for


def test_depth_only_pose_projects_calibrated_camera_mount_after_translation_and_turn():
    b=RobotTrailBuffer();rgb,nav,pose=pair(0,100,yaw=0.)
    b.observe(rgb,nav,pose);initial=b.for_nav(nav_for(nav)).camera
    assert initial is not None
    _,next_nav,next_pose=pair(1,200,yaw=math.pi/2)
    next_nav=replace(next_nav,pose_version=1)
    next_pose=dict(next_pose,pose_version=1,robot_xy=(2.,3.))
    b.observe(None,next_nav,next_pose)
    cone=b.for_nav(nav_for(next_nav)).camera
    assert cone is not None, 'FOV disappeared on the next depth-only capture'
    assert cone.source==next_nav.key and cone.capture_monotonic_ns==200 and cone.pose_version==1
    assert cone.calibration_source==rgb.key and cone.calibration_capture_monotonic_ns==99
    assert cone.xy==pytest.approx((2.5,2.5))
    assert cone.edge_yaws==pytest.approx(tuple(a+math.pi/2 for a in initial.edge_yaws))


def test_no_projection_before_calibration_or_across_episode_or_clock():
    b=RobotTrailBuffer();rgb,nav,pose=pair(0,100)
    b.observe(None,nav,pose);assert b.for_nav(nav_for(nav)).camera is None
    rgb,nav,pose=pair(1,200);b.observe(rgb,nav,pose)
    for episode,domain in [('other','clock'),('other','new-clock')]:
        _,nav,pose=pair(0,300,episode=episode,domain=domain)
        b.observe(None,nav,pose);assert b.for_nav(nav_for(nav)).camera is None


def test_projected_camera_transport_preserves_current_pose_and_calibration_sources():
    from neusymnav.visualization.robot_overlay import CameraProjection
    from neusymnav.runtime.ui_transport import encode_publication,decode_publication
    from neusymnav.contracts import FrameKey
    from test_robot_map_overlay import envelope_with_track
    envelope=envelope_with_track();sample=envelope.sources.robot.samples[-1]
    c=CameraProjection(sample.source,sample.capture_monotonic_ns,sample.clock_domain,sample.pose_version,
        'calibration',sample.xy,(0.,1.),FrameKey(sample.source.episode_id,'rgb',0),0,sample.clock_domain,0)
    e=replace(envelope,sources=replace(envelope.sources,robot=replace(envelope.sources.robot,camera=c)))
    assert decode_publication(encode_publication(e)).sources.robot.camera==c
    for delta in [dict(calibration_source=FrameKey('other','rgb',0)),dict(calibration_clock_domain='other'),
                  dict(calibration_capture_monotonic_ns=sample.capture_monotonic_ns+1),dict(calibration_pose_version=sample.pose_version+1)]:
        with pytest.raises(ValueError):replace(c,**delta)
