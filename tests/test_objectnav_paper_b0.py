"""Paper-mode B0 / B1-revisit on a synthetic room (no Habitat): map, detection, approach, STOP."""
import dataclasses
import gzip
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.objectnav.detector_eval.categories import GoalCategories
from neusymnav.objectnav.paper.b0 import PaperB0Config, PaperB0Policy
from neusymnav.objectnav.paper.protocol import PaperProtocol
from neusymnav.objectnav.paper.runner import PaperRunner
from neusymnav.objectnav.paper.sim_client import PaperObs

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = PaperProtocol.load(ROOT / 'configs/objectnav/paper-hm3d-v1.json')
HALF = 3.0                       # square room [-3, 3]^2, walls 2.5 m high
CHAIR = (2.0, 1.2, 0.4)          # x0, y0, size: a box on the floor 0.9 m high


class RoomSim:
    """Discrete-action simulator of an empty square room with one chair (body r = 0.18 m)."""
    H, W = 60, 80

    def __init__(self, max_steps=500, start=(-2.0, -1.5, 0.0)):
        self.max_steps, self.start, self.frame = max_steps, start, 0
        f = (self.W / 2) / math.tan(math.radians(PROTOCOL.hfov_deg) / 2)
        self.K = np.array([[f, 0, (self.W - 1) / 2], [0, f, (self.H - 1) / 2], [0, 0, 1.0]])

    def _blocked(self, x, y):
        r = 0.18
        if abs(x) > HALF - r or abs(y) > HALF - r:
            return True
        x0, y0, s = CHAIR
        dx = max(x0 - x, 0, x - (x0 + s))
        dy = max(y0 - y, 0, y - (y0 + s))
        return math.hypot(dx, dy) < r

    def _render(self):
        fwd = np.array([math.cos(self.yaw), math.sin(self.yaw), 0.0])
        right = np.array([math.sin(self.yaw), -math.cos(self.yaw), 0.0])
        down = np.array([0.0, 0.0, -1.0])
        T = np.eye(4)
        T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = right, down, fwd, (self.x, self.y, 0.88)
        rows, cols = np.mgrid[0:self.H, 0:self.W]
        d_cam = np.stack(((cols - self.K[0, 2]) / self.K[0, 0], (rows - self.K[1, 2]) / self.K[1, 1],
                          np.ones((self.H, self.W))), -1)
        rays = d_cam @ T[:3, :3].T                       # world direction per pixel, axial depth = parameter t
        o = T[:3, 3]
        t = np.full((self.H, self.W), np.inf)
        with np.errstate(divide='ignore', invalid='ignore'):
            tz = -o[2] / rays[..., 2]                    # floor
            t = np.where((tz > 0), np.minimum(t, tz), t)
            for axis, bound in ((0, HALF), (0, -HALF), (1, HALF), (1, -HALF)):
                tw = (bound - o[axis]) / rays[..., axis]
                t = np.where(tw > 0, np.minimum(t, tw), t)
            x0, y0, s = CHAIR                            # chair box: slab test
            lo = np.array([x0, y0, 0.0]) - o
            hi = np.array([x0 + s, y0 + s, 0.9]) - o
            t1, t2 = lo / rays, hi / rays
            tmin = np.nanmax(np.minimum(t1, t2), axis=-1)
            tmax = np.nanmin(np.maximum(t1, t2), axis=-1)
            hit = (tmax >= tmin) & (tmin > 0)
            self.chair_pixels = int(hit.sum())
            t = np.where(hit, np.minimum(t, tmin), t)
        depth = np.clip(t, 0.5, 5.0).astype(np.float32)
        self.frame += 1
        return SimpleNamespace(depth_m=depth, valid_depth=(t >= 0.5) & (t < 5.0), K=self.K, T_world_camera=T,
                               key=SimpleNamespace(frame_index=self.frame), capture_monotonic_ns=self.frame * 10**8)

    def _obs(self, collided=False):
        done = self.done or self.step >= self.max_steps
        return PaperObs(observation=self._render(), step=self.step, collided=collided, done=done,
                        position_h=(self.x, 0.0, -self.y), robot_xy=(self.x, self.y), z_m=0.0,
                        yaw_rad=self.yaw, tilt_rad=0.0)

    def reset(self, episode, episode_id):
        self.x, self.y, self.yaw = self.start
        self.step, self.done = 0, False
        return self._obs()

    def act(self, action):
        self.step += 1
        collided = False
        if action == 'stop':
            self.done = True
        elif action == 'move_forward':
            nx, ny = self.x + 0.25 * math.cos(self.yaw), self.y + 0.25 * math.sin(self.yaw)
            if self._blocked(nx, ny):
                collided = True
            else:
                self.x, self.y = nx, ny
        elif action in ('turn_left', 'turn_right'):
            self.yaw += math.radians(30) * (1 if action == 'turn_left' else -1)
        return self._obs(collided)

    def close(self):
        pass


def _chair_points():
    rng = np.random.default_rng(0)
    x0, y0, s = CHAIR
    return np.column_stack((rng.uniform(x0, x0 + s, 400), rng.uniform(y0, y0 + s, 400), rng.uniform(0.1, 0.9, 400)))


class FakeProjector:
    def project(self, obs, batch):
        return tuple(SimpleNamespace(detection_id=d.detection_id, points_world=_chair_points()) for d in batch.detections)


def _detector(sim, calls):
    class Client:
        def infer(self, obs):
            calls.append(obs.key.frame_index)
            dets = ()
            if sim.chair_pixels >= 20:
                mask = np.zeros((4, 4), bool)
                mask[1:3, 1:3] = True
                dets = (SimpleNamespace(detection_id='d0', raw_label='chair', score=0.8, mask=mask),)
            return SimpleNamespace(detections=dets, cap_reached=False)

        def close(self):
            calls.append('closed')
    return Client


SMALL_MAP_M = 16.0               # the fake room is 6 x 6 m: a 16 m map instead of the default 60 m keeps tests fast


def small_map(cfg):
    """The same policy config with a test-sized navigation map (production configs are unchanged)."""
    return dataclasses.replace(cfg, nav=dict(cfg.nav, size_m=SMALL_MAP_M))


def _config(**kw):
    data = json.loads((ROOT / 'configs/objectnav/paper-b0-v1.json').read_text())
    data.pop('schema_version')
    data.update(kw)
    return PaperB0Config(**data)


def _run(tmp_path, cfg, sim):
    calls = []
    factory = lambda: PaperB0Policy(small_map(cfg), categories=GoalCategories.load(), detector_factory=_detector(sim, calls),  # noqa: E731
                                    evidence_dir=tmp_path / 'evidence', projector=FakeProjector())
    runner = PaperRunner(PROTOCOL, out_dir=tmp_path, run_id='b0t', sim_factory=lambda: sim,
                         policy_factory=factory, log=lambda *_: None)
    episode = SimpleNamespace(uid='hm3d_v2/val/Room/1', scene_path='/room.glb', object_category='chair')
    rec = json.loads(runner.run([episode]).read_text().splitlines()[0])
    return rec, calls


def test_paper_b0_finds_approaches_and_stops_at_the_chair(tmp_path):
    sim = RoomSim()
    rec, calls = _run(tmp_path, _config(), sim)
    pol = rec['diagnostics']['policy']
    assert rec['called_stop'] and rec['diagnostics']['end_reason'] == 'policy_stop:confirmed_target'
    assert pol['stop']['distance_to_object_m'] <= 0.45
    states = [e['state'] for e in pol['events']]
    assert states[0] == 'EXPLORE' and 'APPROACH' in states and 'VERIFY' in states
    assert rec['steps'] < 120 and calls[-1] == 'closed'
    # detector only on new views; evidence file in the lockstep format
    rows = [json.loads(l) for l in gzip.open(pol['evidence_file'], 'rt')]
    assert len(rows) == pol['detections']['frames'] <= rec['steps'] + 1
    assert rows[-1]['detections'][0]['goal'] == 'chair' and len(rows[-1]['depth_small_cm']) == 3


def test_paper_b0_stops_when_the_room_is_explored_without_target(tmp_path, monkeypatch):
    global CHAIR
    monkeypatch.setattr(__import__(__name__), 'CHAIR', (10.0, 10.0, 0.4))
    sim = RoomSim()
    rec, _ = _run(tmp_path, _config(), sim)
    assert rec['diagnostics']['end_reason'] == 'policy_stop:frontiers_exhausted'
    assert rec['diagnostics']['policy']['map']['explored_m2'] > 25


def test_paper_b1_config_has_revisit_and_b0_has_none():
    b1 = PaperB0Config.load(ROOT / 'configs/objectnav/paper-b1r-v1.json')
    b0 = PaperB0Config.load(ROOT / 'configs/objectnav/paper-b0-v1.json')
    assert b0.revisit is None and b1.revisit['cooldown_steps'] == 30
    with pytest.raises(ValueError):
        _config(revisit=dict(cooldown_s=30))
    with pytest.raises(TypeError):
        _config(unknown=1)
    with pytest.raises(TypeError):
        _config(nav=dict(no_such_key=1))


def test_paper_b1_revives_a_candidate_given_up_for_motion(tmp_path):
    sim = RoomSim()
    cfg = _config(revisit=dict(cooldown_steps=0, min_moved_m=0.0, max_revisits=3, opportunistic_arrival=True))
    rec, _ = _run(tmp_path, cfg, sim)
    assert rec['diagnostics']['end_reason'] == 'policy_stop:confirmed_target'
    assert 'revisit' in rec['diagnostics']['policy']
