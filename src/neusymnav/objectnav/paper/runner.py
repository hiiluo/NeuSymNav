"""Paper-protocol episode runner: obs -> policy -> discrete action -> simulator, <= max_steps.

No guard, no floor datum, no start snap, no velocity pulses: the simulator owns collisions
(``allow_sliding`` false) exactly as in the Habitat ObjectNav challenge. Trajectories use the
lockstep runner's schema so ``tools/objectnav/score_trajectories.py`` scores them unchanged.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence

from .protocol import ACTIONS, PaperProtocol
from .sim_client import PaperObs, PaperSimClient


@dataclass
class PaperContext:
    episode: object                # Episode; a policy reads only ``object_category`` (and uid for logs)
    obs: PaperObs
    protocol: PaperProtocol
    last_action: Optional[str]


def _episode_id(counter: int, episode) -> str:
    return 'paper-%05d-%s' % (counter, re.sub(r'[^A-Za-z0-9_.-]', '_', episode.uid)[-80:])


class PaperRunner:
    def __init__(self, protocol: PaperProtocol, *, out_dir, run_id: str,
                 policy_factory: Callable[[], object], sim_factory: Optional[Callable[[], object]] = None,
                 habitat_python=None, log=print):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise ValueError('run_id must be 1-64 chars of [A-Za-z0-9_.-]')
        self.protocol, self.out_dir, self.run_id = protocol, Path(out_dir), run_id
        self.policy_factory, self.log = policy_factory, log
        self._sim_factory = sim_factory or (lambda: PaperSimClient(
            protocol, python=habitat_python, run_id=run_id, log_path=self.out_dir / 'sim_worker.log'))
        self._counter = 0

    def run(self, episodes: Sequence) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out = self.out_dir / 'trajectories.jsonl'
        done = set()
        if out.exists():          # resume: never re-run a finished episode
            done = {json.loads(line)['uid'] for line in out.read_text().splitlines() if line.strip()}
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
        policy.reset(episode)
        try:
            while not obs.done:
                action = timed('policy', policy.act, PaperContext(episode, obs, self.protocol, last))
                note = None
                if isinstance(action, tuple):
                    action, note = action
                if action not in ACTIONS:
                    raise ValueError('policy returned unknown action %r' % (action,))
                obs = timed('sim', sim.act, action)
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
        return dict(schema_version=1, uid=episode.uid, agent=getattr(policy, 'name', type(policy).__name__),
                    run_id=self.run_id, positions=positions, called_stop=last == 'stop', steps=obs.step,
                    sim_time_s=None, clock_domain='paper_steps', diagnostics=diagnostics)
