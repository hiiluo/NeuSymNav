from dataclasses import replace
from types import SimpleNamespace
import math
import numpy as np
import pytest
from neusymnav.contracts import NavSnapshot, FrameKey
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.navigation.viewpoints import CameraModel, ViewpointPlanner


def nav(states=None, origin=(0., 0.)):
    s = np.zeros((50, 50), dtype=np.int8) if states is None else states
    return NavSnapshot('ep', 1, FrameKey('ep', 'nav', 0), 100, 'clock', .1, origin,
                       s, np.ones(s.shape, bool), np.full(s.shape, 2., np.float32),
                       'robot', 0., 'floor', 'a'*64)


def camera(z=1., K=None, mount=None):
    # Optical x right, y down, z forward; body forward +x.
    T = np.eye(4); T[:3,:3] = [[0,0,1],[-1,0,0],[0,-1,0]]
    if mount is not None: T[:3,3] = mount
    return CameraModel(np.array([[100.,0,50],[0,100,50],[0,0,1]]) if K is None else K,
                       (100,100), T, z, 'cal')


def planner(cam=None, **kw):
    return ViewpointPlanner(RobotGeometry('robot', .1, 1., 0.), cam or camera(), **kw)


def plan(n=None, cam=None, target=(2.5,2.5,1.), **kw):
    return planner(cam).plan(n or nav(), (.55,.55), target, now_ns=100, clock_domain='clock', **kw)


def test_free_map_generates_bounded_deterministic_valid_paths():
    n=nav(); a=plan(n); b=plan(n)
    assert 0 < len(a.candidates) <= 12
    assert a == b
    assert all(c.path.valid_for(n) and c.predicted_visibility for c in a.candidates)


def test_stale_unknown_and_no_clearance_are_rejected():
    p=planner(); n=nav()
    assert p.plan(n,(.55,.55),(2.5,2.5,1.),now_ns=300_000_101,clock_domain='clock').reason == 'nav_stale'
    unknown=plan(nav(np.full((50,50),-1,np.int8)))
    assert not unknown.candidates and unknown.reason == 'unknown'
    assert not plan(replace(n,clearance=np.zeros_like(n.clearance))).candidates


def test_camera_model_owns_transform_and_fixed_body_pose():
    c=camera(mount=(.2,.1,.3)); T=np.eye(4); yaw=.7
    T[:3,:3]=[[math.cos(yaw),-math.sin(yaw),0],[math.sin(yaw),math.cos(yaw),0],[0,0,1]]
    T[:3,3]=[1,2,1]
    obs=SimpleNamespace(K=c.K,rgb=np.zeros((100,100,3)),T_world_camera=T@c.T_body_camera,calibration_id='cal')
    recovered=CameraModel.from_observation(obs,(1,2),yaw,1.)
    assert np.allclose(recovered.T_body_camera,c.T_body_camera)
    with pytest.raises(ValueError): recovered.K.setflags(write=True)
    with pytest.raises(ValueError): camera(mount=(float('nan'),0,0))


def test_vertical_fov_and_height_are_respected():
    assert plan(target=(2.5,2.5,1.)).candidates
    assert not plan(target=(2.5,2.5,5.)).candidates


def test_rolling_origin_keeps_world_coordinates():
    n=nav(); shifted=nav(origin=(-.1,0.)); shifted=replace(shifted,revision=2)
    a=plan(n); b=plan(shifted)
    assert a.candidates and b.candidates
    assert all(c.path.map_revision == 2 for c in b.candidates)
    assert all(0 <= c.world_xy[0] <= 5 for c in b.candidates)


def test_occlusion_unknown_and_unreachable_are_never_proposed():
    s=np.zeros((50,50),np.int8); s[23:28,23:28]=100
    result=plan(nav(s))
    assert not result.candidates and result.reason == 'occluded'
    s[23:28,23:28]=-1
    result=plan(nav(s))
    assert not result.candidates and result.reason == 'unknown'
    s=np.zeros((50,50),np.int8); s[4:8,4:8]=-1; s[5,5]=0
    assert not plan(nav(s)).candidates


def test_mount_offset_and_orientation_keep_target_in_optical_image():
    c=camera(mount=(.25,.2,.1)); result=plan(cam=c)
    assert result.candidates
    for candidate in result.candidates:
        yaw=candidate.yaw_rad; cs,sn=math.cos(yaw),math.sin(yaw)
        body=np.array([[cs,-sn,0,candidate.world_xy[0]],[sn,cs,0,candidate.world_xy[1]],
                       [0,0,1,c.body_z_m],[0,0,0,1.]])
        pose=body@c.T_body_camera
        p=pose[:3,:3].T@(np.array([2.5,2.5,1.])-pose[:3,3])
        uv=c.K@p; uv=uv[:2]/uv[2]
        assert p[2]>0 and 0<=uv[0]<100 and 0<=uv[1]<100


def test_diversity_and_path_are_ranked_deterministically():
    first=plan().candidates[0]
    yaw=first.yaw_rad; c=camera(); cs,sn=math.cos(yaw),math.sin(yaw)
    body=np.array([[cs,-sn,0,first.world_xy[0]],[sn,cs,0,first.world_xy[1]],
                   [0,0,1,1.],[0,0,0,1.]])
    evidence=SimpleNamespace(camera_pose_world=body@c.T_body_camera,object_centroid_world=np.array([2.5,2.5,1.]))
    result=plan(previous_views=(evidence,))
    assert result.candidates[0].diversity_angle_deg > 15
    assert result.candidates[-1].diversity_angle_deg < 1


def test_no_floor_support_and_clock_mismatch_are_rejected():
    n=nav()
    assert not plan(replace(n,floor_support=np.zeros_like(n.floor_support))).candidates
    assert planner().plan(n,(.55,.55),(2.5,2.5,1.),now_ns=100,clock_domain='other').reason == 'nav_clock_invalid'
