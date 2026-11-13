"""Phase-3 B0: candidate memory, latency gate, approach goals, policy states, runner hooks."""
import gzip
import json
import math
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.contracts import NavigationDecision
from neusymnav.navigation.controller import Navigator
from neusymnav.objectnav.b0.approach import approach_goals, facing_rate, wrap
from neusymnav.objectnav.b0.detection import LatencyGate, recipe_from_profile
from neusymnav.objectnav.b0.memory import CandidateMemory, footprint_distance
from neusymnav.objectnav.b0.policy import B0Config, B0Policy
from neusymnav.objectnav.detector_eval.categories import GoalCategories
from neusymnav.objectnav.runner import LockstepRunner
from test_navigation import nav
from test_navmap import geometry
from test_objectnav_runner import FakeSensor, config, episode, identity_snap

RULE = json.loads(open('configs/objectnav/b0-detection-v1.json').read())['categories']


def box(x, y, *, size=0.4, z0=0.1, z1=0.9, n=400, seed=0):
    rng = np.random.default_rng(seed)
    return np.column_stack((rng.uniform(x, x + size, n), rng.uniform(y, y + size, n), rng.uniform(z0, z1, n)))


def memory():
    return CandidateMemory(GoalCategories.load(), RULE, floor_z_m=0.0, robot_height_m=1.5)


# ------------------------------------------------------------------ memory

def test_memory_associates_views_and_applies_the_phase2_rule():
    m = memory()
    a = m.add(0, 'chair', .6, box(1, 1, seed=1))
    assert m.add(1, 'chair', .55, box(1.05, 1, seed=2)) == a               # same chair, second view
    b = m.add(2, 'chair', .7, box(3, 3, seed=3))                            # another chair 2 m away
    assert a != b and len(m.candidates) == 2
    assert m.add(3, 'lamp', .9, box(1, 1)) is None                          # not a goal label
    assert m.add(4, 'chair', .2, box(1, 1)) is None                         # below every rule threshold
    ca, cb = m.candidates[a], m.candidates[b]
    assert m.confirmed(ca, 'chair') and not m.confirmed(cb, 'chair')        # chair: 2 views at >= 0.5
    assert [c.cid for c in m.confirmed_for('chair')] == [a]
    assert m.best_unconfirmed('chair').cid in (a, b)


def test_vote_rejects_an_object_mostly_called_something_else():
    m = memory()
    pts = box(0, 0, size=1.0)
    for f in range(3):
        cid = m.add(f, 'sofa', .6, pts)
    for f in range(3, 7):
        m.add(f, 'armchair', .6, pts)                                       # armchair -> chair category
    cand = m.candidates[cid]
    assert cand.count('sofa', .5) == 3 and cand.count('chair', .5) == 4
    assert not m.confirmed(cand, 'sofa')                                    # sofa rule votes
    assert m.confirmed(cand, 'chair')                                       # chair rule does not


def test_far_side_joins_near_side_and_two_candidates_merge():
    m = memory()
    a = m.add(0, 'bed', .6, box(0, 0, size=0.3))
    b = m.add(1, 'bed', .6, box(0.9, 0, size=0.3))                          # other end of the same bed
    assert a != b
    c = m.add(2, 'bed', .6, box(0.25, 0, size=0.7))                         # middle view bridges both
    assert len(m.candidates) == 1 and c == min(a, b)
    cand = m.candidates[c]
    assert cand.count('bed', .5) == 3 and sorted(cand.merged_from) == [max(a, b)]
    # different category next to it (box overlap only counts within a category)
    d = m.add(3, 'television', .6, box(1.25, 0, size=0.3))
    assert d != c
    row = m.summary('bed')[0]
    assert row['confirmed'] and row['views'] == {'bed': 3}
    assert footprint_distance(cand.points[:, :2], (2.0, 0.1)) == pytest.approx(0.8, abs=0.06)   # bed spans x 0..1.2


# ------------------------------------------------------------------ latency

def test_latency_gate_releases_after_simulated_latency_one_at_a_time():
    calls = []
    gate = LatencyGate(lambda o: calls.append(o) or 'batch-%d' % len(calls), latency_ms=400)
    frame = lambda ns: SimpleNamespace(capture_monotonic_ns=ns)
    assert gate.submit(frame(1_000_000_000)) and not gate.submit(frame(1_100_000_000))
    assert gate.ready(1_300_000_000) == [] and gate.in_flight
    done = gate.ready(1_400_000_000)
    assert [d.batch for d in done] == ['batch-1'] and not gate.in_flight and len(calls) == 1
    with pytest.raises(ValueError):
        LatencyGate(lambda o: o, latency_ms=-1)


def test_recipe_from_profile_checks_pins(tmp_path):
    asset = tmp_path / 'a.bin'
    asset.write_bytes(b'x')
    profile = tmp_path / 'p.json'
    pin = dict(path=str(asset), sha256='0' * 64)
    profile.write_text(json.dumps(dict(detector=dict(checkpoint=pin, encoder=pin, taxonomy=pin),
                                       workers=dict(detector=dict(python=pin, script=pin)))))
    with pytest.raises(ValueError, match='checksum'):
        recipe_from_profile(profile)


# ------------------------------------------------------------------ approach

def test_approach_goals_ring_closer_and_toward():
    n = nav(np.zeros((30, 30), np.int8))                                   # 3 m x 3 m free
    trav = np.zeros((30, 30), bool)
    trav[:, :20] = True                                                    # x < 2 m traversable
    grid = SimpleNamespace(resolution_m=.1, origin_x_m=0., origin_y_m=0.)
    obj = np.array([[1.0, 1.5], [1.1, 1.5]])
    cells, extra, tag = approach_goals(grid, trav, obj, (1.05, 1.5), aim_m=0.4)
    assert tag == 'ring' and cells and all(v == 0 for v in extra.values())
    for r, c in cells:
        assert footprint_distance(obj, ((c + .5) * .1, (r + .5) * .1)) <= 0.4 and trav[r, c]
    far = np.array([[2.6, 1.5]])                                           # behind the untraversable band
    cells, extra, tag = approach_goals(grid, trav, far, (2.6, 1.5), aim_m=0.4)
    assert tag == 'closer' and min(extra.values()) == pytest.approx(2.0 * math.hypot(0.65, 0.05), abs=1e-6)
    cells, extra, tag = approach_goals(grid, trav, np.array([[9.0, 1.5]]), (9.0, 1.5), aim_m=0.4)
    assert tag == 'toward' and cells
    rate, err = facing_rate((0, 0), 0.0, (0, 1))
    assert rate == pytest.approx(math.radians(29.5)) and err == pytest.approx(math.pi / 2)
    assert facing_rate((0, 0), math.pi / 2, (0, 1))[0] == 0.0
    assert wrap(3 * math.pi) == pytest.approx(-math.pi)


def test_navigator_step_toward_plans_to_selected_cells_and_keeps_frontier_state():
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    n = nav()                                                              # 15x15 free, 0.1 m cells
    calls = []

    def select(grid, trav):
        calls.append(trav.shape)
        return [(7, 12)], {(7, 12): 0.0}, 'ring'

    d = navigator.step_toward(n, (.35, .75), 0.0, 1_000_000_000, select, 'b0-cand-1')
    assert calls == [(15, 15)] and d.goal_id == 'b0-cand-1' and d.path
    assert d.path[-1] == pytest.approx((1.25, .75)) and navigator.last_approach['tag'] == 'ring'
    none = navigator.step_toward(n, (.35, .75), 0.0, 1_000_000_000, lambda g, t: ([], {}, 'none'), 'x')
    assert none.reason == 'approach_no_goal_cells' and none.desired_linear_mps == 0
    navigator.release_goal()
    assert navigator.policy._goal is None


# ------------------------------------------------------------------ policy

class FakeProjector:
    def __init__(self, points):
        self.points = points

    def project(self, obs, batch):
        return tuple(SimpleNamespace(detection_id=d.detection_id, points_world=self.points[d.raw_label])
                     for d in batch.detections if d.raw_label in self.points)


class FakeNavigator:
    def __init__(self):
        self.toward, self.released = 0, 0

    def step(self, nav, xy, yaw, now):
        return NavigationDecision('f', ((0, 0), (1, 0)), .15, 0., 1, 'tracking')

    def step_toward(self, nav, xy, yaw, now, select, goal_id):
        self.toward += 1
        return NavigationDecision(goal_id, ((0, 0), (1, 0)), .15, 0., 1, 'tracking')

    def release_goal(self):
        self.released += 1


def det(label, score, i=0):
    mask = np.zeros((4, 4), bool)
    mask[1:3, 1:3] = True
    return SimpleNamespace(detection_id='d%d' % i, raw_label=label, score=score, mask=mask)


def b0_config(**kw):
    base = dict(name='t', detection_rule='configs/objectnav/b0-detection-v1.json',
                mapping='configs/objectnav/goal-categories-v1.json', detector_profile='unused',
                stop_distance_m=0.5, initial_spin=False)
    base.update(kw)
    return B0Config(**base)


def test_policy_explores_confirms_approaches_faces_verifies_and_stops(tmp_path):
    chair = box(2.0, -0.2, size=0.4)
    frames = []

    class Client:
        def infer(self, obs):
            frames.append(obs.key.frame_index)
            return SimpleNamespace(detections=(det('chair', .7),), cap_reached=False)

        def close(self):
            frames.append('closed')

    pol = B0Policy(b0_config(), categories=GoalCategories.load(), detector_factory=Client, robot_height_m=1.5,
                   evidence_dir=tmp_path, projector=FakeProjector({'chair': chair}))
    pol.reset(episode())
    pol.begin_episode(floor_z_m=0.0, episode_tag='ep0')
    navigator = FakeNavigator()
    ns, idx, xy, yaw = [1_000_000_000], [0], [0.0, 0.0], [0.0]

    def obs():
        idx[0] += 1
        return SimpleNamespace(key=SimpleNamespace(frame_index=idx[0]), capture_monotonic_ns=ns[0],
                               T_world_camera=np.eye(4), K=np.eye(3))

    def ctx(cycle):
        return SimpleNamespace(nav=SimpleNamespace(revision=1), robot_xy=tuple(xy), yaw_rad=yaw[0],
                               now_ns=ns[0], cycle=cycle, navigator=navigator)

    states = []
    for cycle in range(150):
        if pol.wants_frame(ns[0], tuple(xy), yaw[0]):
            pol.on_frame(obs(), tuple(xy), yaw[0])
        action = pol.act(ctx(cycle))
        states.append(pol.state)
        if action.stop:
            break
        d = action.decision
        xy[0] += d.desired_linear_mps * .3
        yaw[0] += d.desired_yaw_radps * .5
        ns[0] += 300_000_000
    assert action.stop and action.note == 'confirmed_target'
    assert states[0] == 'EXPLORE' and 'APPROACH' in states and 'VERIFY' in states
    assert navigator.toward > 0 and navigator.released >= 1
    rec = pol.end_episode()
    pol.close()
    assert rec['stop']['distance_to_object_m'] <= 0.5 and rec['candidates'][0]['confirmed']
    assert frames[-1] == 'closed' and rec['detections']['frames'] >= 2
    rows = [json.loads(l) for l in gzip.open(tmp_path / 'ep0.jsonl.gz', 'rt')]
    assert rows[0]['detections'][0]['goal'] == 'chair' and 'rle' in rows[0]['detections'][0]


def test_policy_stops_when_frontiers_exhausted_without_candidates():
    class Client:
        def infer(self, obs):
            return SimpleNamespace(detections=(), cap_reached=False)

    pol = B0Policy(b0_config(exhausted_cycles=3), categories=GoalCategories.load(), detector_factory=Client,
                   robot_height_m=1.5, projector=FakeProjector({}))
    pol.reset(episode())
    pol.begin_episode(floor_z_m=0.0, episode_tag='e')

    class Exhausted(FakeNavigator):
        def step(self, *a):
            return NavigationDecision(None, (), 0., 0., 1, 'no_reachable_frontier_viewpoint')

    navigator = Exhausted()
    for cycle in range(5):
        a = pol.act(SimpleNamespace(nav=SimpleNamespace(revision=1), robot_xy=(0., 0.), yaw_rad=0.,
                                    now_ns=1_000_000_000 + cycle, cycle=cycle, navigator=navigator))
        if a.stop:
            break
    assert a.stop and a.note == 'frontiers_exhausted' and pol.end_episode()['stop']['cid'] is None


def test_b0_config_file_loads_and_validates():
    cfg = B0Config.load('configs/objectnav/b0-policy-v1.json')
    assert cfg.max_sim_s == 500.0 and cfg.resolve('detection_rule').is_file()
    with pytest.raises(ValueError):
        b0_config(stop_distance_m=0.1)
    with pytest.raises(ValueError):
        b0_config(aim_margin_m=0.6)


# ------------------------------------------------------------------ runner hooks

class LookingSensor(FakeSensor):
    def capture(self):
        nav = self.capture_navigation()                    # same clock, a distinct primary frame
        return replace(nav, key=replace(nav.key, sensor_id='primary-rgbd'))


class LookingPolicy:
    name = 'looking_test'

    def reset(self, episode):
        self.calls, self.n = [], 0

    def begin_episode(self, *, floor_z_m, episode_tag):
        self.calls.append(('begin', round(floor_z_m, 3), episode_tag))

    def wants_frame(self, now_ns, xy, yaw):
        return len([c for c in self.calls if c[0] == 'frame']) < 3

    def on_frame(self, obs, xy, yaw):
        self.calls.append(('frame', obs.key.sensor_id))

    def act(self, ctx):
        self.n += 1
        return SimpleNamespace(stop=self.n >= 5, note='done', decision=NavigationDecision(
            None, (), 0., 0., ctx.nav.revision, 'hold'))

    def end_episode(self):
        return dict(calls=self.calls)

    def close(self):
        self.calls.append(('close',))


def test_runner_feeds_primary_frames_and_records_policy_diagnostics(tmp_path):
    runner = LockstepRunner(config(), habitat_python=tmp_path / 'py', out_dir=tmp_path / 'l', run_id='l',
                            policy_factory=LookingPolicy, sensor_factory=LookingSensor,
                            start_snapper=identity_snap, log=lambda *_: None)
    rec = json.loads(runner.run([episode()]).read_text())
    calls = rec['diagnostics']['policy']['calls']
    assert calls[0][0] == 'begin' and [c[1] for c in calls if c[0] == 'frame'] == ['primary-rgbd'] * 3
    assert rec['diagnostics']['primary_frames'] == 3 and rec['called_stop']
    assert {'mapper', 'policy', 'capture_primary'} <= set(rec['diagnostics']['wall_s_by_stage'])


def test_stop_calibration_unprojection_matches_habitat_camera_axes():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('stop_calibration', Path('tools/objectnav/b0/stop_calibration.py'))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    depth = np.full((tool.HEIGHT, tool.WIDTH), 2.0)
    centre = (tool.HEIGHT // 2, tool.WIDTH // 2)
    w = tool.unproject(depth, (1.0, 0.5, 3.0), 0.0)                       # yaw 0 looks along -z
    assert w[centre] == pytest.approx((1.0 + 2.0 / 320 * 0.5, 0.5 + 1.2 - 2.0 / 320 * 0.5, 1.0), abs=1e-6)
    w = tool.unproject(depth, (0.0, 0.0, 0.0), math.pi / 2)              # yaw +90 deg looks along -x
    assert w[centre][0] == pytest.approx(-2.0, abs=0.01) and w[centre][2] == pytest.approx(0.0, abs=0.01)
    assert w[centre[0], -1][2] < 0                                          # image right is -z when facing -x
    vps = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    assert tool.success_at(np.array([0.05, 0.0, 0.0]), vps) and not tool.success_at(np.array([0.5, 0.0, 0.0]), vps)


def _tool(name):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(name, Path('tools/objectnav/b0/%s.py' % name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failure_evidence_camera_pose_round_trip_and_labels():
    tool = _tool('failure_evidence')
    p, th = np.array([1.0, 0.3, -2.0]), 0.7
    right = (math.cos(th), math.sin(th), 0.0)
    down = (0.0, 0.0, -1.0)
    forward = (-math.sin(th), math.cos(th), 0.0)
    T = np.eye(4)
    T[:3, :3] = np.column_stack((right, down, forward))
    T[:3, 3] = (p[0], -p[2], p[1] + 1.2)
    pos, yaw = tool.habitat_camera(T.tolist())
    assert pos == pytest.approx(p) and yaw == pytest.approx(th)
    # one frame: goal 7 visible at 2 m and detected; the stop candidate sits on object 9 (not a goal)
    from neusymnav.objectnav.detector_eval.masks import rle_encode
    sem = np.zeros((tool.HEIGHT, tool.WIDTH), np.uint32)
    sem[100:200, 100:200], sem[300:400, 300:400] = 7, 9
    depth = np.full(sem.shape, 2.0)
    det = lambda m, cid: dict(goal='chair', label='chair', score=.6, rle=rle_encode(m), cid=cid)
    frames = [dict(T_world_camera=T.tolist(), detections=[det(sem == 7, 1), det(sem == 9, 2)])]
    record = dict(diagnostics=dict(policy=dict(stop=dict(cid=2), candidates=[dict(cid=1, confirmed=True),
                                                                                 dict(cid=2, confirmed=True)])))
    ev = tool.episode_evidence(frames, {7}, 'chair', record, lambda T: (sem, depth), {7: 'chair', 9: 'stool'})
    assert ev['target_seen'] and ev['target_detected'] and ev['stop_near_false_detection']
    assert ev['stop_object']['name'] == 'stool' and ev['confirmed_goal']
    assert ev['confirmed_candidates']['1']['is_goal'] and not ev['confirmed_candidates']['2']['is_goal']


def test_far_stop_on_the_closest_reachable_cell():
    class Client:
        def infer(self, obs):
            return SimpleNamespace(detections=(det('chair', .7),), cap_reached=False)

    chair = box(1.6, -0.2, size=0.4)                                         # 0.6 m ahead of the robot
    pol = B0Policy(b0_config(stop_distance_m=0.4, far_stop_distance_m=0.9), categories=GoalCategories.load(),
                   detector_factory=Client, robot_height_m=1.5, projector=FakeProjector({'chair': chair}))
    pol.reset(episode())
    pol.begin_episode(floor_z_m=0.0, episode_tag='far')

    class Blocked(FakeNavigator):                                           # no cell within 0.3 m is traversable
        def step_toward(self, nav, xy, yaw, now, select, goal_id):
            self.last_approach = dict(tag='closer', goal_cells=5, goal_xy=list(xy))
            return NavigationDecision(goal_id, (), 0., 0., 1, 'goal_reached')

    navigator, ns, notes = Blocked(), [1_000_000_000], []
    for cycle in range(40):
        if pol.wants_frame(ns[0], (1.0, 0.0), 0.0):
            pol.on_frame(SimpleNamespace(key=SimpleNamespace(frame_index=cycle), capture_monotonic_ns=ns[0],
                                         T_world_camera=np.eye(4), K=np.eye(3)), (1.0, 0.0), 0.0)
        a = pol.act(SimpleNamespace(nav=SimpleNamespace(revision=1), robot_xy=(1.0, 0.0), yaw_rad=0.0,
                                    now_ns=ns[0], cycle=cycle, navigator=navigator))
        ns[0] += 300_000_000
        if a.stop:
            break
    notes = [e['note'] for e in pol.events]
    assert a.stop and 'arrived_far' in notes and pol.stop_record['distance_to_object_m'] <= 0.9


def test_recipe_keeps_the_venv_interpreter_path_unresolved(tmp_path):
    import hashlib
    import os
    real = tmp_path / 'real_python'
    real.write_bytes(b'#!py')
    (tmp_path / 'venv/bin').mkdir(parents=True)
    link = tmp_path / 'venv/bin/python'
    os.symlink(real, link)
    from neusymnav.objectnav.b0 import detection
    pin = dict(path=str(link), sha256=hashlib.sha256(b'#!py').hexdigest())
    assert detection._pinned(pin, 'python')[0] == str(link)           # not the symlink target


def test_policy_stops_when_the_pose_never_changes():
    class Client:
        def infer(self, obs):
            return SimpleNamespace(detections=(), cap_reached=False)

    pol = B0Policy(b0_config(stuck_stop_s=5.0), categories=GoalCategories.load(), detector_factory=Client,
                   robot_height_m=1.5, projector=FakeProjector({}))
    pol.reset(episode())
    pol.begin_episode(floor_z_m=0.0, episode_tag='s')
    for cycle in range(100):
        a = pol.act(SimpleNamespace(nav=SimpleNamespace(revision=1), robot_xy=(0., 0.), yaw_rad=0.,
                                    now_ns=1_000_000_000 + cycle * 100_000_000, cycle=cycle, navigator=FakeNavigator()))
        if a.stop:
            break
    assert a.stop and a.note == 'stuck' and cycle == 50


def test_escape_backs_away_from_an_obstacle_inside_the_margin_then_resumes():
    from neusymnav.contracts import GridState

    class Client:
        def infer(self, obs):
            return SimpleNamespace(detections=(), cap_reached=False)

    res, n = .05, 60
    states = np.zeros((n, n), np.int8)
    xs = -1.5 + (np.arange(n) + .5) * res
    states[:, (xs >= .25) & (xs <= .30)] = GridState.OCCUPIED                 # wall 0.25 m ahead of the robot
    grid = SimpleNamespace(states=states, floor_support=np.ones((n, n), bool), clearance=np.full((n, n), 2.),
                           resolution_m=res, origin_xy=(-1.5, -1.5), revision=1)

    class Blocked(FakeNavigator):
        def step(self, *a):
            return NavigationDecision(None, (), 0., 0., 1, 'robot_not_on_observed_free_cell')

    pol = B0Policy(b0_config(escape_after_s=3.0), categories=GoalCategories.load(), detector_factory=Client,
                   robot_height_m=1.5, projector=FakeProjector({}))
    pol.reset(episode())
    pol.begin_episode(floor_z_m=0.0, episode_tag='esc')
    xy, yaw, ns, reasons = [0., 0.], [0.], [1_000_000_000], []
    for cycle in range(120):
        a = pol.act(SimpleNamespace(nav=grid, robot_xy=tuple(xy), yaw_rad=yaw[0], now_ns=ns[0], cycle=cycle,
                                    navigator=Blocked()))
        assert not a.stop
        d = a.decision
        reasons.append(d.reason)
        if d.reason == 'escape_step':
            xy[0] += .05 * math.cos(yaw[0]); xy[1] += .05 * math.sin(yaw[0])
        elif d.reason == 'escape_rotate':
            yaw[0] = wrap(yaw[0] + d.desired_yaw_radps * .5)
        ns[0] += 100_000_000
        if any(e['note'] == 'escape_done:clear' for e in pol.events):
            break
    assert 'escape_step' in reasons and xy[0] < -.05                          # moved away from the wall
    assert pol.escapes[0]['kind'] == 'clearance' and pol.escapes[0]['result'] == 'clear'
    assert pol.state == 'EXPLORE'


# ------------------------------------------------------------------ b0-policy-v3 (dev2-diag follow-up)

def _wall_grid(x0, x1, res=.05, n=60):
    from neusymnav.contracts import GridState
    states = np.zeros((n, n), np.int8)
    xs = -1.5 + (np.arange(n) + .5) * res
    states[:, (xs >= x0) & (xs <= x1)] = GridState.OCCUPIED
    return SimpleNamespace(states=states, floor_support=np.ones((n, n), bool), clearance=np.full((n, n), 2.),
                           resolution_m=res, origin_xy=(-1.5, -1.5), revision=1)


class _Quiet:
    def infer(self, obs):
        return SimpleNamespace(detections=(), cap_reached=False)


def _drive(pol, grid, navigator, cycles, xy=(0., 0.), stop_when=None):
    xy, yaw, ns, reasons = list(xy), [0.], [1_000_000_000], []
    for cycle in range(cycles):
        a = pol.act(SimpleNamespace(nav=grid, robot_xy=tuple(xy), yaw_rad=yaw[0], now_ns=ns[0], cycle=cycle,
                                    navigator=navigator))
        if a.stop:
            break
        d = a.decision
        reasons.append(d.reason)
        if d.reason == 'escape_step':
            xy[0] += .05 * math.cos(yaw[0]); xy[1] += .05 * math.sin(yaw[0])
        elif d.reason == 'escape_rotate':
            yaw[0] = wrap(yaw[0] + d.desired_yaw_radps * .5)
        ns[0] += 100_000_000
        if stop_when is not None and stop_when(pol):
            break
    return reasons, xy


def test_v3_clearance_escape_ends_once_the_planner_can_start_here():
    grid = _wall_grid(.25, .30)                                           # clearance ~0.27 m < 0.3375 m

    class Nav(FakeNavigator):
        def step(self, *a):
            return NavigationDecision(None, (), 0., 0., 1, 'robot_not_on_observed_free_cell')

        def start_traversable(self, nav, xy):
            return xy[0] <= -.04                                          # one step back is enough here

    pol = B0Policy(b0_config(escape_after_s=3.0, escape_exit_on_start_traversable=True), categories=GoalCategories.load(),
                   detector_factory=_Quiet, robot_height_m=1.5, projector=FakeProjector({}))
    pol.reset(episode()); pol.begin_episode(floor_z_m=0.0, episode_tag='v3a')
    reasons, xy = _drive(pol, grid, Nav(), 120, stop_when=lambda p: any(e['note'].startswith('escape_done') for e in p.events))
    assert pol.escapes[0]['kind'] == 'clearance' and pol.escapes[0]['result'] == 'clear'
    assert reasons.count('escape_step') == 1 and -.06 < xy[0] < -.04        # left after one 5 cm step


def test_v3_second_escape_at_one_spot_nudges_instead_of_turning_again():
    grid = _wall_grid(.40, .45)                                           # clearance ~0.42 m: planner is fine

    class Nav(FakeNavigator):
        def step(self, *a):
            return NavigationDecision('f', ((0, 0), (1, 0)), 0., 0., 1, 'tracking')   # guard keeps blocking

        def start_traversable(self, nav, xy):
            return True

    pol = B0Policy(b0_config(escape_after_s=3.0, escape_exit_on_start_traversable=True, escape_nudge=True),
                   categories=GoalCategories.load(), detector_factory=_Quiet, robot_height_m=1.5,
                   projector=FakeProjector({}))
    pol.reset(episode()); pol.begin_episode(floor_z_m=0.0, episode_tag='v3b')
    reasons, xy = _drive(pol, grid, Nav(), 400, stop_when=lambda p: len(p.escapes) >= 2 and 'result' in p.escapes[1])
    assert [e['kind'] for e in pol.escapes] == ['turn', 'nudge']
    assert pol.escapes[1]['result'] == 'nudged' and math.hypot(*xy) >= .10 and 'escape_step' in reasons


def test_v3_goal_reached_beyond_the_stop_distance_rejects_the_candidate():
    class Client:
        def infer(self, obs):
            return SimpleNamespace(detections=(det('chair', .7),), cap_reached=False)

    chair = box(3.0, -0.2, size=0.4)

    class Nav(FakeNavigator):
        def step_toward(self, nav, xy, yaw, now, select, goal_id):
            self.last_approach = dict(tag='toward', goal_cells=5, goal_xy=list(xy))
            return NavigationDecision(goal_id, (), 0., 0., 1, 'goal_reached')

    pol = B0Policy(b0_config(approach_reached_far_cycles=5), categories=GoalCategories.load(),
                   detector_factory=Client, robot_height_m=1.5, projector=FakeProjector({'chair': chair}))
    pol.reset(episode()); pol.begin_episode(floor_z_m=0.0, episode_tag='v3c')
    navigator, ns = Nav(), [1_000_000_000]
    for cycle in range(60):
        if pol.wants_frame(ns[0], (0., 0.), 0.):
            pol.on_frame(SimpleNamespace(key=SimpleNamespace(frame_index=cycle), capture_monotonic_ns=ns[0],
                                         T_world_camera=np.eye(4), K=np.eye(3)), (0., 0.), 0.)
        pol.act(SimpleNamespace(nav=SimpleNamespace(revision=1), robot_xy=(0., 0.), yaw_rad=0., now_ns=ns[0],
                                cycle=cycle, navigator=navigator))
        ns[0] += 300_000_000
        if any(e['note'].startswith('reject') for e in pol.events):
            break
    assert [e['note'] for e in pol.events if e['note'].startswith('reject')] == ['reject:approach_goal_reached_far']


@pytest.mark.parametrize('survives', [False, True])
def test_v3_escape_does_not_restart_the_approach_timeout(survives):
    pol = B0Policy(b0_config(approach_timer_survives_escape=survives), categories=GoalCategories.load(),
                   detector_factory=_Quiet, robot_height_m=1.5, projector=FakeProjector({}))
    pol.reset(episode())
    c = lambda t: SimpleNamespace(now_ns=t, cycle=0, navigator=FakeNavigator())
    pol._to('APPROACH', c(1_000), 'confirmed')
    pol._to('ESCAPE', c(2_000), 'escape:turn')
    pol._to('APPROACH', c(3_000), 'escape_done:turned')
    assert pol._approach_since_ns == (1_000 if survives else 3_000)
    pol._to('APPROACH', c(4_000), 'confirmed')                              # a new approach restarts it
    assert pol._approach_since_ns == 4_000


def test_navigator_start_traversable_uses_the_planner_mask():
    from neusymnav.contracts import GridState
    navigator = Navigator(geometry(), clock_domain='host_monotonic:test')
    assert navigator.start_traversable(nav(), (.75, .75))
    s = np.zeros((15, 15), np.int8); s[7, 8] = GridState.OCCUPIED           # 0.1 m from the robot's cell
    assert not navigator.start_traversable(nav(s), (.75, .75))
    assert not navigator.start_traversable(nav(), (5., 5.))                 # outside the map


def test_bootstrap_probe_explains_a_blocked_fresh_frame(tmp_path):
    from neusymnav.mapping.occupancy import NavMapper, RobotGeometry
    from neusymnav.objectnav.bootstrap_probe import probe
    from test_navmap import down
    robot = RobotGeometry('cylinder-v1', .2, 1., .1, .05)
    m = NavMapper(robot=robot, floor_z_m=3., floor_datum_source='scene-calibration:v1', calibration_hash='a' * 64,
                  resolution_m=.05, tile_size_cells=16, sampling_stride=1, snapshot_radius_m=3., tile_archive_dir=tmp_path)
    m.update(down(0, size=201, focal=60.))
    n = m.update(down(1, size=201, focal=60.))
    clean = probe(m, down(2, size=201, focal=60.), n, (0., 0.), 0., body_only=True, corridor_m=0.)
    assert clean['bootstrap']['ready'] and clean['not_free'] == 0
    o = down(3, size=201, focal=60.)
    depth = np.array(o.depth_m, copy=True)
    depth[95:106, 106:113] = 1.5                                            # a box 0.5 m high, ~0.1-0.2 m to the side
    o = replace(o, depth_m=depth)
    hit = probe(m, o, n, (0., 0.), 0., body_only=True, corridor_m=0.)
    assert not hit['bootstrap']['ready'] and hit['not_free'] > 0
    assert hit['kinds'].get('occupied_body', 0) > 0
    assert all(c['d_m'] <= .25 for c in hit['cells_detail'])
