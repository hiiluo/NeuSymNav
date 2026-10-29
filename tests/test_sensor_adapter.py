"""P02 calibrated Habitat boundary and independently launched process tests."""
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.contracts.observations import require_rgbd
from neusymnav.sensors.client import HabitatPoseSource, observation_from_packet
from neusymnav.sensors.habitat_worker import (normalize_capture, encode_packet,
                                               sensor_pose, intrinsics_from_projection)


def sample(modality='rgbd'):
    return normalize_capture(
        rgb=np.arange(18, dtype=np.uint8).reshape(2, 3, 3) if modality == 'rgbd' else None,
        depth=np.array([[1., 0., 10.], [2., np.nan, 3.]], np.float32),
        K=np.array([[2., 0., 1.], [0., 2., .5], [0., 0., 1.]]),
        T_world_habitat=np.array([[1., 0., 0., 1.], [0., 1., 0., 4.],
                                  [0., 0., 1., 3.], [0., 0., 0., 1.]]),
        episode_id='episode', sensor_id='primary' if modality == 'rgbd' else 'downward',
        frame_index=0, capture_monotonic_ns=123, clock_domain='host_monotonic:boot',
        sim_time_s=.2, calibration_id='calibration:actual', pose_version=0,
        modality=modality, depth_min_m=.1, depth_max_m=10.)


def test_world_left_camera_right_and_nonzero_floor():
    obs = observation_from_packet(encode_packet(sample()))
    # Old translation (1,4,3) -> canonical (1,-3,4); optical forward becomes +Y.
    np.testing.assert_array_equal(obs.T_world_camera[:3, 3], [1., -3., 4.])
    np.testing.assert_array_equal(obs.T_world_camera[:3, 2], [0., 1., 0.])
    np.testing.assert_array_equal(obs.T_world_camera[:3, 1], [0., 0., -1.])
    np.testing.assert_array_equal(obs.valid_depth, [[True, False, False], [True, False, True]])
    assert obs.far_plane is None  # no free-space certificates invented at clip plane
    assert obs.capture_monotonic_ns == 123


def test_secondary_depth_has_own_K_pose_modality_and_no_detector():
    capture = sample('depth_only')
    capture['arrays']['K'][0, 0] = 7.
    # Rx(-pi/2) turns the Habitat forward ray straight downward in old Y-up.
    capture = normalize_capture(
        **{k: v for k, v in capture['metadata'].items() if k not in ('coordinate_convention', 'depth_convention')},
        rgb=None, depth=capture['arrays']['depth_m'], K=capture['arrays']['K'],
        T_world_habitat=np.array([[1., 0., 0., 1.], [0., 0., 1., 5.],
                                  [0., -1., 0., 3.], [0., 0., 0., 1.]]),
        depth_min_m=.1, depth_max_m=10.)
    obs = observation_from_packet(encode_packet(capture))
    assert obs.modality == 'depth_only'
    assert obs.key.sensor_id == 'downward'
    assert obs.K[0, 0] == 7.
    np.testing.assert_array_equal(obs.T_world_camera[:3, 2], [0., 0., -1.])
    np.testing.assert_array_equal(obs.T_world_camera[:3, 3], [1., -3., 5.])
    assert not obs.rgb.any()
    with pytest.raises(ValueError, match='primary rgbd'):
        require_rgbd(obs)


def test_intrinsics_use_actual_projection_and_sensor_extrinsics():
    projection = np.diag([2., 3., -1., 1.])
    np.testing.assert_array_equal(intrinsics_from_projection(projection, 8, 6),
                                  [[8., 0., 3.5], [0., 9., 2.5], [0., 0., 1.]])
    state = SimpleNamespace(position=[2., 4., -1.],
                            rotation=SimpleNamespace(x=0., y=0., z=0., w=1.))
    np.testing.assert_array_equal(sensor_pose(state)[:3, 3], [2., 4., -1.])


def test_wire_checksum_rejects_changed_payload_and_semantic_fields():
    packet = encode_packet(sample())
    packet['arrays_b64'] = base64.b64encode(b'broken').decode()
    with pytest.raises(ValueError, match='checksum'):
        observation_from_packet(packet)
    capture = sample()
    capture['metadata']['semantic'] = [1, 2]
    with pytest.raises(ValueError, match='fields'):
        observation_from_packet(encode_packet(capture))


def test_independent_worker_process_protocol_and_shutdown(tmp_path):
    # Only the external simulator is substituted: exercise real process IO,
    # checksummed worker codec, host Observation construction, and close.
    capture = sample()
    packet = encode_packet(capture)
    worker = tmp_path / 'external.py'
    worker.write_text('import sys,json\n'
                      f'p=json.loads({json.dumps(json.dumps(packet))})\n'
                      'print(json.dumps({"ready":True,"wire_version":1}),flush=True)\n'
                      'for line in sys.stdin:\n'
                      ' r=json.loads(line)\n'
                      ' if r["op"]=="close": break\n'
                      ' print(json.dumps({"ok":True,"packet":p}),flush=True)\n')
    source = HabitatPoseSource(python=sys.executable, config={}, worker_script=worker, timeout_s=2)
    try:
        assert source.capture().key.sensor_id == 'primary'
        with pytest.raises(ValueError, match='duplicate|nonmonotonic'):
            source.capture()  # old sensor samples cannot be republished as fresh
    finally:
        source.close()
    assert source.process.poll() is not None


def test_native_entrypoint_fails_cleanly_without_scene(tmp_path):
    script = Path(__file__).parents[1] / 'src/neusymnav/sensors/habitat_worker.py'
    config = tmp_path / 'config.json'
    config.write_text('{}')
    result = subprocess.run([sys.executable, str(script), '--config', str(config)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    data = json.loads(result.stdout.splitlines()[-1])
    assert data['ready'] is False
    assert data['error']


def test_numpy_header_cannot_request_unbounded_allocation():
    from neusymnav.sensors.habitat_worker import _checksum
    import zipfile
    # Checksums alone do not make a NumPy header safe to allocate.
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name in ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera'):
            arr = io.BytesIO()
            np.lib.format.write_array_header_1_0(arr, dict(descr='<f8', fortran_order=False,
                                                          shape=(2**40,)))
            archive.writestr(name + '.npy', arr.getvalue())
    payload = stream.getvalue()
    packet = encode_packet(sample())
    packet['arrays_b64'] = base64.b64encode(payload).decode()
    packet['sha256'] = _checksum(packet['metadata'], payload)
    with pytest.raises(ValueError, match='size|bound|header'):
        observation_from_packet(packet)


def test_timeout_closes_worker_and_drops_late_response(tmp_path):
    worker = tmp_path / 'stalled.py'
    worker.write_text('import json,sys,time\n'
                      'print(json.dumps({"ready":True,"wire_version":1}),flush=True)\n'
                      'for line in sys.stdin:\n'
                      ' time.sleep(10)\n')
    source = HabitatPoseSource(python=sys.executable, config={}, worker_script=worker, timeout_s=.05)
    with pytest.raises(TimeoutError):
        source.capture()
    assert source.process.poll() is not None
    with pytest.raises(RuntimeError, match='closed'):
        source.capture()


def test_worker_capture_uses_actual_sensors_without_gt_or_navmesh(monkeypatch):
    import types
    from neusymnav.sensors.habitat_worker import HabitatCapture
    # Native dependency boundary only: execute real configuration, sensor
    # lookup, K extraction, alignment, conversion, encoding and episode logic.
    native = types.ModuleType('habitat_sim')
    native.SimulatorConfiguration = SimpleNamespace
    native.CameraSensorSpec = SimpleNamespace
    native.AgentState = SimpleNamespace
    native.SensorType = SimpleNamespace(COLOR='color', DEPTH='depth')
    native.SensorSubType = SimpleNamespace(PINHOLE='pinhole')
    native.agent = SimpleNamespace(AgentConfiguration=lambda: SimpleNamespace(action_space={'move_forward': 1}))
    native.Configuration = lambda simulator, agents: (simulator, agents)
    optical = SimpleNamespace(position=[1., 4., 3.], rotation=[0., 0., 0., 1.])
    downward = SimpleNamespace(position=[2., 5., 6.], rotation=np.array([[1., 0., 0.],
                                              [0., 0., 1.], [0., -1., 0.]]))
    class Sim:
        def __init__(self, config):
            self._sensors = {name: SimpleNamespace(_sensor_object=SimpleNamespace(
                render_camera=SimpleNamespace(projection_matrix=np.diag([f, f, -1., 1.]))),
                draw_observation=lambda:None, get_observation=lambda name=name: self.get_sensor_observations()[name])
                for name, f in [('rgb', 2.), ('depth', 2.), ('nav', 4.)]}
            self.agent = SimpleNamespace(agent_config=config[1][0], set_state=lambda *a, **k: None,
                get_state=lambda: SimpleNamespace(sensor_states={'rgb': optical, 'depth': optical, 'nav': downward},
                                                  position=[0., 0., 0.], rotation=[0., 0., 0., 1.]))
        def get_agent(self, i): return self.agent
        def get_sensor_observations(self):
            return {'rgb': np.ones((2, 3, 4), np.uint8), 'depth': np.ones((2, 3), np.float32),
                    'nav': np.full((2, 3), 2., np.float32)}
        def get_world_time(self): return 4.
        def step(self, action): pass
        def reset(self): pass
        def close(self): pass
        @property
        def pathfinder(self): raise AssertionError('navmesh GT must not be queried')
        @property
        def semantic_scene(self): raise AssertionError('semantic GT must not be queried')
    native.Simulator = Sim
    utils, common = types.ModuleType('habitat_sim.utils'), types.ModuleType('habitat_sim.utils.common')
    common.quat_from_coeffs = lambda value: value
    monkeypatch.setitem(sys.modules, 'habitat_sim', native)
    monkeypatch.setitem(sys.modules, 'habitat_sim.utils', utils)
    monkeypatch.setitem(sys.modules, 'habitat_sim.utils.common', common)
    spec = dict(sensor_id='primary', rgb_uuid='rgb', depth_uuid='depth', resolution_hw=[2, 3],
                position_xyz=[0., 1., 0.], orientation_xyz_rad=[0., 0., 0.], hfov_deg=90.,
                depth_min_m=.1, depth_max_m=10.)
    config = dict(scene_id='explicit-scene', episode_id='episode', initial_position=[1., 4., 3.],
                  initial_rotation_xyzw=[0., 0., 0., 1.], primary=spec,
                  navigation=dict(spec, sensor_id='downward', depth_uuid='nav',
                                  orientation_xyz_rad=[-np.pi/2, 0., 0.]))
    capture = HabitatCapture(config)
    try:
        primary = observation_from_packet(capture.capture('primary'))
        nav = observation_from_packet(capture.capture('navigation'))
        assert primary.K[0, 0] == 3.  # actual projection, not config HFOV focal=1.5
        assert nav.K[0, 0] == 6.
        assert primary.calibration_id != nav.calibration_id
        np.testing.assert_array_equal(nav.T_world_camera[:3, 3], [2., -6., 5.])
        assert nav.modality == 'depth_only'
        capture.step('move_forward')
        assert observation_from_packet(capture.capture('primary')).pose_version == 1
        capture.reset('next', [0., 1., 2.], [0., 0., 0., 1.])
        reset = observation_from_packet(capture.capture('primary'))
        assert reset.key.episode_id == 'next'
        assert reset.key.frame_index == 0
        with pytest.raises(ValueError, match='unused'):
            capture.reset('episode', [0., 1., 2.], [0., 0., 0., 1.])
    finally:
        capture.close()
