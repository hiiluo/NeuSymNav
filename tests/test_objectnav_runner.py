"""Lockstep runner plumbing with a fake simulator (no Habitat)."""
import json
from dataclasses import replace

import pytest

from neusymnav.objectnav.episodes import Episode, ObjectGoal
from neusymnav.objectnav.runner import (ExplorePolicy, LockstepRunner, PolicyAction, RunnerConfig,
                                        group_for_workers, habitat_xyz, measure_floor)
from test_navmap import down

DOMAIN = 'sim_lockstep:test'


class FakeSensor:
    """Moves a downward camera along x in simulated time; executes guarded commands only."""

    def __init__(self, cfg):
        self.cfg, self.x, self.now, self.index, self.closed = cfg, 0.0, 1_000_000_000, 0, False
        self.episode = cfg['episode_id']
        self.commands = []

    def reset(self, episode_id, *, position, rotation_xyzw):
        self.episode, self.x, self.index = episode_id, 0.0, 0

    def capture_navigation(self):
        obs = down(self.index, x=self.x, stamp=self.now, domain=DOMAIN)
        obs = replace(obs, key=replace(obs.key, episode_id=self.episode, sensor_id='downward-depth'))
        self.last, self.index, self.now = obs, self.index + 1, self.now + 1_000_000
        return obs

    def robot_pose(self, obs):
        assert obs is self.last
        return dict(source=obs.key, robot_xy=(self.x, 0.0), yaw_rad=0.0, pose_version=0,
                    capture_monotonic_ns=obs.capture_monotonic_ns, clock_domain=DOMAIN)

    def execute(self, command):
        self.commands.append(command)
        assert command.clock_domain == DOMAIN and command.issued_monotonic_ns <= self.now
        pulse = max(0, command.deadline_monotonic_ns - self.now)
        moved = bool(command.linear_mps or command.yaw_radps) and pulse > 0
        if moved:
            self.x += command.linear_mps * pulse / 1e9
        self.now += max(pulse if moved else 0, 100_000_000)
        return dict(executed=moved, reason=None if moved else 'expired_or_zero')

    def close(self):
        self.closed = True


def identity_snap(eps):
    return {e.uid: dict(snapped=list(e.start_position), shift_xz_m=0.0, shift_y_m=0.0, navigable=True) for e in eps}


def episode(eid='0', y=0.1):
    return Episode('hm3d_v2', 'val_mini', eid, 'hm3d_v0.2/minival/00800-TEEsavR23oF/TEEsavR23oF.basis.glb',
                   'TEEsavR23oF', '/scenes/TEEsavR23oF.basis.glb', '/cfg/basis.json', '/cfg/annotated.json',
                   (1.0, y, 2.0), (0.0, 0.0, 0.0, 1.0), 'chair', 3.0,
                   (ObjectGoal(1, 'chair', (3, 0, 4), ((2.0, 0.1, 3.0),)),))


def config(**kw):
    base = dict(sensor={'motion_adapter': 'planar_fixed_y_v1'},
                robot=dict(geometry_id='cylinder-v1', radius_m=.10, height_m=1., margin_m=0., near_ground_tolerance_m=.05),
                mapper=dict(resolution_m=.1, tile_size_cells=16, sampling_stride=1, snapshot_radius_m=3.),
                navigator={}, max_cycles=40)
    base.update(kw)
    return RunnerConfig(**base)


class ForwardPolicy:
    """Asks for straight motion so the guard/execute/record path is exercised."""
    name = 'forward_test'

    def reset(self, episode):
        self.n = 0

    def act(self, ctx):
        from neusymnav.contracts import NavigationDecision
        self.n += 1
        if self.n > 6:
            return PolicyAction(True, note='done')
        x, y = ctx.robot_xy
        return PolicyAction(False, NavigationDecision('g', ((x, y), (x + .3, y)), .15, 0., ctx.nav.revision, 'tracking'))


def test_geometry_helpers():
    assert habitat_xyz((1.5, -2.0), 0.2) == [1.5, 0.2, 2.0]
    floor = measure_floor(down(0))
    assert floor['floor_z_m'] == pytest.approx(3.0) and floor['samples'] == 400


def test_runner_records_guarded_motion_resumes_and_is_deterministic(tmp_path):
    sensors = []

    def factory(cfg):
        sensors.append(FakeSensor(cfg))
        return sensors[-1]

    eps = [episode('0'), episode('1')]
    outs = []
    for run in ('a', 'b'):
        runner = LockstepRunner(config(), habitat_python=tmp_path / 'py', out_dir=tmp_path / run, run_id='t' + run,
                                policy_factory=ForwardPolicy, sensor_factory=factory, start_snapper=identity_snap,
                                log=lambda *_: None)
        out = runner.run(eps)
        outs.append([json.loads(l) for l in out.read_text().splitlines()])
    a, b = outs
    assert [r['uid'] for r in a] == ['hm3d_v2/val_mini/TEEsavR23oF/0', 'hm3d_v2/val_mini/TEEsavR23oF/1']
    assert all(r['called_stop'] and r['clock_domain'] == DOMAIN for r in a)
    moved = a[0]['positions'][-1][0] - a[0]['positions'][0][0]
    assert moved > 0.1 and a[0]['diagnostics']['executed_commands'] > 0
    assert a[0]['positions'][0] == [0.0, 0.1, -0.0]                   # canonical -> Habitat frame
    for ra, rb in zip(a, b):                                          # same inputs -> same trajectory
        assert ra['positions'] == rb['positions'] and ra['sim_time_s'] == rb['sim_time_s']
    assert len(sensors) == 2 and all(s.closed for s in sensors)       # one worker per group, closed
    assert all(c.deadline_monotonic_ns - c.issued_monotonic_ns <= 300_000_000 for c in sensors[0].commands)
    # resume: a second run in the same directory skips finished episodes
    runner = LockstepRunner(config(), habitat_python=tmp_path / 'py', out_dir=tmp_path / 'a', run_id='ta',
                            policy_factory=ForwardPolicy, sensor_factory=factory, start_snapper=identity_snap,
                            log=lambda *_: None)
    runner.run(eps)
    assert len((tmp_path / 'a/trajectories.jsonl').read_text().splitlines()) == 2


def test_explore_policy_stops_on_cycle_budget(tmp_path):
    runner = LockstepRunner(config(), habitat_python=tmp_path / 'py', out_dir=tmp_path / 'e', run_id='e',
                            policy_factory=lambda: ExplorePolicy(stop_after_cycles=3), sensor_factory=FakeSensor,
                            start_snapper=identity_snap, log=lambda *_: None)
    rec = json.loads(runner.run([episode()]).read_text())
    assert rec['called_stop'] and rec['diagnostics']['end_reason'] == 'policy_stop:cycle_budget' and rec['steps'] == 3


def test_workers_grouped_by_scene_and_start_height_and_bad_run_id():
    groups = group_for_workers([episode('0', .1), episode('1', .1), episode('2', 3.2)])
    assert [len(g) for g in groups] == [2, 1]
    with pytest.raises(ValueError):
        LockstepRunner(config(), habitat_python='x', out_dir='y', run_id='bad id', policy_factory=ExplorePolicy)


def test_start_is_snapped_to_robot_navmesh_or_recorded_as_not_navigable(tmp_path):
    seen = []

    def factory(cfg):
        seen.append(cfg['initial_position'])
        return FakeSensor(cfg)

    def snapper(eps):
        return {eps[0].uid: dict(snapped=[1.0, 0.25, 2.0], shift_xz_m=0.0, shift_y_m=0.15, navigable=True),
                eps[1].uid: dict(snapped=[1.9, 0.1, 2.0], shift_xz_m=0.9, shift_y_m=0.0, navigable=True)}

    runner = LockstepRunner(config(), habitat_python=tmp_path / 'py', out_dir=tmp_path / 's', run_id='s',
                            policy_factory=lambda: ExplorePolicy(stop_after_cycles=2), sensor_factory=factory,
                            start_snapper=snapper, log=lambda *_: None)
    rows = [json.loads(l) for l in runner.run([episode('0'), episode('1')]).read_text().splitlines()]
    by = {r['uid'].rsplit('/', 1)[1]: r for r in rows}
    assert seen == [[1.0, 0.25, 2.0]]                                   # worker launched at the snapped height
    assert by['0']['positions'][0][1] == 0.25 and by['0']['diagnostics']['start_snap']['shift_y_m'] == 0.15
    assert by['1']['evidence'] == {'start_not_navigable': True} and by['1']['steps'] == 0
    assert json.loads((tmp_path / 's/start_snap.json').read_text()).keys() == {r['uid'] for r in rows}
