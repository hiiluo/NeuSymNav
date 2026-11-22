"""Client of the paper-protocol Habitat worker (paper/sim_worker.py), host interpreter side."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from ...sensors.client import observation_from_packet
from .protocol import ACTIONS, PaperProtocol

WORKER = Path(__file__).with_name('sim_worker.py')
REPO_SRC = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PaperObs:
    observation: object            # contracts Observation: rgb, depth_m, valid_depth, K, T_world_camera (z-up)
    step: int                      # actions taken so far (STOP included)
    collided: bool                 # the last move was blocked by the simulator
    done: bool                     # STOP called or step budget used
    position_h: Tuple[float, float, float]   # Habitat world (y up), for the trajectory / scorer
    robot_xy: Tuple[float, float]  # canonical_z_up_v1
    z_m: float                     # body base height (canonical z = Habitat y)
    yaw_rad: float
    tilt_rad: float                # camera pitch, + = up


def _obs(reply: dict) -> PaperObs:
    pose = reply['pose']
    return PaperObs(observation=observation_from_packet(reply['packet']), step=int(reply['step']),
                    collided=bool(reply['collided']), done=bool(reply['done']),
                    position_h=tuple(float(v) for v in pose['position_h']),
                    robot_xy=tuple(float(v) for v in pose['robot_xy']), z_m=float(pose['z_m']),
                    yaw_rad=float(pose['yaw_rad']), tilt_rad=float(pose['tilt_rad']))


class PaperSimClient:
    def __init__(self, protocol: PaperProtocol, *, python, run_id: str, log_path: Optional[Path] = None):
        python = Path(python)
        if not python.is_absolute() or not python.is_file():
            raise ValueError('habitat python must be an absolute interpreter path')
        env = dict(os.environ, PYTHONPATH=str(REPO_SRC))
        env.pop('LD_LIBRARY_PATH', None)         # same rule as sensors/client.py: keep Mesa's render path
        self._log = open(log_path, 'ab') if log_path else subprocess.DEVNULL
        self.protocol = protocol
        self.process = subprocess.Popen(
            [str(python), '-u', str(WORKER), '--config-json', json.dumps(protocol.worker_config()),
             '--run-id', run_id], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
            env=env, text=True, bufsize=1)
        ready = self._read()
        if ready.get('ready') is not True or ready.get('protocol_sha256') != protocol.sha256:
            self.close()
            raise RuntimeError('paper sim worker unavailable: %s' % ready.get('error', ready))

    def _read(self) -> dict:
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError('paper sim worker exited (code %s)' % self.process.poll())
        return json.loads(line)

    def _request(self, **request) -> dict:
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        reply = self._read()
        if reply.get('ok') is not True:
            raise RuntimeError('paper sim request failed: %s' % reply.get('error'))
        return reply

    def reset(self, episode, episode_id: str) -> PaperObs:
        return _obs(self._request(op='reset', scene_path=episode.scene_path,
                                  dataset_config=episode.runtime_dataset_config,
                                  position=list(episode.start_position),
                                  rotation_xyzw=list(episode.start_rotation_xyzw), episode_id=episode_id))

    def act(self, action: str) -> PaperObs:
        if action not in ACTIONS:
            raise ValueError('unknown action %r' % action)
        return _obs(self._request(op='act', action=action))

    def close(self) -> None:
        try:
            if self.process.poll() is None:
                try:
                    self.process.stdin.write(json.dumps(dict(op='close')) + '\n')
                    self.process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        finally:
            if self._log is not subprocess.DEVNULL:
                self._log.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
