#!/usr/bin/env python3
"""Paper-protocol Habitat worker: discrete actions, simulator-owned collisions (Habitat interpreter).

Run as a FILE with the Habitat interpreter and ``PYTHONPATH=src`` (Python 3.9): it reuses the
pure geometry helpers of ``neusymnav.sensors.habitat_worker`` (packet format, intrinsics, canonical
pose) but none of its motion code. One process serves many episodes; the simulator is rebuilt
only when the scene changes.

Protocol (docs/objectnav/paper-protocol-plan.md, section 3): body cylinder 0.88 x 0.18 m on the
scene's own navmesh (never recomputed, no start snap), one RGB-D camera at 0.88 m (640x480,
HFOV 79 deg, depth clipped to [0.5, 5.0] m), actions move_forward 0.25 m, turn 30 deg,
look up/down 30 deg, stop; ``allow_sliding`` false; at most ``max_steps`` actions (STOP counts).

Wire: JSON lines. stdin requests {"op": "reset"|"act"|"close", ...}; stdout replies
{"ok": true, "step", "collided", "done", "pose", "packet"} where ``packet`` is the checksummed
NPZ capture of ``habitat_worker.encode_packet`` (canonical_z_up_v1). Native logs go to stderr.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import sys

import numpy as np

from neusymnav.sensors import habitat_worker as hw

WIRE = 'paper-sim-v1'
START_NS = 1_000_000_000
STEP_NS = 100_000_000          # nominal 100 ms per action: keeps capture stamps increasing
RGB_UUID, DEPTH_UUID = 'paper_rgb', 'paper_depth'
MOTION_ACTIONS = ('move_forward', 'turn_left', 'turn_right', 'look_up', 'look_down')


def clip_depth(depth, depth_min_m: float, depth_max_m: float):
    """habitat-lab DepthSensor semantics: clip the metric render to [min, max] (no normalisation).

    A pixel at ``depth_max_m`` is "nothing nearer than max"; downstream ``valid_depth`` excludes it
    (normalize_capture: valid = min <= d < max) while the ray up to max is still free space."""
    depth = np.asarray(depth, dtype=np.float32)
    out = np.clip(depth, depth_min_m, depth_max_m)
    out[~np.isfinite(depth) | (depth <= 0)] = depth_max_m      # no return = beyond range
    return out


class PaperSim:
    def __init__(self, config: dict, run_id: str):
        import habitat_sim
        from habitat_sim.utils.common import quat_from_coeffs
        self.hs, self.quat_from_coeffs = habitat_sim, quat_from_coeffs
        self.config, self.domain = config, 'sim_lockstep:' + run_id
        self.sim, self.scene = None, None
        self.episode_id, self.steps, self.done, self.tilt_steps, self.captures = None, 0, False, 0, 0

    # -- simulator
    def _build(self, scene_path: str, dataset_config):
        if self.sim is not None:
            self.sim.close()
            self.sim = None
        hs, cfg = self.hs, self.config
        sim_cfg = hs.SimulatorConfiguration()
        sim_cfg.scene_id = scene_path
        if dataset_config:
            sim_cfg.scene_dataset_config_file = dataset_config
        sim_cfg.enable_physics = False
        sim_cfg.allow_sliding = bool(cfg['allow_sliding'])
        sim_cfg.gpu_device_id = int(cfg['gpu_device_id'])
        agent = hs.agent.AgentConfiguration()
        agent.height, agent.radius = float(cfg['agent']['height_m']), float(cfg['agent']['radius_m'])
        cam = cfg['camera']
        specs = []
        for uuid, kind in ((RGB_UUID, hs.SensorType.COLOR), (DEPTH_UUID, hs.SensorType.DEPTH)):
            spec = hs.CameraSensorSpec()
            spec.uuid, spec.sensor_type = uuid, kind
            spec.sensor_subtype = hs.SensorSubType.PINHOLE
            spec.resolution = list(cam['resolution_hw'])
            spec.position = list(cam['position_xyz'])
            spec.orientation = [0.0, 0.0, 0.0]
            spec.hfov = float(cam['hfov_deg'])
            if kind == hs.SensorType.DEPTH:
                spec.normalize_depth = False
            specs.append(spec)
        agent.sensor_specifications = specs
        a = cfg['actions']
        spec, act = hs.agent.ActionSpec, hs.agent.ActuationSpec
        agent.action_space = {
            'move_forward': spec('move_forward', act(amount=float(a['forward_step_m']))),
            'turn_left': spec('turn_left', act(amount=float(a['turn_deg']))),
            'turn_right': spec('turn_right', act(amount=float(a['turn_deg']))),
            'look_up': spec('look_up', act(amount=float(a['tilt_deg']))),
            'look_down': spec('look_down', act(amount=float(a['tilt_deg']))),
        }
        self.sim = hs.Simulator(hs.Configuration(sim_cfg, [agent]))
        if not self.sim.pathfinder.is_loaded:
            raise RuntimeError('scene navmesh not loaded (paper protocol never recomputes it): ' + scene_path)
        self.agent = self.sim.get_agent(0)
        self.scene = (scene_path, dataset_config)

    def _K(self, uuid, shape):
        sensor = self.sim._sensors[uuid]
        native = getattr(sensor, '_sensor_object', sensor)
        return hw.intrinsics_from_projection(native.render_camera.projection_matrix, shape[1], shape[0])

    def _observe(self, raw: dict, collided: bool) -> dict:
        cam = self.config['camera']
        state = self.agent.get_state()
        depth = clip_depth(np.asarray(raw[DEPTH_UUID])[..., 0] if np.asarray(raw[DEPTH_UUID]).ndim == 3
                           else raw[DEPTH_UUID], float(cam['depth_min_m']), float(cam['depth_max_m']))
        K = self._K(DEPTH_UUID, depth.shape)
        T = hw.sensor_pose(state.sensor_states[DEPTH_UUID])
        if not np.allclose(hw.sensor_pose(state.sensor_states[RGB_UUID]), T, atol=1e-6, rtol=0):
            raise RuntimeError('RGB and depth sensors are not co-located')
        local = np.linalg.inv(hw.sensor_pose(state)) @ T
        stamp = START_NS + self.steps * STEP_NS + self.captures * 1_000_000
        self.captures += 1
        packet = hw.normalize_capture(
            rgb=np.asarray(raw[RGB_UUID]), depth=depth, K=K, T_world_habitat=T,
            episode_id=self.episode_id, sensor_id='paper-rgbd', frame_index=self.captures - 1,
            capture_monotonic_ns=stamp, clock_domain=self.domain, sim_time_s=self.steps * STEP_NS / 1e9,
            calibration_id=hw._calibration_id(K, local, cam), pose_version=self.steps,
            modality='rgbd', depth_min_m=float(cam['depth_min_m']), depth_max_m=float(cam['depth_max_m']))
        body = hw.canonical_robot_pose(state)
        position = [float(v) for v in state.position]
        pose = dict(position_h=position, robot_xy=list(body['robot_xy']), z_m=position[1],
                    yaw_rad=float(body['yaw_rad']),
                    tilt_rad=math.radians(float(self.config['actions']['tilt_deg'])) * self.tilt_steps)
        return dict(step=self.steps, collided=bool(collided), done=self.done, pose=pose,
                    packet=hw.encode_packet(packet))

    # -- operations
    def reset(self, request: dict) -> dict:
        scene = (request['scene_path'], request.get('dataset_config'))
        if scene != self.scene:
            self._build(*scene)
        position = np.asarray(request['position'], dtype=np.float64)
        rotation = np.asarray(request['rotation_xyzw'], dtype=np.float64)
        if position.shape != (3,) or not np.isfinite(position).all() or rotation.shape != (4,):
            raise ValueError('invalid start pose')
        state = self.hs.AgentState()
        state.position = position
        state.rotation = self.quat_from_coeffs(rotation / np.linalg.norm(rotation))
        self.agent.set_state(state, reset_sensors=True)
        self.episode_id = str(request['episode_id'])
        self.steps, self.done, self.tilt_steps, self.captures = 0, False, 0, 0
        return self._observe(self.sim.get_sensor_observations(), False)

    def act(self, action: str) -> dict:
        if self.episode_id is None:
            raise RuntimeError('reset required')
        if self.done:
            raise RuntimeError('episode is over (STOP called or step budget used)')
        if action not in ('stop',) + MOTION_ACTIONS:
            raise ValueError('unknown action ' + repr(action))
        self.steps += 1
        if action == 'stop':
            self.done = True
            return self._observe(self.sim.get_sensor_observations(), False)
        raw = self.sim.step(action)
        collided = bool(raw.get('collided', False))   # habitat_sim.Simulator.step: agent.act result
        if action in ('look_up', 'look_down'):
            self.tilt_steps += 1 if action == 'look_up' else -1
        if self.steps >= int(self.config['max_steps']):
            self.done = True
        return self._observe(raw, collided)

    def close(self):
        if self.sim is not None:
            self.sim.close()
            self.sim = None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config-json', required=True)
    ap.add_argument('--run-id', required=True)
    a = ap.parse_args(argv)
    out = sys.stdout
    sim = None
    try:
        protocol_fd = os.dup(out.fileno())               # keep the protocol off C stdout
        out = os.fdopen(protocol_fd, 'w', buffering=1)
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
        config = json.loads(a.config_json)
        with contextlib.redirect_stdout(sys.stderr):
            sim = PaperSim(config, a.run_id)
        out.write(json.dumps(dict(ready=True, wire=WIRE, protocol_id=config.get('protocol_id'),
                                  protocol_sha256=config.get('sha256'))) + '\n')
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            try:
                request = json.loads(line)
                op = request.get('op')
                if op == 'close':
                    break
                with contextlib.redirect_stdout(sys.stderr):
                    if op == 'reset':
                        result = sim.reset(request)
                    elif op == 'act':
                        result = sim.act(request['action'])
                    else:
                        raise ValueError('unknown op ' + repr(op))
                out.write(json.dumps(dict(ok=True, **result), separators=(',', ':')) + '\n')
            except Exception as exc:
                out.write(json.dumps(dict(ok=False, error=type(exc).__name__ + ': ' + str(exc))) + '\n')
        return 0
    except Exception as exc:
        out.write(json.dumps(dict(ready=False, error=type(exc).__name__ + ': ' + str(exc))) + '\n')
        return 1
    finally:
        if sim is not None:
            with contextlib.redirect_stdout(sys.stderr):
                sim.close()


if __name__ == '__main__':
    raise SystemExit(main())
