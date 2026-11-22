"""Paper-protocol configuration (configs/objectnav/paper-*.json), validated and hashed.

Python 3.9 compatible: the Habitat worker imports nothing from here, but tests run both sides.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

ACTIONS = ('stop', 'move_forward', 'turn_left', 'turn_right', 'look_up', 'look_down')


def _num(value, name, *, low=None, high=None, positive=False) -> float:
    if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError('%s must be a finite number' % name)
    value = float(value)
    if positive and value <= 0:
        raise ValueError('%s must be positive' % name)
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError('%s out of range' % name)
    return value


@dataclass(frozen=True)
class PaperProtocol:
    protocol_id: str
    agent_height_m: float
    agent_radius_m: float
    resolution_hw: Tuple[int, int]
    hfov_deg: float
    camera_position_xyz: Tuple[float, float, float]
    depth_min_m: float
    depth_max_m: float
    forward_step_m: float
    turn_deg: float
    tilt_deg: float
    allow_sliding: bool
    max_steps: int
    success_distance_m: float
    gpu_device_id: int
    sha256: str

    @classmethod
    def from_dict(cls, data: dict) -> 'PaperProtocol':
        if not isinstance(data, dict) or data.get('schema_version') != 1:
            raise ValueError('paper protocol: schema_version 1 required')
        known = {'schema_version', 'protocol_id', 'description', 'sources', 'agent', 'camera', 'actions',
                 'allow_sliding', 'max_steps', 'success_distance_m', 'gpu_device_id'}
        extra = set(data) - known
        if extra:
            raise ValueError('paper protocol: unknown fields %s' % sorted(extra))
        pid = data.get('protocol_id')
        if not isinstance(pid, str) or not pid:
            raise ValueError('protocol_id must be a nonempty string')
        agent, cam, act = data.get('agent'), data.get('camera'), data.get('actions')
        if not all(isinstance(x, dict) for x in (agent, cam, act)):
            raise ValueError('agent, camera and actions must be objects')
        if set(agent) != {'height_m', 'radius_m'}:
            raise ValueError('agent needs exactly height_m, radius_m')
        if set(cam) != {'resolution_hw', 'hfov_deg', 'position_xyz', 'depth_min_m', 'depth_max_m'}:
            raise ValueError('camera fields mismatch')
        if set(act) != {'forward_step_m', 'turn_deg', 'tilt_deg'}:
            raise ValueError('actions need exactly forward_step_m, turn_deg, tilt_deg')
        hw = cam['resolution_hw']
        if (not isinstance(hw, list) or len(hw) != 2 or any(type(v) is not int or v <= 0 for v in hw)):
            raise ValueError('resolution_hw must be two positive integers')
        pos = cam['position_xyz']
        if not isinstance(pos, list) or len(pos) != 3:
            raise ValueError('position_xyz must have 3 numbers')
        pos = tuple(_num(v, 'position_xyz') for v in pos)
        dmin, dmax = _num(cam['depth_min_m'], 'depth_min_m', positive=True), _num(cam['depth_max_m'], 'depth_max_m')
        if not dmin < dmax:
            raise ValueError('depth_min_m must be < depth_max_m')
        if type(data.get('allow_sliding')) is not bool:
            raise ValueError('allow_sliding must be boolean')
        steps = data.get('max_steps')
        if type(steps) is not int or steps <= 0:
            raise ValueError('max_steps must be a positive integer')
        gpu = data.get('gpu_device_id', -1)
        if type(gpu) is not int or gpu < -1:
            raise ValueError('gpu_device_id must be an integer >= -1')
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return cls(protocol_id=pid,
                   agent_height_m=_num(agent['height_m'], 'height_m', positive=True),
                   agent_radius_m=_num(agent['radius_m'], 'radius_m', positive=True),
                   resolution_hw=(hw[0], hw[1]),
                   hfov_deg=_num(cam['hfov_deg'], 'hfov_deg', low=1, high=179),
                   camera_position_xyz=pos, depth_min_m=dmin, depth_max_m=dmax,
                   forward_step_m=_num(act['forward_step_m'], 'forward_step_m', positive=True),
                   turn_deg=_num(act['turn_deg'], 'turn_deg', low=1, high=180),
                   tilt_deg=_num(act['tilt_deg'], 'tilt_deg', low=1, high=90),
                   allow_sliding=data['allow_sliding'], max_steps=steps,
                   success_distance_m=_num(data.get('success_distance_m'), 'success_distance_m', positive=True),
                   gpu_device_id=gpu, sha256=digest)

    @classmethod
    def load(cls, path) -> 'PaperProtocol':
        return cls.from_dict(json.loads(Path(path).read_text()))

    @property
    def camera_height_m(self) -> float:
        return self.camera_position_xyz[1]

    def worker_config(self) -> dict:
        """The simulator settings the Habitat worker needs (no scene: reset carries it)."""
        return dict(protocol_id=self.protocol_id, sha256=self.sha256,
                    agent=dict(height_m=self.agent_height_m, radius_m=self.agent_radius_m),
                    camera=dict(resolution_hw=list(self.resolution_hw), hfov_deg=self.hfov_deg,
                                position_xyz=list(self.camera_position_xyz),
                                depth_min_m=self.depth_min_m, depth_max_m=self.depth_max_m),
                    actions=dict(forward_step_m=self.forward_step_m, turn_deg=self.turn_deg,
                                 tilt_deg=self.tilt_deg),
                    allow_sliding=self.allow_sliding, max_steps=self.max_steps,
                    gpu_device_id=self.gpu_device_id)
