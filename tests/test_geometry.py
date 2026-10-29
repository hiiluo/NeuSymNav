import importlib
import itertools
import math
import numpy as np
import pytest


def frames():
    return importlib.import_module('neusymnav.geometry.frames')


def test_y_up_to_z_up_known_points():
    f = frames()
    pose = np.eye(4)
    pose[:3, 3] = [0, 1, 0]
    changed = f.to_canonical_pose(pose, 'new_y_up_v1')
    np.testing.assert_allclose(changed[:3, 3], [0, 0, 1], atol=1e-8)
    pose[:3, 3] = [0, 0, 1]
    changed = f.to_canonical_pose(pose, 'new_y_up_v1')
    np.testing.assert_allclose(changed[:3, 3], [0, -1, 0], atol=1e-8)
    assert np.linalg.det(changed[:3, :3]) == pytest.approx(1)
    np.testing.assert_allclose(changed[:3, :3] @ [0, 0, 1], [0, -1, 0])
    with pytest.raises(ValueError):
        f.to_canonical_pose(pose, 'guessed')


def test_camera_optical_ray():
    p = importlib.import_module('neusymnav.geometry.projection')
    f = frames()
    k = np.array([[2., 0, 1], [0, 4., 2], [0, 0, 1.]])
    pose = np.eye(4)
    pose[:3, 3] = [10, 20, 30]
    np.testing.assert_allclose(p.project_pixel_to_world(3, 6, 2, k, pose), [12, 22, 32])
    # Habitat camera looks along local -Z; converting its basis is a RIGHT multiply.
    optical = f.habitat_to_optical_pose(pose)
    np.testing.assert_allclose(p.project_pixel_to_world(1, 2, 2, k, optical), [10, 20, 28])
    np.testing.assert_allclose(p.project_pixel_to_world(3, 6, 2, k, pose, depth_mode='range'),
                               [10 + 2 / math.sqrt(3), 20 + 2 / math.sqrt(3), 30 + 2 / math.sqrt(3)])
    with pytest.raises(ValueError):
        p.project_pixel_to_world(1, 2, 0, k, pose)


def test_bounds_and_covariance_roundtrip():
    f = frames()
    r = np.array([[1., 0, 0], [0, 0, -1], [0, 1, 0]])
    bounds = np.array([[-2., 1., 3.], [4., 5., 7.]])
    transformed = f.transform_bounds(bounds, r)
    np.testing.assert_allclose(transformed, [[-2., -7., 1.], [4., -3., 5.]], atol=1e-8)
    np.testing.assert_allclose(f.transform_bounds(transformed, r.T), bounds, atol=1e-8)
    angle = .37
    arbitrary = np.array([[math.cos(angle), -math.sin(angle), 0],
                          [math.sin(angle), math.cos(angle), 0], [0, 0, 1.]])
    enclosing = f.transform_bounds(bounds, arbitrary)
    corners = np.array(list(itertools.product(*zip(*bounds)))) @ arbitrary.T
    assert np.all(corners >= enclosing[0] - 1e-8)
    assert np.all(corners <= enclosing[1] + 1e-8)
    covariance = np.array([[2., .3, .4], [.3, 3., .7], [.4, .7, 4.]])
    converted = f.transform_covariance(covariance, r)
    np.testing.assert_allclose(converted, [[2., -.4, .3], [-.4, 4., -.7], [.3, -.7, 3.]])
    np.testing.assert_allclose(f.transform_covariance(converted, r.T), covariance, atol=1e-8)
    assert f.transform_heading(math.pi / 2, r, source_convention='new_y_up_v1') == pytest.approx(math.pi / 2)
    np.testing.assert_allclose(f.transform_vectors([[0, 1, 0]], r), [[0, 0, 1]])


@pytest.mark.parametrize('kind', ['reflection', 'scaled', 'bottom', 'nonfinite'])
def test_invalid_pose_rejected(kind):
    p = np.eye(4)
    if kind == 'reflection': p[0, 0] = -1
    if kind == 'scaled': p[0, 0] = 2
    if kind == 'bottom': p[3, 2] = 1
    if kind == 'nonfinite': p[0, 3] = np.nan
    with pytest.raises(ValueError):
        frames().to_canonical_pose(p, 'canonical_z_up_v1')


def test_unproject_depth_measured_samples_only():
    p = importlib.import_module('neusymnav.geometry.projection')
    depth = np.array([[1., np.nan], [0., 2.]], np.float32)
    valid = np.array([[True,False],[False,True]])
    np.testing.assert_allclose(p.unproject_depth(depth, valid, np.eye(3), np.eye(4)),
                               [[0.,0.,1.],[2.,2.,2.]])
    assert p.unproject_depth(depth, np.zeros((2,2),bool), np.eye(3),np.eye(4)).shape == (0,3)
    with pytest.raises(ValueError): p.unproject_depth(depth, np.ones((2,2),bool), np.eye(3),np.eye(4))


def test_covariance_invalid_and_roundtrip_general_pose():
    f = frames()
    with pytest.raises(ValueError): f.transform_covariance(np.diag([-1.,1.,1.]), np.eye(3))
    with pytest.raises(ValueError): f.transform_bounds(np.array([[1.,0.,0.],[0.,1.,1.]]), np.eye(3))
    pose = np.array([[0.,-1.,0.,2.],[1.,0.,0.,3.],[0.,0.,1.,4.],[0.,0.,0.,1.]])
    changed = f.to_canonical_pose(pose, 'new_y_up_v1')
    inverse_world = np.array([[1.,0.,0.,0.],[0.,0.,1.,0.],[0.,-1.,0.,0.],[0.,0.,0.,1.]])
    np.testing.assert_allclose(inverse_world @ changed, pose, atol=1e-8)
    np.testing.assert_allclose(changed[:3,3], [2.,-4.,3.], atol=1e-8)
