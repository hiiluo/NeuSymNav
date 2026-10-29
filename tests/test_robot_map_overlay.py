"""Source-bound robot overlays never fabricate poses, motion or visibility."""
from dataclasses import replace
import math
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import numpy as np
import pytest
from PyQt5 import QtWidgets
from neusymnav.contracts import FrameKey
from neusymnav.visualization.robot_overlay import RobotSample, CameraCone, RobotTrack, RobotTrailBuffer, MAX_TRAIL
from neusymnav.visualization.publisher import DisplaySources
from neusymnav.runtime.ui_transport import encode_publication, decode_publication
from contract_helpers import observation
from test_display_snapshot import make_publisher


def pair(i=1, stamp=100, episode='e', domain='clock', yaw=math.pi/2):
    t=np.eye(4);t[:3,:3]=[[0,0,1],[-1,0,0],[0,-1,0]]
    rgb=observation(key=FrameKey(episode,'rgb',i),capture_monotonic_ns=stamp-1,clock_domain=domain,T_world_camera=t)
    nav=observation(key=FrameKey(episode,'nav',i),capture_monotonic_ns=stamp,clock_domain=domain,modality='depth_only')
    pose=dict(source=nav.key,capture_monotonic_ns=stamp,clock_domain=domain,pose_version=nav.pose_version,
              robot_xy=(.5,.5),yaw_rad=yaw)
    return rgb,nav,pose


def nav_for(obs):
    nav=make_publisher()[4]
    return replace(nav,episode_id=obs.key.episode_id,source=obs.key,capture_monotonic_ns=obs.capture_monotonic_ns,clock_domain=obs.clock_domain)


def test_measured_body_and_actual_camera_calibration_are_independent():
    buffer=RobotTrailBuffer();rgb,nav,pose=pair();buffer.observe(rgb,nav,pose)
    track=buffer.for_nav(nav_for(nav))
    assert track.samples[-1].xy == (.5,.5)
    assert track.samples[-1].yaw_rad == math.pi/2
    cone=track.camera
    assert cone.source==rgb.key and cone.calibration_id==rgb.calibration_id
    # Optical forward is +X even though the body fixture faces +Y.
    assert abs(sum(cone.edge_yaws)/2)<.3
    assert cone.edge_yaws[0]>0 and cone.edge_yaws[1]<0
    assert buffer.for_nav(replace(nav_for(nav),capture_monotonic_ns=101)) is None


@pytest.mark.parametrize('field,value',[('source',FrameKey('wrong','nav',1)),('clock_domain','wrong'),
                                      ('capture_monotonic_ns',99),('pose_version',7),('robot_xy',(float('nan'),0))])
def test_mismatched_or_nonfinite_body_proof_rejected(field,value):
    rgb,nav,pose=pair();pose[field]=value
    with pytest.raises(ValueError):RobotTrailBuffer().observe(rgb,nav,pose)


def test_camera_version_mismatch_or_vertical_view_has_no_cone():
    for change in [dict(pose_version=9),dict(T_world_camera=np.eye(4))]:
        rgb,nav,pose=pair();rgb=replace(rgb,**change)
        buffer=RobotTrailBuffer();buffer.observe(rgb,nav,pose)
        assert buffer.for_nav(nav_for(nav)).camera is None


def test_ring_is_bounded_rejects_replay_resets_episode_and_never_waits_for_ui():
    buffer=RobotTrailBuffer()
    for i in range(MAX_TRAIL+3):buffer.observe(*pair(i,i+2))
    track=buffer.for_nav(nav_for(pair(MAX_TRAIL+2,MAX_TRAIL+4)[1]))
    assert len(track.samples)==MAX_TRAIL and track.truncated
    with pytest.raises(ValueError):buffer.observe(*pair(MAX_TRAIL+2,MAX_TRAIL+4))
    buffer.observe(*pair(0,5,episode='other'))
    assert len(buffer.for_nav(replace(nav_for(pair(0,5,episode='other')[1]),episode_id='other')).samples)==1
    buffer=RobotTrailBuffer();buffer._lock.acquire()
    try:buffer.observe(*pair())
    finally:buffer._lock.release()
    assert buffer.for_nav(nav_for(pair()[1])) is None


def envelope_with_track():
    publisher,hierarchy,metrics,objects,nav,_=make_publisher()
    sample=RobotSample(nav.source,nav.capture_monotonic_ns,nav.clock_domain,0,(.5,.5),0.)
    track=RobotTrack((sample,))
    metrics=dict(metrics,sources=replace(metrics['sources'],robot=track))
    publisher.publish(hierarchy,metrics)
    return publisher.read_latest()


def test_transport_roundtrip_and_pinned_map_binding():
    envelope=envelope_with_track()
    assert decode_publication(encode_publication(envelope)).sources.robot==envelope.sources.robot
    bad=replace(envelope.sources.robot.samples[-1],capture_monotonic_ns=999)
    with pytest.raises(ValueError,match='map source'):
        replace(envelope,sources=replace(envelope.sources,robot=RobotTrack((bad,))))


def test_old_wire_without_optional_robot_remains_readable():
    import json
    envelope=make_publisher()[0].read_latest();value=json.loads(encode_publication(envelope))
    sources=value['payload']['fields']['sources']['fields'];sources.pop('robot')
    assert decode_publication(json.dumps(value).encode()).sources.robot is None


def test_map_renders_heading_on_same_transform_as_raster_and_stale_is_explicit():
    from neusymnav.visualization.desktop import MapWidget
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    envelope=envelope_with_track();view=MapWidget();view.resize(450,450)
    view._now_ns=1_000_000_000;view._clock_domain=envelope.clock_domain
    view.set_snapshot(envelope.sources.nav,envelope);view.show();app.processEvents()
    p=view._world_to_pixel((.5,.5));up=view._world_to_pixel((.5,.6));right=view._world_to_pixel((.6,.5))
    assert up.y()<p.y() and right.x()>p.x()
    assert not view.grab().isNull()
    view.close()


def test_capture_observer_receives_existing_exact_pose_after_admission():
    from test_launcher_capture_pair import scenario
    from neusymnav.runtime.launcher import _capture_sensor_pair
    sensor,pipeline,raw,events,_,_,values=scenario()
    seen=[]
    def observe(*args):seen.append(args);assert events[-1]=='pair'
    _capture_sensor_pair(sensor,pipeline,raw,display_observer=observe)
    assert seen==[values] and events.count('pose')==1
