"""Paper-protocol mode (docs/objectnav/paper-protocol-plan.md): config, map, planner, runner."""
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.objectnav.paper.obstacle_map import ObstacleMap
from neusymnav.objectnav.paper.planner import DistanceField, heading_action, waypoint
from neusymnav.objectnav.paper.protocol import PaperProtocol
from neusymnav.objectnav.paper.runner import PaperRunner
from neusymnav.objectnav.paper.policies import ScriptedPolicy
from neusymnav.objectnav.paper.sim_client import PaperObs

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'configs/objectnav/paper-hm3d-v1.json'


def _data():
    return json.loads(CONFIG.read_text())


# ---------------------------------------------------------------- protocol

def test_paper_protocol_matches_the_challenge_values():
    p = PaperProtocol.load(CONFIG)
    assert (p.agent_height_m, p.agent_radius_m) == (0.88, 0.18)
    assert p.resolution_hw == (480, 640) and p.hfov_deg == 79.0 and p.camera_height_m == 0.88
    assert (p.depth_min_m, p.depth_max_m) == (0.5, 5.0)
    assert (p.forward_step_m, p.turn_deg, p.tilt_deg) == (0.25, 30.0, 30.0)
    assert p.allow_sliding is False and p.max_steps == 500 and p.success_distance_m == 0.1
    assert len(p.sha256) == 64 and PaperProtocol.load(CONFIG).sha256 == p.sha256


@pytest.mark.parametrize('patch', [
    dict(allow_sliding=0), dict(allow_sliding=True), dict(max_steps=500.0), dict(max_steps=0), dict(extra=1),
    dict(agent=dict(height_m=0.88)), dict(camera=dict(_data()['camera'], depth_min_m=6.0)),
    dict(actions=dict(forward_step_m=0.25, turn_deg=30.0)), dict(schema_version=2),
])
def test_paper_protocol_rejects_bad_values(patch):
    with pytest.raises(ValueError):
        PaperProtocol.from_dict(dict(_data(), **patch))


def test_paper_protocol_hash_changes_with_content():
    assert PaperProtocol.from_dict(dict(_data(), max_steps=499)).sha256 != PaperProtocol.load(CONFIG).sha256


def test_worker_depth_clip_keeps_missing_distinct_from_far():
    from neusymnav.objectnav.paper.sim_worker import clip_depth
    out = clip_depth(np.array([[0.2, 1.0, 7.0, 0.0, np.nan]], np.float32), 0.5, 5.0)
    assert out.tolist() == [[0.5, 1.0, 5.0, 0.0, 0.0]]


# ---------------------------------------------------------------- map

def _camera_obs(depth, *, cam_xyz=(0.0, 0.0, 0.88), yaw=0.0, hfov_deg=79.0, dmax=5.0):
    """Forward pinhole camera (optical z = heading, x right, y down) at cam_xyz, canonical z-up."""
    h, w = depth.shape
    f = (w / 2) / math.tan(math.radians(hfov_deg) / 2)
    K = np.array([[f, 0, (w - 1) / 2], [0, f, (h - 1) / 2], [0, 0, 1.0]])
    fwd = np.array([math.cos(yaw), math.sin(yaw), 0.0])
    right = np.array([math.sin(yaw), -math.cos(yaw), 0.0])
    down = np.array([0.0, 0.0, -1.0])
    T = np.eye(4)
    T[:3, 0], T[:3, 1], T[:3, 2], T[:3, 3] = right, down, fwd, cam_xyz
    depth = np.asarray(depth, np.float32)
    return SimpleNamespace(depth_m=depth, valid_depth=(depth >= 0.5) & (depth < dmax), K=K, T_world_camera=T)


def _wall_obs(distance_m):
    """A vertical wall ``distance_m`` ahead of a camera at 0.88 m: axial depth = distance everywhere."""
    return _camera_obs(np.full((48, 64), distance_m, np.float32))


def test_obstacle_map_marks_a_wall_and_the_free_space_before_it():
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=20.0, stride=1, ray_stride=1)
    m.update(_wall_obs(2.0), robot_xy=(0.0, 0.0), base_z_m=0.0)
    wall = m.cell((2.0, 0.0))
    assert m.obstacle[wall] and m.explored[wall]
    for x in (0.5, 1.0, 1.5):
        cell = m.cell((x, 0.0))
        assert m.explored[cell] and not m.obstacle[cell]
    assert not m.explored[m.cell((3.0, 0.0))]          # behind the wall: unknown
    assert not m.explored[m.cell((-2.0, 0.0))]         # behind the camera: unknown


def test_missing_depth_leaves_unknown_but_a_far_ray_clears_space():
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=12.0)
    cell = m.cell((0.5, 0.0))
    m.update(_wall_obs(0.0), robot_xy=(0.0, 0.0), base_z_m=0.0)
    assert not m.explored[cell]
    m.update(_wall_obs(5.0), robot_xy=(0.0, 0.0), base_z_m=0.0)
    assert m.explored[cell] and not m.obstacle[cell]


def test_obstacle_map_ignores_points_above_the_body_and_climbable_points():
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=20.0, stride=1, ray_stride=1)
    obs = _wall_obs(2.0)
    T = obs.T_world_camera.copy()
    T[2, 3] = 2.5                                       # camera far above the body band: points at 1.7-3.3 m
    obs.T_world_camera = T
    m.update(obs, robot_xy=(0.0, 0.0), base_z_m=0.0)
    assert not m.obstacle.any()


def test_obstacle_map_keeps_the_body_cells_free_and_marks_collisions():
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=10.0)
    m.update(_wall_obs(4.0), robot_xy=(0.0, 0.0), base_z_m=0.0)
    m.level.obstacle[m.cell((0.0, 0.0))] = True
    m._clear_body((0.0, 0.0))
    assert not m.obstacle[m.cell((0.0, 0.0))]
    m.mark_collision((0.0, 0.0), 0.0)
    assert m.obstacle[m.cell((0.28, 0.0))] and not m.obstacle[m.cell((0.0, 0.0))]
    assert m.collision_marks == 1


def test_obstacle_map_keeps_one_layer_per_floor():
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=10.0)
    m.update(_wall_obs(2.0), robot_xy=(0.0, 0.0), base_z_m=0.0)
    m.update(_wall_obs(2.0), robot_xy=(0.0, 0.0), base_z_m=3.0)
    assert len(m.levels) == 2 and m.level.z_m == 3.0
    m.update(_wall_obs(2.0), robot_xy=(0.0, 0.0), base_z_m=0.1)
    assert len(m.levels) == 2 and m.level.z_m == 0.0


def test_frontiers_sit_between_free_and_unknown():
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=10.0)
    m.level = m._select_level(0.0)
    m.level.explored[90:110, 90:110] = True
    trav = m.traversable((0.0, 0.0), 0.0)
    fronts = m.frontiers(trav, min_cells=5)
    assert len(fronts) == 1 and fronts[0].size == 76      # the ring of the 20 x 20 square


# ---------------------------------------------------------------- planner

def test_distance_field_goes_around_a_wall():
    mask = np.ones((20, 20), bool)
    mask[0:15, 10] = False
    field = DistanceField(mask, (2, 2))
    path = field.path((2, 18))
    assert path[0] == (2, 2) and path[-1] == (2, 18)
    assert all(mask[c] for c in path)
    assert field.distance((2, 18)) > 16                     # longer than the straight line
    mask2 = mask.copy()
    mask2[:, 10] = False
    assert DistanceField(mask2, (2, 2)).path((2, 18)) == []


def test_heading_action_and_waypoint():
    assert heading_action((0, 0), 0.0, (1, 0)) == 'move_forward'
    assert heading_action((0, 0), 0.0, (0, 1)) == 'turn_left'
    assert heading_action((0, 0), 0.0, (0, -1)) == 'turn_right'
    assert heading_action((0, 0), 0.0, (1, math.tan(math.radians(14)))) == 'move_forward'
    assert waypoint([(0.1, 0), (0.3, 0), (0.6, 0), (1.0, 0)], (0, 0), 0.5) == (0.6, 0)
    assert waypoint([(0.1, 0)], (0, 0), 0.5) == (0.1, 0)


# ---------------------------------------------------------------- runner

class FakeSim:
    """Moves 0.25 m per forward on an open plane, collides past x = 1.0 m; STOP ends the episode."""
    def __init__(self, max_steps=500):
        self.max_steps, self.closed = max_steps, False

    def _obs(self, collided=False):
        done = self.done or self.step >= self.max_steps
        return PaperObs(observation=None, step=self.step, collided=collided, done=done,
                        position_h=(self.x, 0.0, -self.y), robot_xy=(self.x, self.y), z_m=0.0,
                        yaw_rad=self.yaw, tilt_rad=0.0)

    def reset(self, episode, episode_id):
        self.x = self.y = self.yaw = 0.0
        self.step, self.done = 0, False
        return self._obs()

    def act(self, action):
        assert not self.done
        self.step += 1
        collided = False
        if action == 'stop':
            self.done = True
        elif action == 'move_forward':
            nx = self.x + 0.25 * math.cos(self.yaw)
            if nx > 1.0 + 1e-9:
                collided = True
            else:
                self.x, self.y = nx, self.y + 0.25 * math.sin(self.yaw)
        elif action in ('turn_left', 'turn_right'):
            self.yaw += math.radians(30) * (1 if action == 'turn_left' else -1)
        return self._obs(collided)

    def close(self):
        self.closed = True


def _episode(uid='hm3d_v2/val/S/1'):
    return SimpleNamespace(uid=uid, scene_path='/s.glb', object_category='chair')


def test_paper_runner_records_a_scorer_trajectory(tmp_path):
    p = PaperProtocol.load(CONFIG)
    sim = FakeSim()
    runner = PaperRunner(p, out_dir=tmp_path, run_id='t1', sim_factory=lambda: sim, log=lambda *_: None,
                         policy_factory=lambda: ScriptedPolicy(['move_forward'] * 6 + ['turn_left']))
    out = runner.run([_episode()])
    rec = json.loads(out.read_text().splitlines()[0])
    assert rec['called_stop'] is True and rec['steps'] == 8
    assert rec['positions'][0] == [0.0, 0.0, -0.0] and len(rec['positions']) == 9
    d = rec['diagnostics']
    assert d['collisions'] == 2 and d['actions'] == {'move_forward': 6, 'stop': 1, 'turn_left': 1}
    assert d['end_reason'] == 'policy_stop' and abs(d['path_m'] - 1.0) < 1e-9
    assert d['protocol_sha256'] == p.sha256 and sim.closed
    # resume: nothing is re-run
    runner.run([_episode()])
    assert len(out.read_text().splitlines()) == 1


def test_paper_runner_ends_at_the_step_budget_without_stop(tmp_path):
    p = PaperProtocol.load(CONFIG)
    runner = PaperRunner(p, out_dir=tmp_path, run_id='t2', sim_factory=lambda: FakeSim(max_steps=5),
                         log=lambda *_: None, policy_factory=lambda: ScriptedPolicy(['turn_left'] * 50))
    rec = json.loads(runner.run([_episode()]).read_text())
    assert rec['called_stop'] is False and rec['steps'] == 5 and rec['diagnostics']['end_reason'] == 'max_steps'


def test_paper_runner_rejects_unknown_actions(tmp_path):
    p = PaperProtocol.load(CONFIG)
    runner = PaperRunner(p, out_dir=tmp_path, run_id='t3', sim_factory=FakeSim, log=lambda *_: None,
                         policy_factory=lambda: ScriptedPolicy(['jump']))
    with pytest.raises(ValueError):
        runner.run([_episode()])


def test_policy_only_receives_the_category_and_uid(tmp_path):
    class Policy:
        def reset(self, task):
            assert vars(task) == {'uid': 'hm3d_v2/val/S/1', 'object_category': 'chair'}

        def act(self, ctx):
            self.reset(ctx.episode)
            return 'stop'

    episode = _episode()
    episode.goals = ['evaluator only']
    runner = PaperRunner(PaperProtocol.load(CONFIG), out_dir=tmp_path, run_id='t4',
                         sim_factory=FakeSim, log=lambda *_: None, policy_factory=Policy)
    assert json.loads(runner.run([episode]).read_text())['called_stop']


def test_distance_field_with_robot_outside_map_cannot_find_a_path():
    grid = np.ones((4, 4), dtype=bool)
    field = DistanceField(grid, (4, 1))
    assert field.path((3, 1)) == []
    assert field.nearest_reachable([(3, 1)]) is None


def test_obstacle_map_does_not_turn_a_lower_floor_into_obstacles():
    """Standing on a stair step 0.4 m up: the main floor seen below the base is no obstacle."""
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=20.0, stride=1, ray_stride=1)
    h, w = 48, 64
    obs = _camera_obs(np.full((h, w), 5.0, np.float32), cam_xyz=(0.0, 0.0, 0.4 + 0.88))
    K, T = obs.K, obs.T_world_camera
    rows, cols = np.mgrid[0:h, 0:w]
    ray_down = (rows - K[1, 2]) / K[1, 1]                    # camera y is down: z_world drop per unit depth
    with np.errstate(divide='ignore'):
        depth = np.where(ray_down > 0, (0.4 + 0.88) / ray_down, 5.0)   # the main floor at z = 0
    obs = _camera_obs(np.clip(depth, 0.5, 5.0).astype(np.float32), cam_xyz=(0.0, 0.0, 1.28))
    m.update(obs, robot_xy=(0.0, 0.0), base_z_m=0.4)
    assert not m.obstacle.any()


def _door_world(door_w=0.7, start_xy=(0.0, -1.6), yaw_deg=70.0, depth_m=0.0):
    """Wall along y = 0 with a door of ``door_w`` centred at x = 0.4 (a passage ``depth_m`` long);
    the robot starts below it."""
    from neusymnav.objectnav.paper.nav import NavConfig, PaperNav
    p = PaperProtocol.load(Path('configs/objectnav/paper-hm3d-v1.json'))
    nav = PaperNav(p, NavConfig(size_m=8.0))
    nav.map = ObstacleMap(origin_xy=(0.0, 0.0), size_m=8.0, agent_radius_m=p.agent_radius_m)
    lv = nav.map._select_level(0.0)
    lv.explored[:] = True
    wall = []
    for x in np.arange(-3.0, 3.0, 0.025):
        if abs(x - 0.4) > door_w / 2:
            wall.append((x, 0.0))
            lv.obstacle[nav.map.cell((x, 0.0))] = True
    for y in np.arange(0.0, depth_m, 0.025):
        for x in (0.4 - door_w / 2, 0.4 + door_w / 2):
            wall.append((x, y))
            lv.obstacle[nav.map.cell((x, y))] = True
    nav.robot_xy, nav.yaw = start_xy, math.radians(yaw_deg)
    return p, nav, np.array(wall)


def _drive(controller, door_w=0.7, start_xy=(0.0, -1.6), yaw_deg=70.0, steps=80, depth_m=0.0):
    """Discrete actions with no sliding: a forward step is refused if its end is closer than the
    body radius to the wall points (what the navmesh would do)."""
    p, nav, wall = _door_world(door_w, start_xy, yaw_deg, depth_m)
    nav.cfg.controller = controller
    goal = nav.map.cell((0.4, depth_m + 1.5))
    collisions = 0
    for _ in range(steps):
        nav._plan(nav.cfg.inflate_m)
        res = nav.go_to_cells([goal])
        if res.status == 'reached':
            return True, collisions
        if res.action is None:
            return False, collisions
        if res.action == 'move_forward':
            end = (nav.robot_xy[0] + 0.25 * math.cos(nav.yaw), nav.robot_xy[1] + 0.25 * math.sin(nav.yaw))
            seg = [(nav.robot_xy[0] + t * (end[0] - nav.robot_xy[0]), nav.robot_xy[1] + t * (end[1] - nav.robot_xy[1]))
                   for t in np.linspace(0, 1, 6)]
            if min(np.hypot(*(wall - q).T).min() for q in seg) < p.agent_radius_m:
                collisions += 1
                nav.blocked_streak += 1
                continue
            nav.blocked_streak = 0
            nav.robot_xy = end
        else:
            nav.blocked_streak = 0
            nav.yaw += math.radians(p.turn_deg) * (1 if res.action == 'turn_left' else -1)
        nav._recent.append(nav.robot_xy)
    return False, collisions


@pytest.mark.parametrize('yaw_deg', [10.0, 70.0, 130.0])
@pytest.mark.parametrize('depth_m', [0.0, 1.0])
def test_scored_controller_passes_a_narrow_passage_without_sliding(yaw_deg, depth_m):
    ok, collisions = _drive('scored', door_w=0.62, start_xy=(-0.6, -1.6), yaw_deg=yaw_deg, depth_m=depth_m, steps=120)
    assert ok and collisions == 0


def test_wall_penalty_keeps_paths_in_the_middle_of_a_door():
    p, nav, _ = _door_world(door_w=1.2)
    nav._plan(nav.cfg.inflate_m)
    path = nav.field.path(nav.map.cell((0.4, 1.5)))
    xs = [nav.map.xy(c)[0] for c in path if abs(nav.map.xy(c)[1]) < 0.03]
    assert xs and all(abs(x - 0.4) < 0.15 for x in xs)


def test_paper_action_audit_records_order_and_simulator_outcome(tmp_path):
    runner = PaperRunner(PaperProtocol.load(CONFIG), out_dir=tmp_path, run_id='audit',
                         sim_factory=FakeSim, log=lambda *_: None, action_audit=True,
                         policy_factory=lambda: ScriptedPolicy(['move_forward'] * 5 + ['turn_left']))
    record = json.loads(runner.run([_episode()]).read_text())
    trace = record['diagnostics']['action_audit']
    steps = trace['steps']
    assert trace['schema_version'] == 1 and len(steps) == record['steps']
    assert [row['dispatched_action'] for row in steps] == ['move_forward'] * 5 + ['turn_left', 'stop']
    assert steps[4]['collided'] and steps[4]['result_step'] == 5
    assert steps[5]['result_pose']['yaw_rad'] == pytest.approx(math.pi / 6)
    assert steps[0]['input_source'] is None
    assert steps[-1]['simulator_done'] and record['called_stop']


def test_action_audit_retains_terminal_observation_without_dispatch(tmp_path):
    from neusymnav.objectnav.paper.runner import PaperEnd

    class NoAction:
        def reset(self, episode):
            pass

        def act(self, context):
            return PaperEnd('frontier_exhausted')

    runner = PaperRunner(PaperProtocol.load(CONFIG), out_dir=tmp_path, run_id='terminal',
                         sim_factory=FakeSim, log=lambda *_: None, action_audit=True,
                         policy_factory=NoAction)
    result = json.loads(runner.run([_episode()]).read_text())
    trace = result['diagnostics']['action_audit']
    assert trace['steps'] == [] and result['steps'] == 0
    assert trace['terminal_observation']['input_step'] == 0
    assert trace['terminal_observation']['reason'] == 'frontier_exhausted'


def test_paper_simulator_receipt_distinguishes_collision_stop_and_missing_collision_flag():
    from neusymnav.objectnav.paper.sim_worker import PaperSim

    sim = PaperSim.__new__(PaperSim)
    sim.episode_id, sim.done, sim.steps, sim.tilt_steps = 'episode', False, 0, 0
    sim.config = {'max_steps': 10}
    emitted = []
    sim.sim = SimpleNamespace(
        step=lambda cmd: emitted.append(cmd) or ({'collided': True} if cmd == 'move_forward'
                                                else {'collided': None}),
        get_sensor_observations=lambda: {},
    )
    sim._observe = lambda raw, collided: dict(step=sim.steps, collided=collided, done=sim.done)
    blocked = sim.act('move_forward', action_receipt=True)['execution']
    assert blocked == dict(schema_version=1, action='move_forward', reason='collision_reported')
    missing = sim.act('turn_left', action_receipt=True)['execution']
    assert missing['reason'] == 'collision_flag_unavailable'
    stopped = sim.act('stop', action_receipt=True)['execution']
    assert stopped['reason'] == 'episode_stopped'
    assert emitted == ['move_forward', 'turn_left']


def test_paper_nav_audits_actual_unreachable_result():
    from neusymnav.objectnav.paper.nav import PaperNav

    nav = PaperNav(PaperProtocol.load(CONFIG))
    nav.decision_audit = []
    result = nav.go_to_cells([])
    assert result.action is None and result.status == 'unreachable'
    assert nav.decision_audit == [dict(status='unreachable', action=None, relaxed=False)]
