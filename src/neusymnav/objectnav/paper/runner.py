"""Paper-protocol episode runner: obs -> policy -> discrete action -> simulator, <= max_steps.

The simulator owns collisions (``allow_sliding`` false) on the bundled navmesh. Trajectories use the
lockstep runner's schema so ``tools/objectnav/score_trajectories.py`` scores them unchanged.
"""
from __future__ import annotations

import json
import hashlib
import re
import time
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from ..b0.trace import completed_uids
from .protocol import ACTIONS, PaperProtocol
from .sim_client import PaperObs, PaperSimClient


@dataclass(frozen=True)
class PaperEpisode:
    uid: str
    object_category: str


@dataclass
class PaperContext:
    episode: PaperEpisode
    obs: PaperObs
    protocol: PaperProtocol
    last_action: Optional[str]
    navigation_audit: Optional[list] = None


@dataclass(frozen=True)
class PaperEnd:
    """End a rollout without sending an action or claiming a target STOP."""

    reason: str


def _episode_id(counter: int, episode) -> str:
    return 'paper-%05d-%s' % (counter, re.sub(r'[^A-Za-z0-9_.-]', '_', episode.uid)[-80:])


def _audit_source(obs):
    frame = obs.observation
    if frame is None:
        return None
    contents = hashlib.sha256(b'NeuSymNav:paper-action-audit:v1\0')
    for name in ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera',
                 'no_return', 'far_plane'):
        array = getattr(frame, name)
        contents.update(name.encode() + b'\0')
        if array is not None:
            little_endian = array.astype(array.dtype.newbyteorder('<'), copy=False)
            contents.update(json.dumps((little_endian.dtype.str, little_endian.shape)).encode() + b'\0')
            contents.update(little_endian.tobytes(order='C'))
    return dict(key=frame.key.to_dict(), calibration_id=frame.calibration_id,
                capture_monotonic_ns=frame.capture_monotonic_ns, clock_domain=frame.clock_domain,
                pose_version=frame.pose_version, geometry_sha256=frame.geometry_hash,
                arrays_sha256=contents.hexdigest())


def _audit_pose(obs):
    return dict(robot_xy=list(obs.robot_xy), z_m=obs.z_m, yaw_rad=obs.yaw_rad, tilt_rad=obs.tilt_rad)


class PaperRunner:
    def __init__(self, protocol: PaperProtocol, *, out_dir, run_id: str,
                 policy_factory: Callable[[], object], sim_factory: Optional[Callable[[], object]] = None,
                 habitat_python=None, log=print, action_audit=False):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise ValueError('run_id must be 1-64 chars of [A-Za-z0-9_.-]')
        self.protocol, self.out_dir, self.run_id = protocol, Path(out_dir), run_id
        self.policy_factory, self.log = policy_factory, log
        self.action_audit = action_audit
        self._sim_factory = sim_factory or (lambda: PaperSimClient(
            protocol, python=habitat_python, run_id=run_id, log_path=self.out_dir / 'sim_worker.log',
            action_audit=action_audit))
        self._counter = 0

    def run(self, episodes: Sequence) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out = self.out_dir / 'trajectories.jsonl'
        done = completed_uids(out, {episode.uid for episode in episodes}, self.run_id)
        todo = [e for e in episodes if e.uid not in done]
        self.log('episodes: %d total, %d already done, %d to run' % (len(episodes), len(done), len(todo)))
        if not todo:
            return out
        sim = self._sim_factory()
        try:
            with open(out, 'a') as stream:
                for _, group in groupby(sorted(todo, key=lambda e: (e.scene_path, e.uid)), key=lambda e: e.scene_path):
                    for episode in group:
                        started = time.monotonic()
                        record = self.run_episode(sim, episode)
                        record['wall_time_s'] = round(time.monotonic() - started, 3)
                        stream.write(json.dumps(record) + '\n')
                        stream.flush()
                        d = record['diagnostics']
                        self.log('%s  %s  stop=%s steps=%d collided=%d path=%.2fm wall=%.1fs %s' % (
                            episode.uid, episode.object_category, record['called_stop'], record['steps'],
                            d['collisions'], d['path_m'], record['wall_time_s'], d['end_reason']))
        finally:
            sim.close()
        return out

    def run_episode(self, sim, episode) -> dict:
        self._counter += 1
        policy = self.policy_factory()
        wall: Dict[str, float] = {}

        def timed(stage, fn, *args, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kw)
            finally:
                wall[stage] = wall.get(stage, 0.0) + time.perf_counter() - t0

        obs = timed('sim', sim.reset, episode, _episode_id(self._counter, episode))
        positions = [list(obs.position_h)]
        counts: Dict[str, int] = {}
        collisions, last, end_reason, policy_record = 0, None, 'max_steps', None
        task = PaperEpisode(episode.uid, episode.object_category)
        audit = [] if self.action_audit else None
        terminal_observation = None
        try:
            policy.reset(task)
            while not obs.done:
                before = (_audit_source(obs), _audit_pose(obs), obs.step) if audit is not None else None
                nav_audit = [] if audit is not None else None
                action = timed('policy', policy.act, PaperContext(task, obs, self.protocol, last, nav_audit))
                if isinstance(action, PaperEnd):
                    end_reason = action.reason
                    if audit is not None:
                        source, pose, input_step = before
                        terminal_observation = dict(input_step=input_step, input_source=source,
                                                    input_pose=pose, reason=end_reason, planner_decisions=nav_audit)
                    break
                note = None
                if isinstance(action, tuple):
                    action, note = action
                if action not in ACTIONS:
                    raise ValueError('policy returned unknown action %r' % (action,))
                obs = timed('sim', sim.act, action)
                if audit is not None:
                    source, pose, input_step = before
                    audit.append(dict(input_step=input_step, input_source=source, input_pose=pose,
                                      requested_action=action, dispatched_action=action,
                                      simulator_execution=getattr(obs, 'execution', None),
                                      planner_decisions=nav_audit,
                                      policy_note=note if isinstance(note, str) else None,
                                      result_step=obs.step, result_pose=_audit_pose(obs),
                                      collided=obs.collided, simulator_done=obs.done))
                counts[action] = counts.get(action, 0) + 1
                collisions += obs.collided
                last = action
                positions.append(list(obs.position_h))
                if action == 'stop':
                    end_reason = 'policy_stop' + (':' + note if note else '')
            if hasattr(policy, 'end_episode'):
                policy_record = policy.end_episode()
        finally:
            if hasattr(policy, 'close'):
                policy.close()
        path = sum(sum((a[i] - b[i]) ** 2 for i in (0, 2)) ** 0.5 for a, b in zip(positions, positions[1:]))
        diagnostics = dict(end_reason=end_reason, protocol=self.protocol.protocol_id,
                           protocol_sha256=self.protocol.sha256, actions=dict(sorted(counts.items())),
                           collisions=collisions, path_m=round(path, 3),
                           wall_s_by_stage={k: round(v, 3) for k, v in sorted(wall.items())})
        if policy_record is not None:
            diagnostics['policy'] = policy_record
        if audit is not None:
            diagnostics['action_audit'] = dict(schema_version=1, steps=audit)
            if terminal_observation is not None:
                diagnostics['action_audit']['terminal_observation'] = terminal_observation
        return dict(schema_version=1, uid=episode.uid, agent=getattr(policy, 'name', type(policy).__name__),
                    run_id=self.run_id, positions=positions, called_stop=last == 'stop', steps=obs.step,
                    sim_time_s=None, clock_domain='paper_steps', diagnostics=diagnostics)
