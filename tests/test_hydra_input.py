from dataclasses import replace

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import Detection, DetectionBatch
from neusymnav.contracts.hydra_graph import HydraCalibration
from neusymnav.backends.hydra.input_adapter import HydraInputAdapter

LABELSPACE = dict(labelspace_id='test:hydra-labelspace:v1', labelspace_hash='0' * 64)


def make_calibration(K):
    T_body_camera = np.eye(4)
    angle = np.pi / 2
    T_body_camera[:3, :3] = [[np.cos(angle), -np.sin(angle), 0.],
                             [np.sin(angle), np.cos(angle), 0.], [0., 0., 1.]]
    T_body_camera[:3, 3] = [.25, -.5, .1]
    return HydraCalibration('calibration:v1', 'camera-cal-v1', 'rgbd', 'primary_rgbd',
                            K, T_body_camera, 0, 'canonical_z_up_v1',
                            'optical_x_right_y_down_z_forward_v1', 'metric_axial_v1',
                            'simulator:calibration:v1')


def test_convert_uses_body_camera_transform_once_and_exports_wxyz():
    T_world_camera = np.eye(4)
    T_world_camera[:3, 3] = [2., 3., 4.]
    obs = observation(T_world_camera=T_world_camera)
    detection = Detection('d1', 'chair', 'chair', .8, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(obs, (detection,), vocabulary_id='taxonomy:v1')
    labels = np.full((2, 3), 7, np.int32)
    frame = HydraInputAdapter.convert(obs, batch, make_calibration(obs.K), labels,
                                      detector_profile_id='yoloe:v1', **LABELSPACE)
    expected_world_T_body = T_world_camera @ np.linalg.inv(make_calibration(obs.K).body_T_camera)
    np.testing.assert_allclose(frame.world_T_body, expected_world_T_body, atol=1e-12)
    np.testing.assert_allclose(frame.world_T_body @ frame.body_T_camera, T_world_camera, atol=1e-12)
    np.testing.assert_allclose(frame.world_t_body, expected_world_T_body[:3, 3], atol=1e-12)
    np.testing.assert_allclose(frame.world_R_body_wxyz,
        [np.sqrt(.5), 0., 0., -np.sqrt(.5)], atol=1e-12)
    assert frame.world_R_body_wxyz[0] > .7  # wxyz; xyzw would put zero here.
    np.testing.assert_array_equal(frame.labels, labels)
    assert frame.labels.dtype == np.int32


def test_static_calibration_remains_valid_after_simulator_pose_version_advances():
    initial = observation()
    calibration = make_calibration(initial.K)
    moved_pose = replace(initial, pose_version=1)
    detection = Detection('d1', 'chair', 'chair', .8, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(moved_pose, (detection,), vocabulary_id='taxonomy:v1')

    frame = HydraInputAdapter.convert(moved_pose, batch, calibration,
        np.zeros((2, 3), np.int32), detector_profile_id='yoloe:v1', **LABELSPACE)

    assert frame.pose_version == 1
    np.testing.assert_allclose(frame.world_T_body @ frame.body_T_camera,
        moved_pose.T_world_camera, atol=1e-12)


def test_convert_preserves_rgb_depth_units_and_invalid_as_nan_without_mutation():
    rgb = np.zeros((2, 3, 3), np.uint8)
    rgb[0, 0] = [255, 0, 0]
    depth = np.array([[2., np.nan, 0.], [np.inf, 1.5, 3.]], np.float32)
    valid = np.array([[True, False, False], [False, True, True]])
    obs = observation(rgb=rgb, depth_m=depth, valid_depth=valid)
    d = Detection('d1', 'chair', 'chair', .7, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(obs, (d,), vocabulary_id='taxonomy:v1')
    labels = np.zeros((2, 3), np.int32)
    frame = HydraInputAdapter.convert(obs, batch, make_calibration(obs.K), labels,
                                      detector_profile_id='yoloe:v1', **LABELSPACE)
    np.testing.assert_array_equal(frame.rgb[0, 0], [255, 0, 0])
    assert frame.depth_m[0, 0] == 2.0
    assert np.isnan(frame.depth_m[0, 1:]).all()
    assert np.isnan(frame.depth_m[1, 0])
    np.testing.assert_array_equal(obs.rgb[0, 0], [255, 0, 0])
    np.testing.assert_array_equal(obs.depth_m, depth)
    for arr in (frame.rgb, frame.depth_m, frame.labels, frame.world_T_body):
        with pytest.raises(ValueError): arr.setflags(write=True)


def test_convert_rejects_out_of_order_or_wrong_time_source_by_validation():
    obs = observation()
    d = Detection('d1', 'chair', 'chair', .7, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(obs, (d,), vocabulary_id='taxonomy:v1')
    frame = HydraInputAdapter.convert(obs, batch, make_calibration(obs.K), np.zeros((2, 3), np.int32),
                                      detector_profile_id='yoloe:v1', **LABELSPACE)
    with pytest.raises(ValueError): frame.validate_now(100, 'different-clock')
    with pytest.raises(ValueError): frame.validate_now(99, 'host:boot1')
