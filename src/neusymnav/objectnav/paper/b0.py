"""B0 and B1-revisit in paper-protocol mode (discrete actions, simulator-owned collisions).

Same decisions as the lockstep B0 (objectnav/b0/policy.py) on the same detector, candidate memory,
confirmation rule and approach goals; what changes is the protocol (docs/objectnav/paper-protocol-plan.md):

* one discrete action per step (``PaperNav``: obstacle map from the forward camera, frontiers, A*);
* the detector runs synchronously on every frame whose view changed (D3: no simulated latency);
* timeouts are counted in steps, not simulated seconds;
* no ESCAPE state and no guard: the simulator refuses a blocked move, the map marks it, the
  planner goes around; a goal the robot cannot make progress toward is given up.

States: SPIN (12 x 30 deg) -> EXPLORE (nearest frontier) -> APPROACH (confirmed candidate) ->
FACE -> VERIFY (the latest frame, taken after arriving and facing, must still confirm) -> STOP.
Inputs: object CATEGORY, RGB-D frames and simulator pose only.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Optional

import numpy as np

from ..b0.approach import approach_goals
from ..b0.memory import CandidateMemory, footprint_distance
from .nav import NavConfig, PaperNav

REPO = Path(__file__).resolve().parents[4]
MOTION_REASONS = ('approach_no_path', 'approach_timeout', 'approach_goal_reached_far', 'approach_stuck')


@dataclass(frozen=True)
class PaperB0Config:
    name: str
    detection_rule: str
    mapping: str
    detector_profile: str
    stop_distance_m: float = 0.4
    far_stop_distance_m: float = 0.9
    aim_margin_m: float = 0.1
    spin_turns: int = 12
    approach_max_steps: int = 100
    approach_no_path_steps: int = 10
    approach_reached_far_steps: int = 3
    face_max_steps: int = 6
    memory_height_m: float = 1.5            # candidate points kept up to this + 0.5 m (lockstep B0 value)
    fallback_best_unconfirmed: bool = True
    nav: dict = field(default_factory=dict)
    revisit: Optional[dict] = None          # B1-revisit: cooldown_steps, min_moved_m, max_revisits, opportunistic_arrival
    description: str = ''
    plant_taxonomy: str | None = None
    reachable_approach: bool = False

    @classmethod
    def load(cls, path) -> 'PaperB0Config':
        data = json.loads(Path(path).read_text())
        if data.pop('schema_version', None) != 1:
            raise ValueError('paper B0 config needs schema_version 1')
        return cls(**data)

    def __post_init__(self):
        if type(self.reachable_approach) is not bool:
            raise ValueError('reachable_approach must be boolean')
        if self.plant_taxonomy is not None and (not isinstance(self.plant_taxonomy, str) or not self.plant_taxonomy):
            raise ValueError('plant_taxonomy requires a path')
        if not 0.2 <= self.stop_distance_m <= 1.0 or not 0 <= self.aim_margin_m < self.stop_distance_m:
            raise ValueError('stop distance must be in [0.2, 1.0] m and aim margin below it')
        if not self.stop_distance_m <= self.far_stop_distance_m <= 1.2:
            raise ValueError('far stop distance must be in [stop distance, 1.2] m')
        for name in ('spin_turns', 'approach_max_steps', 'approach_no_path_steps', 'approach_reached_far_steps',
                     'face_max_steps'):
            if type(getattr(self, name)) is not int or getattr(self, name) < 0:
                raise ValueError(name + ' must be a non-negative integer')
        NavConfig(**self.nav)                 # unknown keys fail here
        if self.revisit is not None and set(self.revisit) - {'cooldown_steps', 'min_moved_m', 'max_revisits',
                                                              'opportunistic_arrival'}:
            raise ValueError('unknown revisit keys')

    def resolve(self, name: str) -> Path:
        p = Path(getattr(self, name))
        return p if p.is_absolute() else REPO / p


class PaperB0Policy:
    name = 'paper_b0'

    def __init__(self, config: PaperB0Config, *, categories, detector_factory: Callable[[], object],
                 evidence_dir: Optional[Path] = None, projector=None, plant_detector_factory=None,
                 shadow_root: Optional[Path] = None):
        self.cfg = config
        self.categories = categories
        self.rule = json.loads(config.resolve('detection_rule').read_text())
        if self.rule.get('schema_version') != 1:
            raise ValueError('detection rule needs schema_version 1')
        self.detector_factory = detector_factory
        self.plant_detector_factory = plant_detector_factory
        self._client_factory = None
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        self.shadow_root = Path(shadow_root).absolute() if shadow_root is not None else None
        self._shadow_capture = None
        if projector is None:
            from ...perception.projector import Projector
            projector = Projector()
        self.projector = projector
        self._client = None

    # ------------------------------------------------------------ lifecycle
    def reset(self, episode) -> None:
        if episode.object_category not in self.rule['categories']:
            raise ValueError('no confirmation rule for category %r' % episode.object_category)
        self.episode, self.target = episode, episode.object_category
        self.episode_tag = ''.join(ch if ch.isalnum() or ch in '_.-' else '_' for ch in episode.uid)
        if self.shadow_root is not None:
            from uuid import uuid4
            from ...reasoninggraph.paper_shadow import PaperShadowCapture

            # The current Hydra replay profile emits a full update at one-second intervals.
            self._shadow_capture = PaperShadowCapture(self.shadow_root / uuid4().hex,
                                                     min_interval_ns=1_000_000_000)
        self.state, self.state_steps, self.step = 'SPIN', 0, 0
        self.nav, self.memory = None, None
        self._frontier, self._target_cid, self._fallback = None, None, False
        self._frontier_blocks, self._goal_xy = 0, None
        self._no_path = self._reached_far = 0
        self._last_view = None
        self.frames, self.events, self.state_step_counts = [], [], {}
        self.detector_wall_s = []
        self.stop_record = None
        self._gave_up, self.revisit_events = {}, []
        make = self.plant_detector_factory if self.target == 'plant' and self.plant_detector_factory else self.detector_factory
        if self._client is not None and make is not self._client_factory:
            if hasattr(self._client, 'close'):
                self._client.close()
            self._client = None
        if self._client is None:
            self._client = make()
        self._client_factory = make

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, 'close'):
            self._client.close()
        self._client = None
        self._shadow_capture = None

    # ------------------------------------------------------------ perception (synchronous)
    def _perceive(self, obs) -> None:
        view = (tuple(round(v, 3) for v in obs.robot_xy), round(obs.yaw_rad, 3), round(obs.tilt_rad, 3))
        if view == self._last_view:
            return                                  # blocked move / STOP: same image, same detections
        self._last_view = view
        observation = obs.observation
        t0 = time.perf_counter()
        batch = self._client.infer(observation)
        self.detector_wall_s.append(time.perf_counter() - t0)
        projected = {o.detection_id: o for o in self.projector.project(observation, batch)}
        if self._shadow_capture is not None:
            self._shadow_capture.offer(observation, batch, robot_xyz=(*obs.robot_xy, obs.z_m),
                                       yaw_rad=obs.yaw_rad, tilt_rad=obs.tilt_rad)
        rows = self._detection_rows(obs, batch, projected)
        depth = np.asarray(observation.depth_m, np.float64)
        depth = np.where(np.asarray(observation.valid_depth, bool), depth, 0.0)    # clipped max range: no pose check
        self.frames.append(dict(frame_index=observation.key.frame_index, capture_ns=observation.capture_monotonic_ns,
                                released_ns=observation.capture_monotonic_ns, step=obs.step,
                                wall_s=round(self.detector_wall_s[-1], 4),
                                T_world_camera=np.asarray(observation.T_world_camera).round(6).tolist(),
                                K=np.asarray(observation.K).round(4).tolist(), detections=rows,
                                depth_small_cm=np.round(depth[10::20, 10::20] * 100).astype(int).tolist(),
                                cap_reached=bool(batch.cap_reached)))

    def _detection_rows(self, obs, batch, projected):
        from ..detector_eval.masks import bbox_xyxy, rle_encode
        rows = []
        for det in batch.detections:
            goal = self.categories.goal_category(det.raw_label)
            if goal is None:
                continue
            o = projected.get(det.detection_id)
            cid = self.memory.add(obs.observation.key.frame_index, det.raw_label, float(det.score),
                                  o.points_world) if o is not None else None
            rows.append(dict(label=det.raw_label, goal=goal, score=round(float(det.score), 4),
                             bbox=bbox_xyxy(det.mask), rle=rle_encode(det.mask), cid=cid,
                             points=0 if o is None else int(len(o.points_world))))
        return rows

    def _new_memory(self, obs):
        return CandidateMemory(self.categories, self.rule['categories'], floor_z_m=obs.z_m,
                               robot_height_m=self.cfg.memory_height_m)

    # ------------------------------------------------------------ helpers
    def _to(self, state: str, note: str = '') -> None:
        self.events.append(dict(step=self.step, state=state, note=note, target=self._target_cid))
        self.state, self.state_steps = state, 0
        if state == 'APPROACH':
            self._no_path = self._reached_far = 0
            if self.nav is not None:
                self.nav.reset_progress()
        if state == 'EXPLORE':
            self._frontier, self._frontier_blocks, self._goal_xy = None, 0, None

    def _target(self):
        return None if self._target_cid is None else self.memory.candidates.get(self._target_cid)

    def _reject(self, reason: str) -> None:
        cand = self._target()
        if cand is not None:
            cand.rejected = reason
            if self.cfg.revisit is not None and reason in MOTION_REASONS:
                g = self._gave_up.setdefault(cand.cid, dict(n=0))
                g.update(n=g['n'] + 1, step=self.step, xy=tuple(self.nav.robot_xy), reason=reason)
        self._target_cid, self._fallback = None, False
        self._to('EXPLORE', 'reject:' + reason)

    def _stop(self, note: str):
        cand = self._target()
        self.stop_record = dict(note=note, step=self.step, cid=self._target_cid,
                                robot_xy=[round(v, 3) for v in self.nav.robot_xy],
                                distance_to_object_m=None if cand is None else round(
                                    footprint_distance(cand.points[:, :2], self.nav.robot_xy), 3))
        self._to('STOPPED', note)
        return ('stop', note)

    def _grid(self):
        m = self.nav.map
        return SimpleNamespace(resolution_m=m.res, origin_x_m=m.origin[0], origin_y_m=m.origin[1])

    # ------------------------------------------------------------ control
    def act(self, ctx):
        obs = ctx.obs
        self.step = obs.step
        if self.nav is None:
            self.nav = PaperNav(ctx.protocol, NavConfig(**self.cfg.nav))
            self.memory = self._new_memory(obs)
        self.nav.decision_audit = getattr(ctx, 'navigation_audit', None)
        self.nav.observe(obs, ctx.last_action)
        self._perceive(obs)
        self.state_steps += 1
        self.state_step_counts[self.state] = self.state_step_counts.get(self.state, 0) + 1
        for _ in range(6):                  # state changes within one step; one action out
            action = getattr(self, '_act_' + self.state.lower())()
            if action is not None:
                return action
        return 'turn_left'

    def _act_spin(self):
        if self.state_steps <= self.cfg.spin_turns:
            return 'turn_left'
        self._to('EXPLORE', 'spin_done')
        return None

    # B1-revisit hooks (no-ops for B0)
    def _revive(self) -> None:
        rv = self.cfg.revisit
        if rv is None:
            return
        for cid, g in self._gave_up.items():
            cand = self.memory.candidates.get(cid)
            if cand is None or cand.rejected not in MOTION_REASONS or g['n'] > int(rv.get('max_revisits', 3)):
                continue
            if (self.step - g['step'] >= int(rv.get('cooldown_steps', 30))
                    and math.dist(g['xy'], self.nav.robot_xy) >= float(rv.get('min_moved_m', 1.0))):
                cand.rejected = None
                self.revisit_events.append(dict(step=self.step, kind='revive', cid=cid, after=g['reason'], n=g['n']))

    def _near_confirmed(self):
        best = None
        for cand in self.memory.candidates.values():
            if cand.rejected is not None and cand.rejected not in MOTION_REASONS:
                continue
            if not self.memory.confirmed(cand, self.target):
                continue
            d = footprint_distance(cand.points[:, :2], self.nav.robot_xy)
            if d <= self.cfg.stop_distance_m and (best is None or d < best[0]):
                best = (d, cand)
        return best

    def _act_explore(self):
        if self.cfg.revisit is not None:
            self._revive()
            if self.cfg.revisit.get('opportunistic_arrival', True):
                near = self._near_confirmed()
                if near is not None:
                    d, cand = near
                    self.revisit_events.append(dict(step=self.step, kind='arrive_nearby', cid=cand.cid,
                                                    distance_m=round(d, 3), was_rejected=cand.rejected))
                    cand.rejected = None
                    self._target_cid, self._fallback = cand.cid, False
                    self._to('FACE', 'arrived_nearby')
                    return None
        pool = self.memory.confirmed_for(self.target)
        if pool:
            cand = min(pool, key=lambda c: math.dist(c.centroid_xy, self.nav.robot_xy))
            self._target_cid, self._fallback = cand.cid, False
            self._to('APPROACH', 'confirmed')
            return None
        return self._explore_frontiers()

    def _choose_frontier(self, frontiers):
        return min(frontiers, key=lambda frontier: self.nav.path_length_m(frontier.cell))

    def _frontier_reached(self):
        return None

    def _explore_frontiers(self):
        for _ in range(4):
            if self._frontier is None:
                frontiers = self.nav.frontiers()
                if not frontiers:
                    return self._frontiers_exhausted()
                self._frontier = self._choose_frontier(frontiers)
                if self._goal_xy is None or math.dist(self._goal_xy, self._frontier.xy) > self.nav.cfg.frontier_blacklist_m:
                    self.nav.reset_progress()          # same goal re-chosen: keep counting toward 'stuck'
                    self._goal_xy = self._frontier.xy
            result = self.nav.go_to_cells([self._frontier.cell])
            if result.action is not None:
                return result.action
            if result.status == 'blocked':                 # the map now marks the bump: turn away, replan
                self._frontier_blocks += 1
                if self._frontier_blocks < self.nav.cfg.blocked_give_up:
                    return self.nav.escape_turn()
            if result.status in ('stuck', 'blocked'):      # unreachable = map changed: just re-choose
                self.nav.blacklist.append(self._frontier.xy)
            self._frontier = None
            self._frontier_blocks = 0
            if result.status == 'reached':
                action = self._frontier_reached()
                if action is not None:
                    return action
        return 'turn_left'

    def _frontiers_exhausted(self):
        if self.cfg.fallback_best_unconfirmed:
            cand = self.memory.best_unconfirmed(self.target)
            if cand is not None:
                self._target_cid, self._fallback = cand.cid, True
                self._to('APPROACH', 'fallback_best_unconfirmed')
                return None
        return self._stop('frontiers_exhausted')

    def _act_approach(self):
        cand = self._target()
        if cand is None or cand.rejected:
            self._target_cid = None
            self._to('EXPLORE', 'target_gone')
            return None
        if not self._fallback and not self.memory.confirmed(cand, self.target):
            self._target_cid = None
            self._to('EXPLORE', 'unconfirmed')
            return None
        points = cand.points[:, :2]
        dist = footprint_distance(points, self.nav.robot_xy)
        if dist <= self.cfg.stop_distance_m:
            self._to('FACE', 'arrived')
            return None
        if self.state_steps > self.cfg.approach_max_steps:
            self._reject('approach_timeout')
            return None
        aim = self.cfg.stop_distance_m - self.cfg.aim_margin_m
        traversable = self.nav.reachable() if self.cfg.reachable_approach else self.nav.trav
        cells, _cost, tag = approach_goals(self._grid(), traversable, points, cand.centroid_xy, aim_m=aim)
        result = self.nav.go_to_cells(cells, reach_m=0.0)
        if result.status == 'reached':
            if tag == 'closer' and dist <= self.cfg.far_stop_distance_m:
                self._to('FACE', 'arrived_far')
                return None
            self._reached_far += 1
            if self._reached_far >= self.cfg.approach_reached_far_steps:
                self._reject('approach_goal_reached_far')
                return None
            return self._face_or_probe(cand.centroid_xy)    # look / nudge from here
        self._reached_far = 0
        if result.status in ('stuck', 'blocked'):
            if dist <= self.cfg.far_stop_distance_m:          # cannot get closer: the closest reachable spot
                self._to('FACE', 'arrived_far')
                return None
            self._reject('approach_stuck')
            return None
        if result.status == 'unreachable':
            self._no_path += 1
            if self._no_path >= self.cfg.approach_no_path_steps:
                self._reject('approach_no_path')
                return None
            return self._face_or_probe(cand.centroid_xy)
        self._no_path = 0
        return result.action

    def _face_or_probe(self, xy):
        turn = self.nav.face(xy)
        if turn is not None:
            return turn
        if self.cfg.reachable_approach and self.nav._forward_ok(self.nav.yaw) is None:
            return self.nav.escape_turn()
        return 'move_forward'

    def _act_face(self):
        cand = self._target()
        if cand is None:
            self._to('EXPLORE', 'target_gone')
            return None
        turn = self.nav.face(cand.centroid_xy)
        if turn is None or self.state_steps > self.cfg.face_max_steps:
            self._to('VERIFY', 'faced' if turn is None else 'face_steps')
            return None
        return turn

    def _act_verify(self):
        # The current frame was taken after arriving and facing (perception ran before this call).
        cand = self._target()
        if cand is None:
            self._to('EXPLORE', 'target_gone')
            return None
        if not self._fallback and not self.memory.confirmed(cand, self.target):
            self._reject('verify_failed')
            return None
        limit = (self.cfg.far_stop_distance_m if any(e['note'] == 'arrived_far' for e in self.events[-2:])
                 else self.cfg.stop_distance_m)
        if footprint_distance(cand.points[:, :2], self.nav.robot_xy) > limit + 0.05:
            self._to('APPROACH', 'object_grew_away')
            return None
        return self._stop('confirmed_target' if not self._fallback else 'fallback_target')

    def _act_stopped(self):
        return ('stop', 'after_stop')

    # ------------------------------------------------------------ records
    def end_episode(self) -> dict:
        evidence_file = None
        if self.evidence_dir is not None:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence_file = self.evidence_dir / (self.episode_tag + '.jsonl.gz')
            with gzip.open(evidence_file, 'wt') as stream:
                for row in self.frames:
                    stream.write(json.dumps(row) + '\n')
        walls = self.detector_wall_s
        m = self.nav.map if self.nav is not None else None
        rec = dict(config=self.cfg.name, target=self.target, final_state=self.state, stop=self.stop_record,
                   events=self.events, state_steps=self.state_step_counts,
                   detections=dict(frames=len(self.frames), wall_s_mean=round(float(np.mean(walls)), 4) if walls else None,
                                   wall_s_max=round(float(np.max(walls)), 4) if walls else None),
                   candidates=self.memory.summary(self.target) if self.memory is not None else [],
                   map=None if m is None else dict(explored_m2=round(m.explored_area_m2(), 2),
                                                   collision_marks=m.collision_marks, levels=len(m.levels),
                                                   relaxed_plan_steps=self.nav.relaxed_steps),
                   evidence_file=None if evidence_file is None else str(evidence_file))
        if self.cfg.revisit is not None:
            rec['revisit'] = dict(events=self.revisit_events,
                                  gave_up={str(k): dict(n=v['n'], reason=v['reason']) for k, v in self._gave_up.items()})
        if self._shadow_capture is not None:
            rec['reasoninggraph_shadow'] = self._shadow_capture.close()
        return rec


def make_policy_factory(cfg: PaperB0Config, *, evidence_dir=None,
                        base_launch=None, plant_launch=None, shadow_root=None):
    """Build the paper baseline with a detector confirmed by the local profile."""
    from ..b0.detection import client_from_launch, recipe_from_profile, with_taxonomy
    from ..detector_eval.categories import GoalCategories
    if cfg.revisit is not None:
        raise ValueError('the B0-paper baseline requires a config without a revisit block')
    categories = GoalCategories.load(cfg.resolve('mapping'))
    base_launch = base_launch or recipe_from_profile(cfg.resolve('detector_profile'))
    if plant_launch is None and cfg.plant_taxonomy:
        plant_launch = with_taxonomy(base_launch, cfg.resolve('plant_taxonomy'))
    make_client = client_from_launch(base_launch)
    make_plant = client_from_launch(plant_launch) if plant_launch else None

    def factory():
        args = dict(categories=categories, detector_factory=make_client, evidence_dir=evidence_dir)
        if make_plant is not None:
            args['plant_detector_factory'] = make_plant
        if shadow_root is not None:
            args['shadow_root'] = shadow_root
        return PaperB0Policy(cfg, **args)
    return factory
