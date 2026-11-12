import json
import os
import subprocess
import sys
from dataclasses import replace

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import (Detection, DetectionBatch, FrameKey, dumps, loads,
                                 validate_hydra_frame_order)
from neusymnav.contracts.hydra_graph import HydraCalibration, HydraFrame

_LABELSPACE = dict(labelspace_id='test:hydra-labelspace:v1', labelspace_hash='0' * 64)


def calibration(**changes):
    values = dict(calibration_id='calibration:v1', version='camera-cal-v1',
                  sensor_id='rgbd', camera_name='primary_rgbd',
                  K=np.array([[2., 0., 1.], [0., 2., .5], [0., 0., 1.]]),
                  body_T_camera=np.eye(4), pose_version=0,
                  coordinate_convention='canonical_z_up_v1',
                  camera_convention='optical_x_right_y_down_z_forward_v1',
                  depth_convention='metric_axial_v1', provenance='simulator:calibration:v1')
    values.update(changes)
    return HydraCalibration(**values)


def test_hydra_calibration_validates_and_owns_its_matrices():
    k = np.array([[2., 0., 1.], [0., 2., .5], [0., 0., 1.]])
    c = calibration(K=k)
    k[:] = 99
    assert c.K[0, 0] == 2
    with pytest.raises(ValueError): c.K.setflags(write=True)
    with pytest.raises(ValueError): calibration(version='')
    with pytest.raises(ValueError): calibration(body_T_camera=np.diag([-1., 1., 1., 1.]))
    with pytest.raises(ValueError): calibration(camera_convention='habitat_xyz')
    with pytest.raises(ValueError): calibration(depth_convention='millimetres')


def test_hydra_frame_requires_source_provenance_and_explicit_time_domain():
    from neusymnav.backends.hydra.input_adapter import HydraInputAdapter
    obs = observation()
    det = Detection('chair-1', 'chair', 'chair', .9, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(obs, (det,), vocabulary_id='taxonomy:v1')
    frame = HydraInputAdapter.convert(obs, batch, calibration(), np.ones((2, 3), np.int32),
                                      detector_profile_id='yoloe:v1', **_LABELSPACE)
    assert frame.source_key == obs.key
    assert frame.capture_monotonic_ns == obs.capture_monotonic_ns
    assert frame.clock_domain == obs.clock_domain
    assert frame.calibration_hash == calibration().calibration_hash
    assert frame.validate_now(101, 'host:boot1') == 1
    with pytest.raises(ValueError): frame.validate_now(99, 'host:boot1')
    with pytest.raises(ValueError): frame.validate_now(101, 'other-boot')
    with pytest.raises(ValueError): replace(frame, capture_monotonic_ns=True)


def test_hydra_contracts_roundtrip_in_clean_import_order():
    from neusymnav.backends.hydra.input_adapter import HydraInputAdapter
    obs = observation()
    det = Detection('d1', 'chair', 'chair', .8, np.ones((2, 3), bool))
    frame = HydraInputAdapter.convert(obs, DetectionBatch.from_observation(
        obs, (det,), vocabulary_id='taxonomy:v1'), calibration(),
        np.zeros((2, 3), np.int32), detector_profile_id='detector:v1', **_LABELSPACE)
    payload = dumps(frame)
    assert isinstance(loads(payload), HydraFrame)
    env = dict(os.environ)
    proc = subprocess.run([sys.executable, '-c',
        'import sys; from neusymnav.contracts.serialization import loads; '
        'from neusymnav.contracts.hydra_graph import HydraFrame; '
        'value=loads(sys.stdin.read()); assert isinstance(value, HydraFrame); print(type(value).__name__)'],
        input=payload, text=True, capture_output=True, env=env, check=True)
    assert proc.stdout.strip() == 'HydraFrame'
    wire = json.loads(payload)
    wire['payload']['fields']['unrecognized'] = 1
    with pytest.raises(ValueError): loads(json.dumps(wire))


def test_hydra_frame_rejects_inconsistent_calibration_source_or_shapes():
    from neusymnav.backends.hydra.input_adapter import HydraInputAdapter
    obs = observation()
    det = Detection('d1', 'chair', 'chair', .8, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(obs, (det,), vocabulary_id='taxonomy:v1')
    with pytest.raises(ValueError, match='calibration'):
        HydraInputAdapter.convert(obs, batch, calibration(calibration_id='other'),
                                  np.zeros((2, 3), np.int32), detector_profile_id='detector:v1', **_LABELSPACE)
    with pytest.raises(ValueError, match='mask'):
        bad = replace(batch, detections=(replace(det, mask=np.ones((3, 2), bool)),))
        HydraInputAdapter.convert(obs, bad, calibration(), np.zeros((2, 3), np.int32),
                                  detector_profile_id='detector:v1', **_LABELSPACE)
    with pytest.raises(ValueError, match='source'):
        other = replace(obs, key=FrameKey('episode', 'other-sensor', 0))
        HydraInputAdapter.convert(other, batch, calibration(sensor_id='other-sensor'),
                                  np.zeros((2, 3), np.int32), detector_profile_id='detector:v1', **_LABELSPACE)
    with pytest.raises(ValueError, match='primary rgbd'):
        depth_only = replace(obs, modality='depth_only')
        HydraInputAdapter.convert(depth_only, batch, calibration(), np.zeros((2, 3), np.int32),
                                  detector_profile_id='detector:v1', **_LABELSPACE)


def test_hydra_frame_order_rejects_duplicate_replay_and_clock_reordering():
    from neusymnav.backends.hydra.input_adapter import HydraInputAdapter
    obs = observation()
    d = Detection('d1', 'chair', 'chair', .8, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(obs, (d,), vocabulary_id='taxonomy:v1')
    first = HydraInputAdapter.convert(obs, batch, calibration(), np.zeros((2, 3), np.int32),
                                      detector_profile_id='detector:v1', **_LABELSPACE)
    next_obs = replace(obs, key=FrameKey('episode', 'rgbd', 2), capture_monotonic_ns=102)
    next_batch = DetectionBatch.from_observation(next_obs, (d,), vocabulary_id='taxonomy:v1')
    later = HydraInputAdapter.convert(next_obs, next_batch, calibration(), np.zeros((2, 3), np.int32),
                                      detector_profile_id='detector:v1', **_LABELSPACE)
    validate_hydra_frame_order(first, later)  # gaps are allowed for live latest-wins.
    with pytest.raises(ValueError, match='strictly increasing'):
        validate_hydra_frame_order(first, first)
    older_obs = replace(obs, key=FrameKey('episode', 'rgbd', 1), capture_monotonic_ns=99)
    older = HydraInputAdapter.convert(older_obs, DetectionBatch.from_observation(
        older_obs, (d,), vocabulary_id='taxonomy:v1'), calibration(),
        np.zeros((2, 3), np.int32), detector_profile_id='detector:v1', **_LABELSPACE)
    with pytest.raises(ValueError, match='strictly increasing'):
        validate_hydra_frame_order(later, older)
    wrong_episode = HydraInputAdapter.convert(
        replace(obs, key=FrameKey('another-episode', 'rgbd', 1), capture_monotonic_ns=103),
        DetectionBatch.from_observation(replace(obs, key=FrameKey('another-episode', 'rgbd', 1),
            capture_monotonic_ns=103), (d,), vocabulary_id='taxonomy:v1'), calibration(),
        np.zeros((2, 3), np.int32), detector_profile_id='detector:v1', **_LABELSPACE)
    with pytest.raises(ValueError, match='episode/sensor'):
        validate_hydra_frame_order(first, wrong_episode)
