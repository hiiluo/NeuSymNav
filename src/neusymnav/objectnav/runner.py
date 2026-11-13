"""Deterministic lockstep ObjectNav episode runner (phase 1 skeleton).

One thread, one cycle = navigation capture -> NavMapper -> policy -> MotionGuard
-> execute. The Habitat worker runs through ``sim_worker_entry`` so time is the
simulator's (``sim_lockstep:`` domain) and every command moves the robot by an
amount that depends only on the command. The realtime demo is untouched.

Privileged data stays out of the robot: the runner only gives the policy the
episode's object CATEGORY; start pose goes to the simulator, view points and
geodesics are used only by the offline scorer (tools/objectnav/score_trajectories.py).

Each episode measures its own floor from the downward depth camera at the start
pose (same method as tools/prepare_local_maps.py), because HM3D houses have
several floors and the navmesh height is not the visual floor.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field, replace
from itertools import groupby
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

from ..contracts import NavigationDecision
from .episodes import Episode

SIM_ENTRY = Path(__file__).with_name('sim_worker_entry.py')
SNAP_SCRIPT = Path(__file__).with_name('start_snap.py')
MAX_START_SHIFT_M = 0.30      # farther than this from the episode start = not the same task
REPO_SRC = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- geometry

def habitat_xyz(robot_xy, floor_y: float) -> List[float]:
    """canonical_z_up_v1 (x, y) -> Habitat new_y_up_v1 (x, y_h, z_h); inverse of
    the worker's world matrix [[1,0,0],[0,0,-1],[0,1,0]]."""
    x, y = float(robot_xy[0]), float(robot_xy[1])
    return [x, float(floor_y), -y]


def _floor_points(observation, rows, cols):
    depth = np.asarray(observation.depth_m, dtype=np.float64)
    z = depth[rows, cols]
    k = np.asarray(observation.K, dtype=np.float64)
    rays = np.stack(((cols - k[0, 2]) * z / k[0, 0], (rows - k[1, 2]) * z / k[1, 1], z, np.ones_like(z)), axis=-1)
    world = rays @ np.asarray(observation.T_world_camera, dtype=np.float64).T
    return world[..., 2][np.asarray(observation.valid_depth)[rows, cols]]


def measure_floor(observation, *, patch: int = 10, max_spread_m: float = 0.03,
                  pose_z_m: Optional[float] = None) -> dict:
    """World height of the floor under the robot from the downward depth camera.

    measured-downward-depth-v1: median of the flat centre patch. When the
    centre patch is not flat (an object edge or a step under the camera at the
    episode start), measured-downward-depth-mode-v1: the densest 3 cm height
    band over the whole image, accepted only if it holds >= 25 % of the valid
    pixels. Cluttered starts: with ``pose_z_m`` (the simulator pose height of
    the robot base) measured-downward-depth-near-pose-v1 takes the densest
    band within +-0.2 m of it (>= 2 % of the pixels), and otherwise
    simulator-pose-height-v1 uses the pose height itself.
    """
    h, w = np.asarray(observation.depth_m).shape
    yy, xx = np.mgrid[h // 2 - patch:h // 2 + patch, w // 2 - patch:w // 2 + patch]
    values = _floor_points(observation, yy, xx)
    if values.size < (2 * patch) ** 2 // 2:
        raise ValueError('floor patch has too few valid depth pixels')
    p05, p95 = float(np.quantile(values, .05)), float(np.quantile(values, .95))
    base = dict(samples=int(values.size), source=observation.key.sensor_id, frame_index=observation.key.frame_index)
    if p95 - p05 <= max_spread_m:
        return dict(base, method='measured-downward-depth-center-patch-v1', floor_z_m=float(np.median(values)),
                    p05_m=p05, p95_m=p95)
    yy, xx = np.mgrid[0:h:2, 0:w:2]
    allv = np.sort(_floor_points(observation, yy, xx))
    if allv.size < 100:
        raise ValueError('floor patch is not flat (spread %.3f m) and too few pixels for the mode' % (p95 - p05))
    band = 0.03
    ends = np.searchsorted(allv, allv + band, side='right')
    counts = ends - np.arange(allv.size)
    i = int(np.argmax(counts))
    chosen = allv[i:ends[i]]
    share = float(chosen.size) / allv.size
    extra = dict(centre_spread_m=round(p95 - p05, 3))
    if share >= 0.25:
        return dict(base, **extra, method='measured-downward-depth-mode-v1', floor_z_m=float(np.median(chosen)),
                    samples=int(chosen.size), share=round(share, 3), p05_m=float(chosen.min()), p95_m=float(chosen.max()))
    if pose_z_m is None:
        raise ValueError('floor patch is not flat (spread %.3f m); densest 3 cm band holds only %.0f %%'
                         % (p95 - p05, 100 * share))
    near = allv[np.abs(allv - pose_z_m) <= 0.2]
    if near.size >= 0.02 * allv.size:
        e = np.searchsorted(near, near + band, side='right')
        j = int(np.argmax(e - np.arange(near.size)))
        sel = near[j:e[j]]
        if sel.size >= 0.02 * allv.size:
            return dict(base, **extra, method='measured-downward-depth-near-pose-v1', floor_z_m=float(np.median(sel)),
                        samples=int(sel.size), share=round(sel.size / allv.size, 3), pose_z_m=float(pose_z_m),
                        p05_m=float(sel.min()), p95_m=float(sel.max()))
    return dict(base, **extra, method='simulator-pose-height-v1', floor_z_m=float(pose_z_m), samples=0,
                share=0.0, pose_z_m=float(pose_z_m), p05_m=float(pose_z_m), p95_m=float(pose_z_m))


# ---------------------------------------------------------------- policies

@dataclass
class StepContext:
    episode: Episode            # policy may read object_category only
    nav: object                 # NavSnapshot
    navigation_obs: object      # depth-only Observation
    robot_xy: tuple
    yaw_rad: float
    now_ns: int
    cycle: int
    navigator: object


@dataclass
class PolicyAction:
    stop: bool
    decision: Optional[NavigationDecision] = None
    note: str = ''


class ExplorePolicy:
    """Validation policy: frontier exploration with the project Navigator,
    STOP after ``stop_after_cycles`` or when frontiers stay exhausted."""
    name = 'lockstep_explore'

    def __init__(self, stop_after_cycles: int = 400, exhausted_cycles: int = 30):
        self.stop_after_cycles, self.exhausted_cycles = stop_after_cycles, exhausted_cycles
        self._exhausted = 0

    def reset(self, episode: Episode) -> None:
        self._exhausted = 0

    def act(self, ctx: StepContext) -> PolicyAction:
        if ctx.cycle >= self.stop_after_cycles:
            return PolicyAction(True, note='cycle_budget')
        decision = ctx.navigator.step(ctx.nav, ctx.robot_xy, ctx.yaw_rad, ctx.now_ns)
        self._exhausted = self._exhausted + 1 if decision.reason == 'no_frontiers' else 0
        if self._exhausted >= self.exhausted_cycles:
            return PolicyAction(True, decision, note='frontiers_exhausted')
        return PolicyAction(False, decision)


# ---------------------------------------------------------------- runner

@dataclass
class RunnerConfig:
    sensor: dict                     # primary/navigation specs + motion_adapter, gpu_device_id
    robot: dict                      # RobotGeometry fields
    mapper: dict                     # NavMapper options
    navigator: dict                  # Navigator options (no tour)
    pulse_ms: int = 300
    rotation_pulse_ms: int = 500
    start_unknown_tolerance: float = 0.2
    max_sim_s: float = 300.0
    max_cycles: int = 3000
    # Approved 12/11/2026 for ObjectNav lockstep runs (defaults = phase-1 behaviour):
    planar_height_tolerance_m: float = 0.05   # planar adapter accepts navmesh steps within this height
    escape: bool = False                      # MotionGuard(escape=True): body-radius escape commands
    column_fallback_cells: int = 0            # MotionGuard body-column fallback (approved 12/11/2026); 0 = off

    def __post_init__(self):
        if not 0.05 <= float(self.planar_height_tolerance_m) <= 0.15:
            raise ValueError('planar_height_tolerance_m must be in [0.05, 0.15]')
        if type(self.escape) is not bool:
            raise ValueError('escape must be boolean')
        if type(self.column_fallback_cells) is not int or not 0 <= self.column_fallback_cells <= 12:
            raise ValueError('column_fallback_cells must be an int in [0, 12]')

    @classmethod
    def load(cls, path: Path) -> 'RunnerConfig':
        data = json.loads(Path(path).read_text())
        if data.get('schema_version') != 1:
            raise ValueError('runner config schema_version must be 1')
        data.pop('schema_version')
        data.pop('description', None)
        return cls(**data)


def _safe_episode_id(index: int, episode: Episode) -> str:
    token = re.sub(r'[^A-Za-z0-9_.-]', '-', '%s-%s' % (episode.scene_short, episode.episode_id))
    return 'objnav-%05d-%s' % (index, token)


def group_for_workers(episodes: Sequence[Episode]) -> List[List[Episode]]:
    """One Habitat worker per (scene, start height): the planar motion adapter
    can only reset to its launch height."""
    key = lambda e: (e.scene_path, round(e.start_position[1], 6))
    return [list(g) for _, g in groupby(sorted(episodes, key=lambda e: (key(e), e.uid)), key=key)]


class LockstepRunner:
    def __init__(self, config: RunnerConfig, *, habitat_python: Path, out_dir: Path, run_id: str,
                 policy_factory: Callable[[], object], sensor_factory=None, start_snapper=None, log=print):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', run_id):
            raise ValueError('run_id must be 1-64 chars of [A-Za-z0-9_.-]')
        self.config, self.habitat_python, self.run_id = config, Path(habitat_python), run_id
        self.out_dir = Path(out_dir)
        self.policy_factory, self.log = policy_factory, log
        self._sensor_factory = sensor_factory or self._habitat_sensor
        self._start_snapper = start_snapper or self._habitat_snap
        self._episode_counter = 0

    # -- sensor
    def _sensor_config(self, episode: Episode, episode_id: str) -> dict:
        cfg = json.loads(json.dumps(self.config.sensor))
        cfg.update(scene_id=episode.scene_path, episode_id=episode_id,
                   initial_position=list(episode.start_position),
                   initial_rotation_xyzw=list(episode.start_rotation_xyzw),
                   agent_geometry={k: self.config.robot[k] for k in ('geometry_id', 'radius_m', 'height_m')})
        if episode.runtime_dataset_config:
            cfg['scene_dataset_config_file'] = episode.runtime_dataset_config
        return cfg

    def _habitat_sensor(self, cfg: dict):
        from ..sensors.client import HabitatPoseSource
        os.environ['NEUSYMNAV_SIM_RUN_ID'] = self.run_id
        os.environ['NEUSYMNAV_PLANAR_HEIGHT_TOLERANCE_M'] = repr(float(self.config.planar_height_tolerance_m))
        paths = [str(REPO_SRC)] + [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p]
        os.environ['PYTHONPATH'] = os.pathsep.join(dict.fromkeys(paths))
        return HabitatPoseSource(python=self.habitat_python, worker_script=SIM_ENTRY, config=cfg, timeout_s=120.)

    def _habitat_snap(self, episodes: Sequence[Episode]) -> dict:
        request = dict(robot=self.config.robot, episodes=[
            dict(uid=e.uid, scene_path=e.scene_path, dataset_config=e.runtime_dataset_config,
                 start_position=list(e.start_position)) for e in episodes])
        with tempfile.TemporaryDirectory() as tmp:
            req, res = Path(tmp) / 'request.json', Path(tmp) / 'result.json'
            req.write_text(json.dumps(request))
            env = dict(os.environ, PYTHONPATH=str(REPO_SRC))
            proc = subprocess.run([str(self.habitat_python), str(SNAP_SCRIPT), str(req), str(res)],
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if proc.returncode != 0 or not res.exists():
                raise RuntimeError('start snapping failed: ' + proc.stderr[-2000:])
            return json.loads(res.read_text())['starts']

    def _snapped(self, episodes: Sequence[Episode]) -> Dict[str, dict]:
        """Robot-navmesh start per episode, cached in <out_dir>/start_snap.json."""
        path = self.out_dir / 'start_snap.json'
        cache = json.loads(path.read_text()) if path.exists() else {}
        missing = [e for e in episodes if e.uid not in cache]
        if missing:
            cache.update(self._start_snapper(missing))
            path.write_text(json.dumps(cache, indent=1, sort_keys=True) + '\n')
        return cache

    def _invalid_start_record(self, episode: Episode, snap: dict) -> dict:
        return dict(schema_version=1, uid=episode.uid, agent=getattr(self.policy_factory(), 'name', 'policy'),
                    run_id=self.run_id, positions=[list(episode.start_position)], called_stop=False, steps=0,
                    sim_time_s=0.0, clock_domain=None, evidence=dict(start_not_navigable=True),
                    diagnostics=dict(end_reason='start_not_navigable_for_robot', start_snap=snap, path_m=0.0))

    # -- run
    def run(self, episodes: Sequence[Episode]) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out = self.out_dir / 'trajectories.jsonl'
        done = set()
        if out.exists():   # resume: never re-run a finished episode
            done = {json.loads(line)['uid'] for line in out.read_text().splitlines() if line.strip()}
        todo = [e for e in episodes if e.uid not in done]
        self.log('episodes: %d total, %d already done, %d to run' % (len(episodes), len(done), len(todo)))
        snaps = self._snapped(todo) if todo else {}
        runnable = []
        with open(out, 'a') as stream:
            for e in todo:
                snap = snaps[e.uid]
                if not snap.get('navigable') or snap.get('shift_xz_m') is None or snap['shift_xz_m'] > MAX_START_SHIFT_M:
                    stream.write(json.dumps(self._invalid_start_record(e, snap)) + '\n')
                    self.log('%s  start not navigable for the robot body: %s' % (e.uid, snap))
                    continue
                runnable.append(replace(e, start_position=tuple(snap['snapped'])))
            stream.flush()
            for group in group_for_workers(runnable):
                sensor = None
                try:
                    for i, episode in enumerate(group):
                        self._episode_counter += 1
                        episode_id = _safe_episode_id(self._episode_counter, episode)
                        if sensor is None:
                            sensor = self._sensor_factory(self._sensor_config(episode, episode_id))
                        else:
                            sensor.reset(episode_id, position=tuple(episode.start_position),
                                         rotation_xyzw=tuple(episode.start_rotation_xyzw))
                        started = time.monotonic()
                        record = self.run_episode(sensor, episode)
                        record['diagnostics']['start_snap'] = snaps[episode.uid]
                        record['wall_time_s'] = round(time.monotonic() - started, 3)
                        stream.write(json.dumps(record) + '\n')
                        stream.flush()
                        self.log('%s  %s  stop=%s cycles=%d sim=%.1fs wall=%.1fs path=%.2fm %s' % (
                            episode.uid, episode.object_category, record['called_stop'], record['steps'],
                            record['sim_time_s'], record['wall_time_s'], record['diagnostics']['path_m'],
                            record['diagnostics']['end_reason']))
                finally:
                    if sensor is not None:
                        sensor.close()
        return out

    def run_episode(self, sensor, episode: Episode) -> dict:
        from ..mapping.occupancy import NavMapper, RobotGeometry
        from ..navigation.controller import Navigator
        from ..navigation.safety import MotionGuard
        cfg = self.config
        obs = sensor.capture_navigation()
        # canonical z of the robot base = Habitat y of the (snapped) start pose
        floor = measure_floor(obs, pose_z_m=float(episode.start_position[1]))
        floor_record = dict(floor, episode=episode.uid)
        floor_hash = hashlib.sha256(json.dumps(floor_record, sort_keys=True).encode()).hexdigest()
        robot = RobotGeometry(**cfg.robot)
        tiles = self.out_dir / 'tiles' / re.sub(r'[^A-Za-z0-9_.-]', '_', episode.uid)
        mapper = NavMapper(robot=robot, floor_z_m=floor['floor_z_m'],
                           floor_datum_source='measured-downward-depth-v1:objectnav:' + episode.uid,
                           calibration_hash=floor_hash, tile_archive_dir=tiles, **cfg.mapper)
        domain = obs.clock_domain
        navigator = Navigator(robot, clock_domain=domain, start_unknown_tolerance=cfg.start_unknown_tolerance,
                              **cfg.navigator)
        guard = MotionGuard(mapper, clock_domain=domain, command_horizon_ns=cfg.pulse_ms * 1_000_000,
                            rotation_horizon_ns=cfg.rotation_pulse_ms * 1_000_000,
                            start_unknown_tolerance=cfg.start_unknown_tolerance, escape=cfg.escape,
                            column_fallback_cells=cfg.column_fallback_cells)
        policy = self.policy_factory()
        policy.reset(episode)
        wall: Dict[str, float] = {}
        from collections import deque
        tail = deque(maxlen=60)             # last cycles: decision / guard / worker reasons (stuck diagnosis)

        def timed(stage, fn, *args, **kw):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kw)
            finally:
                wall[stage] = wall.get(stage, 0.0) + time.perf_counter() - t0

        frames = 0
        # diagnosis only (dev2-diag follow-up): sampled fresh-frame proofs of guard blocks and
        # accepted pulses that did not move the body; nothing here changes a command
        probes, still_samples, block_streak = [], [], 0
        PROBE_REASONS = {'bootstrap_blocked': False, 'escape_bootstrap_blocked': True}

        def maybe_frame(now_ns, xy, yaw):
            # Policies that look (B0) get the primary RGB-D frame between the
            # executed pulse and the next navigation capture; the frame stamp
            # is 1 ms older than that capture and the policy charges its own
            # detector latency in simulated time.
            nonlocal frames
            wants = getattr(policy, 'wants_frame', None)
            if wants is not None and wants(now_ns, xy, yaw):
                primary = timed('capture_primary', sensor.capture)
                timed('perception', policy.on_frame, primary, xy, yaw)
                frames += 1

        start_ns = obs.capture_monotonic_ns
        floor_y = episode.start_position[1]          # planar adapter keeps the launch height
        pose = sensor.robot_pose(obs)
        positions = [habitat_xyz(pose['robot_xy'], floor_y)]
        reasons: Dict[str, int] = {}
        executed = blocked = 0
        called_stop, end_reason, cycle = False, 'max_cycles', 0
        policy_record = None
        try:
            if hasattr(policy, 'begin_episode'):
                policy.begin_episode(floor_z_m=floor['floor_z_m'],
                                     episode_tag=re.sub(r'[^A-Za-z0-9_.-]', '_', episode.uid))
                maybe_frame(obs.capture_monotonic_ns, tuple(pose['robot_xy']), float(pose['yaw_rad']))
                obs = sensor.capture_navigation()
            for cycle in range(cfg.max_cycles):
                if (obs.capture_monotonic_ns - start_ns) / 1e9 >= cfg.max_sim_s:
                    end_reason = 'max_sim_time'
                    break
                nav = timed('mapper', mapper.update_for_control, obs)
                pose = sensor.robot_pose(obs)
                xy, yaw, now = tuple(pose['robot_xy']), float(pose['yaw_rad']), obs.capture_monotonic_ns
                guard.bind_nav(nav, robot_xy=xy, yaw_rad=yaw)
                action = timed('policy', policy.act, StepContext(episode, nav, obs, xy, yaw, now, cycle, navigator))
                if action.stop:
                    called_stop, end_reason = True, 'policy_stop:' + action.note
                    break
                decision = action.decision
                command = timed('guard', guard.filter, decision, obs, now)
                block_streak = block_streak + 1 if command.reason in PROBE_REASONS else 0
                if block_streak in (10, 200, 600) and len(probes) < 6:
                    try:
                        from .bootstrap_probe import probe
                        body_only = PROBE_REASONS[command.reason]
                        row = timed('probe', probe, mapper, obs, nav, xy, yaw, body_only=body_only,
                                    corridor_m=0.0 if body_only else 0.05)
                        probes.append(dict(cycle=cycle, reason=command.reason, decision=decision.reason,
                                           xy=[round(v, 3) for v in xy], yaw=round(yaw, 3), **row))
                    except Exception as exc:          # diagnosis must never break an episode
                        probes.append(dict(cycle=cycle, reason=command.reason, error=repr(exc)[:200]))
                result = timed('execute', sensor.execute, command)
                moved = isinstance(result, dict) and result.get('executed') is True and (
                    command.linear_mps or command.yaw_radps)
                executed += 1 if moved else 0
                reason = command.reason if moved or not isinstance(result, dict) else (result.get('reason') or command.reason)
                tail.append([cycle, decision.reason, command.reason,
                             result.get('reason') if isinstance(result, dict) else None, bool(moved)])
                if reason == 'expired_or_zero':
                    # The worker's generic answer to a zero command: the real reason is the
                    # guard's/controller's (as in runtime/coordinator.py). Without it the
                    # Navigator's failure watch never sees 'collision_blocked' & co. and a
                    # blocked goal is held forever.
                    reason = command.reason
                reasons[reason] = reasons.get(reason, 0) + 1
                maybe_frame(now, xy, yaw)
                obs = timed('capture_nav', sensor.capture_navigation)
                after = sensor.robot_pose(obs)
                no_progress = bool(moved) and tuple(after['robot_xy']) == xy and float(after['yaw_rad']) == yaw
                if no_progress:
                    blocked += 1          # accepted by the worker, but the body did not move
                    tail[-1].append('no_progress')
                    if len(still_samples) < 12:
                        still_samples.append(dict(
                            cycle=cycle, xy=[round(v, 3) for v in xy], yaw=round(yaw, 3),
                            decision=decision.reason, linear_mps=command.linear_mps, yaw_radps=command.yaw_radps,
                            worker={k: v for k, v in result.items() if isinstance(v, (str, int, float, bool))}))
                # The failure watch sees a body that does not move as a blocked goal too.
                navigator.observe_navigation_result(nav, xy, now, 'actuation_no_progress' if no_progress else reason,
                                                    no_progress or not moved)
                positions.append(habitat_xyz(after['robot_xy'], floor_y))
            else:
                cycle = cfg.max_cycles
            if hasattr(policy, 'end_episode'):
                policy_record = policy.end_episode()
        finally:
            mapper.close() if hasattr(mapper, 'close') else None
            if hasattr(policy, 'close'):
                policy.close()
        path = sum(math.dist(a, b) for a, b in zip(positions, positions[1:]))
        return dict(schema_version=1, uid=episode.uid, agent=getattr(policy, 'name', type(policy).__name__),
                    run_id=self.run_id, positions=positions, called_stop=called_stop, steps=cycle,
                    sim_time_s=round((obs.capture_monotonic_ns - start_ns) / 1e9, 3),
                    clock_domain=domain,
                    diagnostics=dict(end_reason=end_reason, executed_commands=executed, blocked_moves=blocked,
                                     command_reasons=dict(sorted(reasons.items())), floor=floor,
                                     path_m=round(path, 3), primary_frames=frames, reason_tail=list(tail),
                                     guard_block_probes=probes, no_progress_samples=still_samples,
                                     guard_column_fallback=guard.column_fallback_used,
                                     guard_escape_issued=guard.escape_issued,
                                     wall_s_by_stage={k: round(v, 3) for k, v in sorted(wall.items())},
                                     **({} if policy_record is None else dict(policy=policy_record))))
