"""Standalone Python 3.9+ Habitat worker, deliberately independent of the host ABI.

Run this FILE using the configured sensor interpreter, not ``python -m`` (the
host package requires Python 3.12). Imports are stdlib/NumPy until native launch.
JSON-lines + checksummed NPZ (no pickle) carries only measured RGB/depth,
calibration, source timing and simulator-ground-truth pose. Never query scene
semantics. Simulator collision filtering is used only for actuation; it never
supplies map evidence. All simulator calls run serially here.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import numpy as np

WIRE_VERSION = 1
MAX_WIRE_BYTES = 64 * 1024**2
_ARRAY_NAMES = ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera')


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _checksum(metadata, payload):
    return hashlib.sha256(_canonical(metadata) + b'\0' + payload).hexdigest()


def host_clock_domain():
    # Stable across worker restarts within a host boot. No random per-worker
    # fallback: domains with unknown comparability must fail closed.
    boot = Path('/proc/sys/kernel/random/boot_id').read_text(encoding='ascii').strip()
    if not boot:
        raise RuntimeError('host boot ID unavailable')
    return 'host_monotonic:' + boot


def _rotation(rotation):
    if hasattr(rotation, 'to_matrix'):
        matrix = np.asarray(rotation.to_matrix(), dtype=np.float64)
    elif all(hasattr(rotation, name) for name in ('x', 'y', 'z', 'w')):
        values = np.array([rotation.x, rotation.y, rotation.z, rotation.w], np.float64)
        matrix = _quaternion_matrix(values)
    elif hasattr(rotation, 'real') and np.asarray(rotation.imag).shape == (3,):
        matrix = _quaternion_matrix(np.r_[rotation.imag, rotation.real])
    else:
        values = np.asarray(rotation, np.float64)
        matrix = _quaternion_matrix(values) if values.shape == (4,) else values
    if (matrix.shape != (3, 3) or not np.isfinite(matrix).all()
            or not np.allclose(matrix.T @ matrix, np.eye(3), rtol=0, atol=1e-8)
            or not np.isclose(np.linalg.det(matrix), 1, rtol=0, atol=1e-8)):
        raise ValueError('sensor rotation must be a right-handed orthonormal matrix')
    return matrix


def _quaternion_matrix(values):
    if not np.isfinite(values).all() or values.shape != (4,) or np.linalg.norm(values) == 0:
        raise ValueError('invalid xyzw sensor quaternion')
    x, y, z, w = values / np.linalg.norm(values)
    return np.array([[1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
                     [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
                     [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)]], np.float64)


def sensor_pose(state):
    """Read actual world sensor state; never substitute the agent body pose."""
    position = np.asarray(state.position, np.float64)
    if position.shape != (3,) or not np.isfinite(position).all():
        raise ValueError('sensor position must be finite xyz')
    result = np.eye(4, dtype=np.float64)
    result[:3, :3], result[:3, 3] = _rotation(state.rotation), position
    return result


def wrap_yaw(angle):
    return (angle + math.pi) % (2 * math.pi) - math.pi


def canonical_robot_pose(state):
    """Body -Z forward, source +Y up -> canonical XY/yaw; no camera shortcut."""
    source_pose = sensor_pose(state)
    rotation = np.array([[1., 0., 0.], [0., 0., -1.], [0., 1., 0.]])
    position = rotation @ source_pose[:3, 3]
    forward = rotation @ (-source_pose[:3, 2])
    if np.linalg.norm(forward[:2]) < 1e-8:
        raise ValueError('robot forward axis has no planar heading')
    return dict(robot_xy=(float(position[0]), float(position[1])),
                yaw_rad=math.atan2(forward[1], forward[0]))


class _NativeYawMath:
    """Read-only float32 Magnum prediction for a qualified local body action."""
    def __init__(self, magnum, action_supported, agent_supported=lambda agent: True):
        self.mn = magnum
        self.action_supported = action_supported
        self.agent_supported = agent_supported

    def components(self, agent, state):
        node = agent.scene_node
        parent = node.parent
        if parent is None:
            return None
        transform = np.asarray(parent.absolute_transformation(), dtype=np.float64)
        if (transform.shape != (4, 4) or not np.isfinite(transform).all() or
                not np.array_equal(transform[:3, :3], np.eye(3)) or
                not np.array_equal(transform[3], [0., 0., 0., 1.])):
            return None
        native = node.rotation
        if type(native) is not self.mn.Quaternion:
            return None
        vector = np.asarray(native.vector)
        values = np.r_[vector, float(native.scalar)].astype(np.float64)
        if (vector.dtype != np.float32 or vector.shape != (3,) or
                not np.isfinite(values).all() or abs(np.linalg.norm(values)-1.) > 1e-5 or
                not np.allclose(_rotation(state.rotation), _quaternion_matrix(values), rtol=0, atol=1e-8)):
            return None
        return values

    def predict(self, values, action, amount):
        mn = self.mn
        before = mn.Quaternion(values[:3], float(values[3]))
        direction = 1 if action == 'turn_left' else -1
        delta = mn.Quaternion.rotation(mn.Rad(mn.Deg(direction*amount)), mn.Vector3.y_axis())
        if np.array_equal(np.asarray(delta.vector), np.zeros(3)) and float(delta.scalar) == 1.:
            raise ValueError('native yaw increment underflowed to identity')
        after = (before*delta).normalized()
        values_after = np.r_[np.asarray(after.vector), float(after.scalar)].astype(np.float64)
        # Use the same canonical conversion of the represented quaternion that
        # the real post-step proof uses, not a requested or ideal angle.
        yaw = canonical_robot_pose(SimpleNamespace(position=np.zeros(3), rotation=values_after))['yaw_rad']
        if not np.isfinite(values_after).all():
            raise ValueError('nonfinite native yaw prediction')
        return values_after, yaw

    def prepare(self, agent, state, action, requested):
        try:
            if (action not in ('turn_left', 'turn_right') or type(requested) not in (int, float) or
                    not math.isfinite(requested) or not 0 < requested <= 3. or
                    not self.action_supported(action) or not self.agent_supported(agent)):
                return None
            values = self.components(agent, state)
            if values is None:
                return None
            before = canonical_robot_pose(state)['yaw_rad']
            amount = np.float32(requested)
            if float(amount) > requested:
                amount = np.nextafter(amount, np.float32(-math.inf))
            for _ in range(32):
                candidate = float(amount)
                if not 0 < candidate <= requested:
                    return None
                predicted, yaw = self.predict(values, action, candidate)
                delta = math.remainder(yaw-before, 2*math.pi)
                direction = 1 if action == 'turn_left' else -1
                if direction*delta > 0 and abs(delta) <= math.radians(candidate)+1e-7:
                    return candidate, (predicted, yaw)
                amount = np.nextafter(amount, np.float32(-math.inf))
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            # No supported prediction is never permission to use an old path.
            return None
        return None

    def matches(self, agent, state, expected):
        actual = self.components(agent, state)
        return (actual is not None and np.array_equal(actual, expected[0]) and
                abs(wrap_yaw(canonical_robot_pose(state)['yaw_rad']-expected[1])) <= 1e-8)


class _NativePlanarMath:
    """Qualified upright native body, with a fixed source-Y simulation plane."""
    def __init__(self, magnum, agent_supported, action_supported):
        self.body_math = _NativeYawMath(magnum, None, agent_supported)
        self.agent_supported, self.action_supported = agent_supported, action_supported

    def valid(self, agent, state, anchor):
        try:
            if not self.agent_supported(agent) or not self.action_supported():
                return False
            if self.body_math.components(agent, state) is None:
                return False
            position = np.asarray(state.position, dtype=np.float64)
            rotation = _rotation(state.rotation)
            node = agent.scene_node
            world_position = np.asarray(node.absolute_translation, dtype=np.float64)
            local = np.asarray(node.transformation, dtype=np.float64)
            native_rotation = np.asarray(node.rotation.to_matrix(), dtype=np.float64)
            return bool(position.shape == (3,) and np.isfinite(position).all() and
                abs(position[1]-anchor) <= 1e-7 and
                np.array_equal(rotation[:, 1], [0., 1., 0.]) and
                world_position.shape == (3,) and np.isfinite(world_position).all() and
                np.allclose(world_position, position, rtol=0, atol=1e-8) and
                local.shape == (4, 4) and np.isfinite(local).all() and
                np.array_equal(local[3], [0., 0., 0., 1.]) and
                native_rotation.shape == (3, 3) and np.isfinite(native_rotation).all() and
                np.array_equal(local[:3, :3], native_rotation))
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            return False

    def prepare_translation(self, agent, amount):
        """Select a bounded smaller native move under the issued upper bound.

        ObjectControls translates first, then adds (filter_end-world_end) in
        parent coordinates. A translated identity-linear parent still rounds
        the world/local additions separately; never assume filter_end is the
        actual final body endpoint. Prediction performs only qualified native
        float math, never a trial action, collision query or pose mutation.
        """
        try:
            if type(amount) not in (int, float) or not math.isfinite(amount) or amount <= 0:
                return None
            state = agent.get_state()
            position = np.asarray(state.position, dtype=np.float64)
            if position.shape != (3,) or not self.valid(agent, state, float(position[1])):
                return None
            before = canonical_robot_pose(state)
            mn = self.body_math.mn
            node = agent.scene_node
            parent = node.parent.absolute_transformation()
            if (type(parent) is not mn.Matrix4 or type(node.translation) is not mn.Vector3 or
                    type(node.absolute_translation) is not mn.Vector3):
                return None
            start = mn.Vector3(node.absolute_translation)
            local = mn.Vector3(node.translation)
            axis = mn.Vector3(np.asarray(node.transformation)[:3, 2])
            for step in range(32, 0, -1):
                chosen = amount * (step / 32.)
                if not 0 < chosen <= amount:
                    continue
                local_end = local + axis*(-chosen)
                end = parent.transform_point(local_end)
                rollback = parent.transform_point(local_end + (start-end))
                predicted = parent.transform_point(local_end + (mn.Vector3(end)-end))
                after = np.asarray(predicted, dtype=np.float64)
                if (after.shape != (3,) or not np.isfinite(after).all() or
                        after[1] != position[1] or
                        np.array_equal(after[[0, 2]], np.asarray(start)[[0, 2]]) or
                        not np.array_equal(rollback, start)):
                    continue
                after_xy = (float(after[0]), -float(after[2]))
                dx, dy = after_xy[0]-before['robot_xy'][0], after_xy[1]-before['robot_xy'][1]
                yaw = before['yaw_rad']
                forward = dx*math.cos(yaw) + dy*math.sin(yaw)
                lateral = -dx*math.sin(yaw) + dy*math.cos(yaw)
                if (math.dist(before['robot_xy'], after_xy) <= chosen+1e-7 and
                        forward >= -1e-7 and abs(lateral) <= 1e-7):
                    return dict(start=start, end=end, local_end=local_end,
                        parent=np.asarray(parent).copy(), amount=chosen)
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            pass
        return None

    def corrected_endpoint(self, agent, start, end, point, prepared):
        try:
            mn = self.body_math.mn
            node = agent.scene_node
            parent = node.parent.absolute_transformation()
            if (not np.array_equal(start, prepared['start']) or
                    not np.array_equal(end, prepared['end']) or
                    not np.array_equal(node.translation, prepared['local_end']) or
                    not np.array_equal(np.asarray(parent), prepared['parent'])):
                return None
            return np.asarray(parent.transform_point(mn.Vector3(node.translation) +
                (point-mn.Vector3(end))), dtype=np.float64)
        except (AttributeError, TypeError, ValueError, OverflowError, RuntimeError):
            return None


def _qualified_native_planar(habitat_sim):
    """Qualify translation independently of yaw prediction, once at startup."""
    try:
        import magnum as mn
        from habitat_sim.agent import agent
        from habitat_sim.agent.controls import default_controls, object_controls
        from habitat_sim.registry import registry
        pins = ((default_controls.__file__, 'b3b1b86f5c1b04e7201fbfe1f31bdc1001993253526a530984a2f01c079b4f42'),
                (agent.__file__, '7e23e19aa33f48670eefdabbd8b0736058bc4336df6863f7d7dcfd7451da65fe'),
                (object_controls.__file__, 'ff80413f7368209ab1bb58dcd37d46602739f0f51b9b2e58b140b2da7aa6ce8b'))
        if getattr(habitat_sim, '__version__', None) != '0.3.3':
            return None
        for path, digest in pins:
            with Path(path).open('rb') as handle:
                content = handle.read(131073)
            if len(content) > 131072 or hashlib.sha256(content).hexdigest() != digest:
                return None
        controls_type = object_controls.ObjectControls
        act, get_state, controls_action = agent.Agent.act, agent.Agent.get_state, controls_type.action
        forward, move = default_controls.MoveForward.__call__, default_controls._move_along
        translate_local, translate = habitat_sim.SceneNode.translate_local, habitat_sim.SceneNode.translate
        math_types = tuple((name, getattr(mn, name)) for name in ('Vector3', 'Matrix4', 'Quaternion'))
        math_apis = tuple((owner, name, getattr(owner, name)) for owner, name in (
            (mn.Vector3, '__add__'), (mn.Vector3, '__sub__'), (mn.Vector3, '__mul__'),
            (mn.Matrix4, 'transform_point'), (mn.Quaternion, 'to_matrix'),
            (habitat_sim.SceneNode, 'absolute_transformation'),
            (habitat_sim.SceneNode, 'translation'), (habitat_sim.SceneNode, 'absolute_translation'),
            (habitat_sim.SceneNode, 'transformation')))
        def agent_supported(value):
            return (type(value) is agent.Agent and type(value.controls) is controls_type and
                getattr(value.act, '__func__', None) is act and
                getattr(value.get_state, '__func__', None) is get_state and
                getattr(value.controls.action, '__func__', None) is controls_action)
        def action_supported():
            return (type(registry.get_move_fn('move_forward')) is default_controls.MoveForward and
                registry.get_move_fn('move_forward').body_action is True and
                default_controls.MoveForward.__call__ is forward and
                default_controls._move_along is move and
                habitat_sim.SceneNode.translate_local is translate_local and
                habitat_sim.SceneNode.translate is translate and
                all(getattr(mn, name) is native_type for name, native_type in math_types) and
                all(getattr(owner, name) is method for owner, name, method in math_apis))
        return _NativePlanarMath(mn, agent_supported, action_supported)
    except (ImportError, OSError, AttributeError, TypeError, ValueError, RuntimeError):
        return None


def _qualified_native_yaw(habitat_sim):
    """Qualify once at startup; unsupported ABIs still permit sensor capture."""
    try:
        import magnum as mn
        from habitat_sim.agent import agent
        from habitat_sim.agent.controls import default_controls
        from habitat_sim.agent.controls import object_controls
        ObjectControls = object_controls.ObjectControls
        from habitat_sim.registry import registry
        pins = ((default_controls.__file__, 'b3b1b86f5c1b04e7201fbfe1f31bdc1001993253526a530984a2f01c079b4f42'),
                (agent.__file__, '7e23e19aa33f48670eefdabbd8b0736058bc4336df6863f7d7dcfd7451da65fe'),
                (object_controls.__file__, 'ff80413f7368209ab1bb58dcd37d46602739f0f51b9b2e58b140b2da7aa6ce8b'))
        def source_matches(path, digest):
            with Path(path).open('rb') as handle:
                content = handle.read(131073)
            return len(content) <= 131072 and hashlib.sha256(content).hexdigest() == digest
        if (getattr(habitat_sim, '__version__', None) != '0.3.3' or
                any(not source_matches(path, digest) for path, digest in pins)):
            return None
        supported = {'turn_left': default_controls.LookLeft, 'turn_right': default_controls.LookRight}
        methods = {name: cls.__call__ for name, cls in supported.items()}
        rotate = default_controls._rotate_local
        native_rotate = habitat_sim.SceneNode.rotate_y_local
        agent_act, agent_state = agent.Agent.act, agent.Agent.get_state
        controls_action = ObjectControls.action
        def agent_supported(value):
            return (type(value) is agent.Agent and type(value.controls) is ObjectControls and
                    getattr(value.act, '__func__', None) is agent_act and
                    getattr(value.get_state, '__func__', None) is agent_state and
                    getattr(value.controls.action, '__func__', None) is controls_action)
        def action_supported(name):
            return (type(registry.get_move_fn(name)) is supported[name] and
                    registry.get_move_fn(name).body_action is True and
                    supported[name].__call__ is methods[name] and
                    default_controls._rotate_local is rotate and
                    default_controls._rotate_local_fns[1] is native_rotate)
        result = _NativeYawMath(mn, action_supported, agent_supported)
        # Exact component witnesses from the bounded actual 0.3.3 run qualify
        # degree conversion, multiplication order and normalization together.
        cases = [([0., -.8467497825622559, 0., -.5319913625717163], 2.9920852199999994,
                  [0., -.8325719237327576, 0., -.5539169311523438]),
                 ([0., -.6415769457817078, 0., -.7670587301254272], 2.9919087899999997,
                  [0., -.621333122253418, 0., -.7835465669631958])]
        if any(not np.array_equal(result.predict(np.asarray(q), 'turn_right', amount)[0], expected)
               for q, amount, expected in cases):
            return None
        return result
    except (ImportError, OSError, AttributeError, TypeError, ValueError, RuntimeError):
        return None


def intrinsics_from_projection(projection, width, height):
    """Pixel-centre pinhole K from the actual symmetric GL render projection.

    Pixel integer centres have principal point ((W-1)/2,(H-1)/2). Reject
    off-axis/sheared projections rather than silently applying a guessed HFOV.
    """
    p = np.asarray(projection, np.float64)
    if (p.shape != (4, 4) or not np.isfinite(p).all() or width <= 0 or height <= 0
            or p[0, 0] <= 0 or p[1, 1] <= 0
            or not np.allclose(p[[0, 0, 1, 1], [1, 2, 0, 2]], 0, rtol=0, atol=1e-8)):
        raise ValueError('unsupported actual camera projection')
    return np.array([[p[0, 0]*width/2., 0., (width-1)/2.],
                     [0., p[1, 1]*height/2., (height-1)/2.], [0., 0., 1.]], np.float64)


def normalize_capture(*, rgb, depth, K, T_world_habitat, episode_id, sensor_id,
                      frame_index, capture_monotonic_ns, clock_domain, sim_time_s,
                      calibration_id, pose_version, modality, depth_min_m, depth_max_m):
    """Pure geometry seam, with separate left-world and right-camera changes."""
    if modality not in ('rgbd', 'depth_only'):
        raise ValueError('invalid modality')
    if not math.isfinite(depth_min_m) or not math.isfinite(depth_max_m) or not 0 < depth_min_m < depth_max_m:
        raise ValueError('invalid measured depth bounds')
    depth = np.asarray(depth)
    if depth.ndim != 2 or 0 in depth.shape or depth.dtype.kind != 'f':
        raise ValueError('depth must be floating HxW metric axial depth')
    depth = depth.astype(np.float32, copy=True)
    if modality == 'depth_only':
        if rgb is not None:
            raise ValueError('depth_only capture cannot carry unrelated RGB')
        color = np.zeros((*depth.shape, 3), np.uint8)
    else:
        color = np.asarray(rgb)
        if color.shape not in ((*depth.shape, 3), (*depth.shape, 4)) or color.dtype != np.uint8:
            raise ValueError('aligned RGB must be uint8 HxWx3|4')
        color = color[..., :3].copy()
    pose = np.asarray(T_world_habitat, np.float64)
    if (pose.shape != (4, 4) or not np.isfinite(pose).all()
            or not np.allclose(pose[3], [0., 0., 0., 1.], rtol=0, atol=1e-8)):
        raise ValueError('invalid homogeneous sensor pose')
    _rotation(pose[:3, :3])
    world = np.array([[1., 0., 0., 0.], [0., 0., -1., 0.],
                      [0., 1., 0., 0.], [0., 0., 0., 1.]], np.float64)
    optical = np.diag([1., -1., -1., 1.])
    k = np.asarray(K, np.float64)
    if (k.shape != (3, 3) or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0
            or not np.allclose(k[2], [0., 0., 1.], rtol=0, atol=1e-8)):
        raise ValueError('invalid intrinsics')
    metadata = dict(episode_id=episode_id, sensor_id=sensor_id, frame_index=frame_index,
                    capture_monotonic_ns=capture_monotonic_ns, clock_domain=clock_domain,
                    sim_time_s=sim_time_s, calibration_id=calibration_id, pose_version=pose_version,
                    modality=modality, coordinate_convention='canonical_z_up_v1',
                    depth_convention='metric_axial_v1')
    arrays = dict(rgb=color, depth_m=depth,
                  valid_depth=np.isfinite(depth) & (depth >= depth_min_m) & (depth < depth_max_m),
                  K=k.copy(), T_world_camera=world @ pose @ optical)
    return dict(metadata=metadata, arrays=arrays)


def encode_packet(capture):
    buffer = io.BytesIO()
    np.savez(buffer, **capture['arrays'])
    payload = buffer.getvalue()
    result = dict(wire_version=WIRE_VERSION, metadata=capture['metadata'],
                  arrays_b64=base64.b64encode(payload).decode('ascii'),
                  sha256=_checksum(capture['metadata'], payload))
    if len(_canonical(result)) > MAX_WIRE_BYTES:
        raise ValueError('capture exceeds bounded wire packet capacity')
    return result


class HabitatCapture:
    """Real Habitat-Sim adapter, constructed only in the native interpreter.

    Config supplies exact scene/initial pose and distinct primary/navigation
    sensor specs. Runtime K and world extrinsics are read back from sensors.
    No random navigable spawn, semantic sensor, or navmesh seeding is used.
    """
    def __init__(self, config):
        self.config = config
        self.execution_ack = None
        if 'seed' in config and (type(config['seed']) is not int or not 0 <= config['seed'] <= 2**32 - 1):
            raise ValueError('sensor seed must be a uint32 integer')
        for key in ('scene_id', 'episode_id', 'initial_position', 'initial_rotation_xyzw', 'primary', 'navigation'):
            if key not in config:
                raise ValueError('missing sensor config field: ' + key)
        if not isinstance(config['episode_id'], str) or not config['episode_id']:
            raise ValueError('episode_id must be nonempty')
        self._motion_adapter = config.get('motion_adapter', 'strict_3d')
        if type(self._motion_adapter) is not str or self._motion_adapter not in ('strict_3d', 'planar_fixed_y_v1'):
            raise ValueError('unknown motion_adapter')
        initial = np.asarray(config['initial_position'], dtype=np.float64)
        if initial.shape != (3,) or not np.isfinite(initial).all():
            raise ValueError('initial position must be finite source-world xyz')
        self._planar_anchor_y = float(initial[1])
        import habitat_sim
        from habitat_sim.utils.common import quat_from_coeffs
        self.habitat_sim, self.quat_from_coeffs = habitat_sim, quat_from_coeffs
        self.clock_domain = host_clock_domain()
        simulator = habitat_sim.SimulatorConfiguration()
        simulator.scene_id = str(config['scene_id'])
        simulator.enable_physics = False
        simulator.gpu_device_id = int(config.get('gpu_device_id', 0))
        if config.get('scene_dataset_config_file'):
            simulator.scene_dataset_config_file = str(config['scene_dataset_config_file'])
        agent_config = habitat_sim.agent.AgentConfiguration()
        specs = []
        self.specs = {}
        primary, navigation = config['primary'], config['navigation']
        if primary['sensor_id'] == navigation['sensor_id']:
            raise ValueError('primary and navigation source IDs must differ')
        ids = []
        for lane, specification, color in [('primary', primary, True), ('navigation', navigation, False)]:
            for kind in (('rgb', 'depth') if color else ('depth',)):
                spec = habitat_sim.CameraSensorSpec()
                spec.uuid = specification[kind + '_uuid']
                ids.append(spec.uuid)
                spec.sensor_type = habitat_sim.SensorType.COLOR if kind == 'rgb' else habitat_sim.SensorType.DEPTH
                spec.sensor_subtype = habitat_sim.SensorSubType.PINHOLE
                spec.resolution = list(specification['resolution_hw'])
                spec.position = list(specification['position_xyz'])
                spec.orientation = list(specification['orientation_xyz_rad'])
                spec.hfov = float(specification['hfov_deg'])
                spec.near, spec.far = float(specification['depth_min_m']), float(specification['depth_max_m'])
                if kind == 'depth':
                    spec.normalize_depth = False
                self.specs[spec.uuid] = spec
                specs.append(spec)
        if len(ids) != len(set(ids)):
            raise ValueError('all native sensor UUIDs must be distinct')
        agent_config.sensor_specifications = specs
        self.sim = habitat_sim.Simulator(habitat_sim.Configuration(simulator, [agent_config]))
        try:
            if 'seed' in config:
                # This ACK exists only after the actual native API succeeds.
                # Apply before agent pose initialization or the first capture.
                self.sim.seed(config['seed'])
                self.execution_ack = dict(schema_version=1, episode_id=config['episode_id'],
                    clock_domain=self.clock_domain, seed=config['seed'],
                    seed_method='habitat_sim.Simulator.seed', seed_applied=True,
                    config_sha256=hashlib.sha256(_canonical(config)).hexdigest(),
                    runtime_version=str(getattr(habitat_sim, '__version__', 'unavailable')))
            self.agent = self.sim.get_agent(0)
            self.episode_id = config['episode_id']
            self._episodes = {self.episode_id}
            self.indices = {'primary': 0, 'navigation': 0}
            self.pose_version = 0
            self._navigation_state = None
            self._last_map_revision = -1
            self._set_pose(config['initial_position'], config['initial_rotation_xyzw'])
            self._yaw_math = _qualified_native_yaw(habitat_sim)
            self._planar_math = _qualified_native_planar(habitat_sim) if self._motion_adapter == 'planar_fixed_y_v1' else None
            self._planar_initial_valid = (self._planar_math is not None and
                self._planar_math.valid(self.agent, self.agent.get_state(), self._planar_anchor_y))
        except Exception:
            self.sim.close()
            raise

    def _set_pose(self, position, rotation):
        state = self.habitat_sim.AgentState()
        position, rotation = np.asarray(position, np.float64), np.asarray(rotation, np.float64)
        if position.shape != (3,) or not np.isfinite(position).all():
            raise ValueError('initial position must be finite source-world xyz')
        _quaternion_matrix(rotation)
        state.position = position
        state.rotation = self.quat_from_coeffs(rotation / np.linalg.norm(rotation))
        self.agent.set_state(state, reset_sensors=True)

    def _K(self, uuid, shape):
        sensor = self.sim._sensors[uuid]
        native = getattr(sensor, '_sensor_object', sensor)
        projection = native.render_camera.projection_matrix
        return intrinsics_from_projection(projection, shape[1], shape[0])

    def capture(self, lane):
        spec = self.config[lane]
        # Habitat's get_sensor_observations draws and reads EVERY configured
        # sensor. The owner already serializes capture/action transactions, so
        # draw only this lane, then read those same render targets. Never read a
        # cached target from a different lane and label it a new capture.
        uuids = (spec['rgb_uuid'], spec['depth_uuid']) if lane == 'primary' else (spec['depth_uuid'],)
        sensors = {uuid: self.sim._sensors[uuid] for uuid in uuids}
        for sensor in sensors.values():
            sensor.draw_observation()
        raw = {uuid: sensor.get_observation() for uuid, sensor in sensors.items()}
        capture_ns = time.monotonic_ns()
        state = self.agent.get_state()
        depth_uuid = spec['depth_uuid']
        depth = np.asarray(raw[depth_uuid])
        K = self._K(depth_uuid, depth.shape)
        T = sensor_pose(state.sensor_states[depth_uuid])
        rgb = None
        if lane == 'primary':
            rgb_uuid = spec['rgb_uuid']
            rgb = raw[rgb_uuid]
            if (not np.allclose(sensor_pose(state.sensor_states[rgb_uuid]), T, atol=1e-6, rtol=0)
                    or not np.allclose(self._K(rgb_uuid, depth.shape), K, atol=1e-8, rtol=0)):
                raise ValueError('primary RGB/depth extrinsics or intrinsics are not aligned')
        # Hash actual K, local calibration and configured depth semantics. World
        # pose stays per-capture, so moving the agent does not change calibration.
        local_extrinsic = np.linalg.inv(sensor_pose(state)) @ T
        calibration = dict(K=K.tolist(), T_agent_sensor=local_extrinsic.tolist(),
                           configuration=spec, depth_convention='metric_axial_v1',
                           source_world='new_y_up_v1', camera_basis='habitat_gl_v1',
                           calibration_method='actual_render_projection_and_sensor_state_v1')
        calibration_id = 'habitat:' + hashlib.sha256(_canonical(calibration)).hexdigest()
        packet = normalize_capture(
            rgb=rgb, depth=depth, K=K, T_world_habitat=T,
            episode_id=self.episode_id, sensor_id=spec['sensor_id'], frame_index=self.indices[lane],
            capture_monotonic_ns=capture_ns, clock_domain=self.clock_domain,
            sim_time_s=float(self.sim.get_world_time()), calibration_id=calibration_id,
            pose_version=self.pose_version, modality='rgbd' if lane == 'primary' else 'depth_only',
            depth_min_m=float(spec['depth_min_m']), depth_max_m=float(spec['depth_max_m']))
        if lane == 'navigation' and not np.allclose(packet['arrays']['T_world_camera'][:3, 2],
                                                    [0., 0., -1.], rtol=0, atol=1e-6):
            raise ValueError('navigation camera optical axis is not calibrated downward')
        self.indices[lane] += 1
        # Agent pose and sensor samples share this exact capture transaction.
        # A camera can be offset and downward; it is never the robot body pose.
        if lane == 'navigation':
            pose = canonical_robot_pose(state)
            self._navigation_state = dict(packet['metadata'], **pose)
            if getattr(self, '_motion_adapter', 'strict_3d') == 'planar_fixed_y_v1':
                self._navigation_state.update(body_source_xyz=tuple(float(v) for v in state.position),
                    body_source_up=tuple(float(v) for v in _rotation(state.rotation)[:, 1]))
        return encode_packet(packet)

    def step(self, action):
        if getattr(self, '_motion_adapter', 'strict_3d') == 'planar_fixed_y_v1':
            raise ValueError('planar adapter requires source-bound execute')
        if action not in self.agent.agent_config.action_space:
            raise ValueError('unknown simulator action')
        self._navigation_state = None
        self.last_actuation_proof = None
        self.sim.step(action)
        self.pose_version += 1

    def robot_pose(self):
        if self._navigation_state is None:
            raise ValueError('fresh navigation capture required for robot pose')
        state = self._navigation_state
        return dict(source={name: state[name] for name in ('episode_id', 'sensor_id', 'frame_index')},
                    capture_monotonic_ns=state['capture_monotonic_ns'],
                    clock_domain=state['clock_domain'], pose_version=state['pose_version'],
                    robot_xy=list(state['robot_xy']), yaw_rad=state['yaw_rad'])

    def execute(self, command, pose_version):
        """One-use, deadline-checked measured-source pulse, never a default step.

        With simultaneous v/w, translate on the certified initial tangent first,
        then rotate in place, each using half the time budget. This trajectory
        stays inside P03's forward capsule (a circular robot footprint). Native
        movement is Habitat's body action with its simulator collision filter.
        """
        self.last_actuation_proof = None
        state, self._navigation_state = self._navigation_state, None
        result = dict(executed=False, reason='stopped', actions=[], displacement_m=0., yaw_rad=0.)
        names = {'source', 'map_revision', 'issued_monotonic_ns', 'deadline_monotonic_ns',
                 'clock_domain', 'linear_mps', 'yaw_radps', 'reason', 'source_capture_monotonic_ns'}
        if not isinstance(command, dict) or set(command) != names:
            raise ValueError('invalid MotionCommand fields')
        key = command['source']
        if (not isinstance(key, dict) or set(key) != {'episode_id', 'sensor_id', 'frame_index'}
                or type(key['frame_index']) is not int or key['frame_index'] < 0):
            raise ValueError('invalid command source')
        for name in ('map_revision', 'issued_monotonic_ns', 'deadline_monotonic_ns', 'source_capture_monotonic_ns'):
            if type(command[name]) is not int or command[name] < 0:
                raise ValueError('invalid command integer: ' + name)
        if type(pose_version) is not int or pose_version < 0:
            raise ValueError('invalid pose version')
        for name in ('linear_mps', 'yaw_radps'):
            if type(command[name]) not in (int, float) or not math.isfinite(command[name]):
                raise ValueError('invalid motion velocity')
        if not isinstance(command['reason'], str) or not command['reason']:
            raise ValueError('missing command reason')
        now = time.monotonic_ns()
        issued, deadline = command['issued_monotonic_ns'], command['deadline_monotonic_ns']
        capture = command['source_capture_monotonic_ns']
        if command['clock_domain'] != self.clock_domain or self.clock_domain != host_clock_domain():
            result['reason'] = 'clock_domain_mismatch'
            return result
        if not capture <= issued <= now or deadline < issued:
            result['reason'] = 'future_or_invalid_command'
            return result
        if now >= deadline or (command['linear_mps'] == 0 and command['yaw_radps'] == 0):
            result['reason'] = 'expired_or_zero'
            return result
        if (state is None or key != {n: state[n] for n in ('episode_id', 'sensor_id', 'frame_index')}
                or capture != state['capture_monotonic_ns'] or state['pose_version'] != pose_version
                or pose_version != self.pose_version or key['episode_id'] != self.episode_id):
            result['reason'] = 'source_replayed_or_mismatched'
            return result
        if now - capture > 300_000_000 or command['map_revision'] < self._last_map_revision:
            result['reason'] = 'stale_source_or_map_revision'
            return result
        # The caller cannot extend the exact source's safety lifetime. Keep
        # this same deadline for preparation, both pulse budgets and every step.
        deadline = min(deadline, state['capture_monotonic_ns'] + 300_000_000)
        v, w = command['linear_mps'], command['yaw_radps']
        if not 0 <= v <= .2 or abs(w) > math.radians(30.):
            result['reason'] = 'motion_limits_exceeded'
            return result
        # The simulator owns contact/navmesh filtering. Never query navigability
        # to seed NavMap, and never set_state to enact a candidate displacement.
        move_filter = getattr(self.sim, 'step_filter', None)
        controls = getattr(self.agent, 'controls', None)
        if not callable(move_filter) or controls is None:
            raise RuntimeError('simulator collision filter unavailable; actuation blocked')
        native_act = getattr(self.agent, 'act', None)
        step_physics = getattr(self.sim, 'step_physics', None)
        if not callable(native_act) or not callable(step_physics):
            raise RuntimeError('public native action/physics API unavailable; actuation blocked')
        planar = getattr(self, '_motion_adapter', 'strict_3d') == 'planar_fixed_y_v1'
        planar_math = getattr(self, '_planar_math', None)
        anchor = getattr(self, '_planar_anchor_y', None)
        if planar:
            source_xyz = np.asarray(state.get('body_source_xyz'), dtype=np.float64)
            source_up = np.asarray(state.get('body_source_up'), dtype=np.float64)
            planar_body = self.agent.get_state()
            if (not getattr(self, '_planar_initial_valid', False) or planar_math is None or
                    source_xyz.shape != (3,) or not np.isfinite(source_xyz).all() or
                    source_up.shape != (3,) or not np.isfinite(source_up).all() or
                    not np.array_equal(source_up, [0., 1., 0.]) or
                    abs(source_xyz[1]-anchor) > 1e-7 or
                    not planar_math.valid(self.agent, planar_body, anchor) or
                    float(planar_body.position[1]) != source_xyz[1]):
                result['reason'] = 'planar_adapter_unavailable'
                return result
        planar_translation, expected_translation = None, None
        def segment_filter(start, end):
            nonlocal expected_translation
            # Habitat may offer sliding. Accept only points on the certified
            # initial forward segment; a sideways slide is not map evidence.
            start_array, end_array = np.asarray(start,dtype=np.float64), np.asarray(end,dtype=np.float64)
            filtered = move_filter(start, end)
            candidate = np.asarray(filtered, dtype=np.float64)
            if planar:
                if (start_array.shape != (3,) or end_array.shape != (3,) or candidate.shape != (3,) or
                        not np.isfinite(start_array).all() or not np.isfinite(end_array).all() or
                        not np.isfinite(candidate).all() or abs(start_array[1]-anchor) > 1e-7 or
                        abs(end_array[1]-anchor) > 1e-7 or abs(end_array[1]-start_array[1]) > 1e-7 or
                        abs(candidate[1]-anchor) > .05):
                    return start
                delta = end_array[[0, 2]] - start_array[[0, 2]]
                length2 = float(delta @ delta)
                if not math.isfinite(length2) or length2 <= 0:
                    return start
                offset = candidate[[0, 2]] - start_array[[0, 2]]
                fraction = float(offset @ delta / length2)
                projected = start_array[[0, 2]] + max(0., min(1., fraction)) * delta
                if not 0 < fraction <= 1 or np.linalg.norm(candidate[[0, 2]]-projected) > 1e-7:
                    return start
                point = planar_math.body_math.mn.Vector3([candidate[0], start_array[1], candidate[2]])
                represented = np.asarray(point, dtype=np.float64)
                fraction = float((represented[[0, 2]]-start_array[[0, 2]]) @ delta / length2)
                projected = start_array[[0, 2]] + max(0., min(1., fraction)) * delta
                if (represented.shape != (3,) or not np.isfinite(represented).all() or
                        represented[1] != start_array[1] or not 0 < fraction <= 1 or
                        np.linalg.norm(represented[[0, 2]]-projected) > 1e-7):
                    return start
                predicted = planar_math.corrected_endpoint(self.agent, start, end, point, planar_translation)
                if predicted is None or predicted.shape != (3,) or not np.isfinite(predicted).all():
                    return start
                # Keep both the native certified segment and the host proof's
                # canonical heading predicates: native float32 endpoints need
                # not be collinear with the double heading, even when the
                # contact filter returns its unchanged requested endpoint.
                fraction = float((predicted[[0, 2]]-start_array[[0, 2]]) @ delta / length2)
                projected = start_array[[0, 2]] + max(0., min(1., fraction)) * delta
                after_xy = (float(predicted[0]), -float(predicted[2]))
                dx, dy = after_xy[0]-step_before['robot_xy'][0], after_xy[1]-step_before['robot_xy'][1]
                yaw = step_before['yaw_rad']
                forward = dx*math.cos(yaw) + dy*math.sin(yaw)
                lateral = -dx*math.sin(yaw) + dy*math.cos(yaw)
                if (predicted[1] != step_y or not 0 < fraction <= 1 or
                        np.linalg.norm(predicted[[0, 2]]-projected) > 1e-7 or
                        math.dist(step_before['robot_xy'], after_xy) > amount+1e-7 or
                        forward < -1e-7 or abs(lateral) > 1e-7):
                    return start
                expected_translation = predicted
                return point
            delta = end_array - start_array
            length2 = float(delta @ delta)
            if candidate.shape != (3,) or not np.isfinite(candidate).all() or length2 <= 0:
                return start
            fraction = float((candidate - start_array) @ delta / length2)
            projected = start_array + max(0., min(1., fraction)) * delta
            if not 0 <= fraction <= 1 or np.linalg.norm(candidate - projected) > 1e-7:
                return start
            return filtered
        controls.move_filter_fn = segment_filter
        proof_actions = []
        # Prepare digest/source metadata before the final per-step TTL gate.
        proof_source = None
        if state.get('calibration_id'):
            proof_source = dict(schema_version='runtime_measurement_source_v1',
                key={n: state[n] for n in ('episode_id','sensor_id','frame_index')},
                capture_monotonic_ns=state['capture_monotonic_ns'],clock_domain=state['clock_domain'],
                pose_version=state['pose_version'],calibration_id=state['calibration_id'])
        command_digest = hashlib.sha256(_canonical(command)).hexdigest()
        before = canonical_robot_pose(self.agent.get_state())
        if (not np.allclose(before['robot_xy'], state['robot_xy'], rtol=0, atol=1e-8)
                or abs(wrap_yaw(before['yaw_rad'] - state['yaw_rad'])) > 1e-8):
            raise RuntimeError('agent pose changed after source capture')
        self._last_map_revision = command['map_revision']
        operations = [('move_forward', v)] if v else []
        if w:
            operations.append(('turn_left' if w > 0 else 'turn_right', abs(w)))
        budget = min((deadline - now) / 1e9, .1)
        for action, speed in operations:
            # Configure ONLY a private action, never the default 0.25m/10deg.
            # Construction can take time: check again immediately before step.
            remaining = (deadline - time.monotonic_ns()) / 1e9
            duration = min(budget / len(operations), remaining)
            if duration <= 0:
                result['reason'] = 'expired_before_step'
                break
            amount = speed * duration
            if action != 'move_forward':
                amount = math.degrees(amount)
            private = '__neusymnav_guarded_pulse__'
            self.agent.agent_config.action_space[private] = self.habitat_sim.agent.ActionSpec(
                action, self.habitat_sim.agent.ActuationSpec(amount=amount))
            remaining = (deadline - time.monotonic_ns()) / 1e9
            if remaining <= 0:
                result['reason'] = 'expired_before_step'
                break
            # Shrink after configuration so IPC/native preparation latency is
            # included in the certified remaining deadline.
            amount = min(amount, speed * remaining * (1 if action == 'move_forward' else 180 / math.pi))
            # Body measurement setup is deliberately before the last gate.
            body_before = self.agent.get_state()
            step_before = canonical_robot_pose(body_before)
            step_y = float(body_before.position[1]) if planar else None
            if planar and (step_y != source_xyz[1] or not planar_math.valid(self.agent, body_before, anchor)):
                result['reason'] = 'planar_adapter_unavailable'
                break
            planar_translation, expected_translation = None, None
            if planar and action == 'move_forward':
                planar_translation = planar_math.prepare_translation(self.agent, amount)
                if planar_translation is None:
                    result['reason'] = 'planar_translation_unavailable'
                    break
                amount = planar_translation['amount']
                expected_translation = np.asarray(planar_translation['start'], dtype=np.float64)
            expected_yaw = None
            if action != 'move_forward':
                yaw_math = getattr(self, '_yaw_math', None)
                selected = None if yaw_math is None else yaw_math.prepare(self.agent, body_before, action, amount)
                if selected is None:
                    result['reason'] = 'yaw_preflight_unavailable'
                    break
                amount, expected_yaw = selected
            # Chosen amount is final: no shrink/mutation after prediction.
            self.agent.agent_config.action_space[private].actuation.amount = amount
            if ((expected_yaw is not None or planar_translation is not None) and
                    self.agent.agent_config.action_space[private].actuation.amount != amount):
                raise RuntimeError('native guarded amount changed after prediction')
            version_before = self.pose_version
            pre_step_ns = time.monotonic_ns()
            if pre_step_ns >= deadline:
                result['reason'] = 'expired_before_step'
                break
            # Simulator.step also renders every sensor. Its public action and
            # physics APIs preserve body collision filtering and the same
            # 1/60 s world step; explicit capture reads current agent/sensor
            # state and world time without Simulator's private last-state cache.
            native_act(private)
            step_physics(1. / 60.)
            post_step_ns = time.monotonic_ns()
            self.pose_version += 1
            body_after = self.agent.get_state()
            step_after = canonical_robot_pose(body_after)
            if planar and (float(body_after.position[1]) != step_y or not planar_math.valid(self.agent, body_after, anchor)):
                raise RuntimeError('native planar body/height changed')
            if expected_translation is not None and not np.array_equal(body_after.position, expected_translation):
                raise RuntimeError('native planar translation prediction mismatch')
            if expected_yaw is not None and not yaw_math.matches(self.agent, body_after, expected_yaw):
                raise RuntimeError('native yaw prediction mismatch')
            proof_actions.append(dict(index=len(proof_actions),action=action,amount=amount,
                pre_step_monotonic_ns=pre_step_ns,post_step_monotonic_ns=post_step_ns,
                pose_version_before=version_before,pose_version_after=self.pose_version,
                body_before_xy=list(step_before['robot_xy']),body_after_xy=list(step_after['robot_xy']),
                yaw_before_rad=step_before['yaw_rad'],yaw_after_rad=step_after['yaw_rad']))
            result['actions'].append(dict(action=action, amount=amount))
            result['executed'], result['reason'] = True, 'executed'
        after = canonical_robot_pose(self.agent.get_state())
        result['displacement_m'] = math.dist(before['robot_xy'], after['robot_xy'])
        result['yaw_rad'] = wrap_yaw(after['yaw_rad'] - before['yaw_rad'])
        if result['displacement_m'] > v * budget + 1e-7 or abs(result['yaw_rad']) > abs(w) * budget + 1e-7:
            raise RuntimeError('simulator exceeded guarded action bounds')
        if proof_source is not None:
            self.last_actuation_proof = dict(schema_version=1,command_sha256=command_digest,source=proof_source,
                map_revision=command['map_revision'],source_pose_version=pose_version,
                actions=proof_actions,complete=True,reason=result['reason'])
        return result

    def reset(self, episode_id, position, rotation_xyzw):
        self.last_actuation_proof = None
        if not isinstance(episode_id, str) or not episode_id or episode_id in self._episodes:
            raise ValueError('reset needs a new, unused episode_id')
        if getattr(self, '_motion_adapter', 'strict_3d') == 'planar_fixed_y_v1':
            target = np.asarray(position, dtype=np.float64)
            rotation = _quaternion_matrix(np.asarray(rotation_xyzw, dtype=np.float64))
            if (target.shape != (3,) or not np.isfinite(target).all() or
                    target[1] != self._planar_anchor_y or
                    not np.array_equal(rotation[:, 1], [0., 1., 0.])):
                raise ValueError('planar reset requires the launch height and upright body')
        self.sim.reset()
        self._set_pose(position, rotation_xyzw)
        self._episodes.add(episode_id)
        self.episode_id = episode_id
        # Initial seeding is not an ACK for a new episode after Simulator.reset.
        self.execution_ack = None
        self.indices = {'primary': 0, 'navigation': 0}
        self.pose_version = 0
        self._navigation_state = None
        self._last_map_revision = -1

    def close(self):
        self.sim.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--config')
    group.add_argument('--config-json')
    args = parser.parse_args(argv)
    output = sys.stdout
    capture = None
    try:
        config = json.loads(Path(args.config).read_text() if args.config else args.config_json)
        # Native libraries may print through C stdout. Keep protocol stdout on a
        # duplicate FD and send all simulator diagnostics to stderr, including C.
        protocol_fd = os.dup(output.fileno())
        output = os.fdopen(protocol_fd, 'w', buffering=1)
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        with contextlib.redirect_stdout(sys.stderr):
            capture = HabitatCapture(config)
        output.write(json.dumps(dict(ready=True, wire_version=WIRE_VERSION,
                                    pose_source='simulator_ground_truth',
                                    execution=capture.execution_ack)) + '\n')
        while True:
            line = sys.stdin.buffer.readline(64 * 1024 + 1)
            if not line:
                break
            if len(line) > 64 * 1024 or not line.endswith(b"\n"):
                raise ValueError('request too large')
            try:
                request = json.loads(line)
                op = request['op']
                if op == 'close':
                    break
                with contextlib.redirect_stdout(sys.stderr):
                    if op in ('capture', 'capture_navigation'):
                        result = dict(packet=capture.capture('primary' if op == 'capture' else 'navigation'))
                        if op == 'capture_navigation':
                            result['pose'] = capture.robot_pose()
                    elif op == 'robot_pose':
                        result = dict(pose=capture.robot_pose())
                    elif op == 'execute':
                        result = dict(actuation=capture.execute(request['command'], request['pose_version']),
                                      actuation_proof=getattr(capture,'last_actuation_proof',None))
                    elif op == 'step':
                        capture.step(request['action'])
                        result = {}
                    elif op == 'reset':
                        capture.reset(request['episode_id'], request['position'], request['rotation_xyzw'])
                        result = {}
                    else:
                        raise ValueError('unknown operation')
                output.write(json.dumps(dict(ok=True, **result), separators=(',', ':')) + '\n')
            except Exception as exc:
                output.write(json.dumps(dict(ok=False, error=type(exc).__name__ + ': ' + str(exc))) + '\n')
        return 0
    except Exception as exc:
        output.write(json.dumps(dict(ready=False, error=type(exc).__name__ + ': ' + str(exc))) + '\n')
        output.flush()
        return 1
    finally:
        if capture is not None:
            with contextlib.redirect_stdout(sys.stderr):
                capture.close()


if __name__ == '__main__':
    raise SystemExit(main())
