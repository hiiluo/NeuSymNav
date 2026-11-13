"""B0: the non-privileged ObjectNav baseline (no 3DSG, no tour, no room labels).

    SPIN      one in-place turn at the start (detector + map bootstrap)
    EXPLORE   frontier exploration with the project Navigator
    APPROACH  a candidate confirmed by ``b0-detection-v1``: plan on the robot's
              observed map to a cell within ``stop_distance_m`` of the
              object's observed points
    FACE      turn toward the object
    VERIFY    hold until one detection captured after arrival is released,
              then STOP if the candidate is still confirmed (else reject it)

Inputs are the episode's object CATEGORY, the robot's RGB-D frames and
simulator pose (AGENTS.md: runtime uses RGB-D + simulator pose). The detector
latency is charged in simulated time (``detection.LatencyGate``).
"""
from __future__ import annotations

import gzip
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ...contracts import NavigationDecision
from ..runner import PolicyAction
from .approach import approach_goals, facing_rate, wrap
from .memory import CandidateMemory, footprint_distance

REPO = Path(__file__).resolve().parents[4]


def exhausted_reason(reason: str) -> bool:
    """Navigator reasons meaning "no frontier left to go to" (frontiers.py / _policy_core.py)."""
    return reason == 'no_frontiers' or reason.startswith(('no_frontier', 'no_reachable_frontier'))


@dataclass(frozen=True)
class B0Config:
    name: str
    detection_rule: str
    mapping: str
    detector_profile: str
    detector_latency_ms: float = 400.0
    frame_moved_m: float = 0.30
    frame_rotated_deg: float = 20.0
    frame_max_interval_s: float = 3.0
    stop_distance_m: float = 0.4
    far_stop_distance_m: float = 0.9
    aim_margin_m: float = 0.10
    face_tolerance_deg: float = 10.0
    initial_spin: bool = True
    spin_max_cycles: int = 40
    approach_timeout_s: float = 60.0
    approach_no_path_cycles: int = 30
    verify_max_cycles: int = 20
    fallback_best_unconfirmed: bool = True
    exhausted_cycles: int = 30
    stuck_stop_s: float = 60.0
    escape_after_s: float = 0.0           # 0 disables the ESCAPE state (b0-policy-v1)
    escape_max_cycles: int = 60
    escape_max_per_episode: int = 10
    # b0-policy-v3 (dev2-diag follow-up); the v1/v2 defaults keep the old behaviour
    escape_exit_on_start_traversable: bool = False   # clearance escape ends once the planner can start here
    escape_nudge: bool = False                        # 2nd escape at one spot: short steps instead of a turn
    approach_reached_far_cycles: int = 0              # reject a candidate after N 'goal_reached' beyond the stop distance
    approach_timer_survives_escape: bool = False      # an escape does not restart the approach timeout
    max_sim_s: float = 500.0
    description: str = ''

    @classmethod
    def load(cls, path: Path) -> 'B0Config':
        data = json.loads(Path(path).read_text())
        if data.pop('schema_version', None) != 1:
            raise ValueError('B0 config needs schema_version 1')
        return cls(**data)

    def __post_init__(self):
        if not 0.2 <= self.stop_distance_m <= 1.0 or not 0 <= self.aim_margin_m < self.stop_distance_m:
            raise ValueError('stop distance must be in [0.2, 1.0] m and aim margin below it')
        if not self.stop_distance_m <= self.far_stop_distance_m <= 1.2:
            raise ValueError('far stop distance must be in [stop distance, 1.2] m')
        if not 0 < self.max_sim_s <= 1800 or self.detector_latency_ms < 0:
            raise ValueError('invalid B0 time budget or detector latency')

    def resolve(self, name: str) -> Path:
        p = Path(getattr(self, name))
        return p if p.is_absolute() else REPO / p


class B0Policy:
    name = 'b0'

    def __init__(self, config: B0Config, *, categories, detector_factory: Callable[[], object],
                 robot_height_m: float, evidence_dir: Optional[Path] = None, projector=None,
                 robot_radius_m: float = 0.2, robot_margin_m: float = 0.05):
        self.cfg = config
        self.categories = categories
        self.rule = json.loads(config.resolve('detection_rule').read_text())
        if self.rule.get('schema_version') != 1:
            raise ValueError('detection rule needs schema_version 1')
        self.detector_factory = detector_factory
        self.robot_height_m = float(robot_height_m)
        self.robot_radius_m, self.robot_margin_m = float(robot_radius_m), float(robot_margin_m)
        self.evidence_dir = Path(evidence_dir) if evidence_dir else None
        if projector is None:
            from ...perception.projector import Projector
            projector = Projector()
        self.projector = projector
        self.episode = None

    # ------------------------------------------------------------ episode lifecycle
    def reset(self, episode) -> None:
        if episode.object_category not in self.rule['categories']:
            raise ValueError('no confirmation rule for category %r' % episode.object_category)
        self.episode, self.target = episode, episode.object_category
        self.state, self.state_cycles, self.state_since_ns = 'SPIN' if self.cfg.initial_spin else 'EXPLORE', 0, None
        self.memory = None
        self.gate = None
        self._client = None
        self._last_frame = None             # (ns, xy, yaw) of the last submitted frame
        self._spin_turned, self._spin_prev_yaw = 0.0, None
        self._exhausted = 0
        self._target_cid, self._no_path, self._fallback = None, 0, False
        self._verify_after_ns = None
        self.frames = []                    # evidence rows (goal-category detections only)
        self.events = []
        self.state_cycle_counts = {}
        self.stop_record = None
        self._still_since = None           # (ns, xy, yaw) when the pose last changed
        self._escape = None                # dict while in ESCAPE
        self.escapes = []
        self._approach_since_ns = None     # approach timeout clock (v3: kept across escapes)
        self._reached_far = 0

    def begin_episode(self, *, floor_z_m: float, episode_tag: str) -> None:
        from .detection import LatencyGate
        self.memory = CandidateMemory(self.categories, self.rule['categories'], floor_z_m=floor_z_m,
                                      robot_height_m=self.robot_height_m)
        self._client = self.detector_factory()
        self.gate = LatencyGate(self._client.infer, latency_ms=self.cfg.detector_latency_ms)
        self.episode_tag = episode_tag

    def close(self) -> None:
        if self._client is not None and hasattr(self._client, 'close'):
            self._client.close()
        self._client = None

    # ------------------------------------------------------------ frames
    def wants_frame(self, now_ns: int, robot_xy, yaw_rad: float) -> bool:
        if self.gate is None or self.gate.in_flight:
            return False
        if self._last_frame is None or self.state in ('SPIN', 'APPROACH', 'FACE', 'VERIFY'):
            return True
        ns, xy, yaw = self._last_frame
        return (math.dist(xy, robot_xy) >= self.cfg.frame_moved_m
                or abs(wrap(yaw_rad - yaw)) >= math.radians(self.cfg.frame_rotated_deg)
                or (now_ns - ns) / 1e9 >= self.cfg.frame_max_interval_s)

    def on_frame(self, observation, robot_xy, yaw_rad) -> None:
        if self.gate.submit(observation):
            self._last_frame = (observation.capture_monotonic_ns, tuple(robot_xy), float(yaw_rad))

    def _ingest(self, now_ns: int) -> None:
        from ..detector_eval.masks import bbox_xyxy, rle_encode
        for item in self.gate.ready(now_ns):
            obs, batch = item.observation, item.batch
            projected = {o.detection_id: o for o in self.projector.project(obs, batch)}
            rows = []
            for det in batch.detections:
                goal = self.categories.goal_category(det.raw_label)
                if goal is None:
                    continue
                o = projected.get(det.detection_id)
                cid = self.memory.add(obs.key.frame_index, det.raw_label, float(det.score),
                                      o.points_world) if o is not None else None
                rows.append(dict(label=det.raw_label, goal=goal, score=round(float(det.score), 4),
                                 bbox=bbox_xyxy(det.mask), rle=rle_encode(det.mask), cid=cid,
                                 points=0 if o is None else int(len(o.points_world))))
            self.frames.append(dict(frame_index=obs.key.frame_index, capture_ns=obs.capture_monotonic_ns,
                                    released_ns=now_ns, wall_s=round(item.wall_s, 4),
                                    T_world_camera=np.asarray(obs.T_world_camera).round(6).tolist(),
                                    K=np.asarray(obs.K).round(4).tolist(), detections=rows,
                                    depth_small_cm=None if getattr(obs, 'depth_m', None) is None else
                                    np.round(np.nan_to_num(np.asarray(obs.depth_m, dtype=np.float64)
                                                           [10::20, 10::20]) * 100).astype(int).tolist(),
                                    cap_reached=bool(batch.cap_reached)))
            if self.state == 'VERIFY' and self._verify_after_ns is not None and obs.capture_monotonic_ns >= self._verify_after_ns:
                self._verify_after_ns = None          # the arrival view is in

    # ------------------------------------------------------------ control
    def _to(self, state: str, ctx, note: str = '') -> None:
        self.events.append(dict(cycle=ctx.cycle, sim_s=round(ctx.now_ns / 1e9, 3), state=state, note=note,
                                target=self._target_cid))
        self.state, self.state_cycles, self.state_since_ns = state, 0, ctx.now_ns
        if state == 'APPROACH' and not (self.cfg.approach_timer_survives_escape
                                        and note.startswith('escape_done') and self._approach_since_ns is not None):
            self._approach_since_ns, self._reached_far = ctx.now_ns, 0
        if state in ('EXPLORE', 'APPROACH'):
            ctx.navigator.release_goal()

    def _target(self):
        return None if self._target_cid is None else self.memory.candidates.get(self._target_cid)

    def _reject(self, ctx, reason: str) -> None:
        cand = self._target()
        if cand is not None:
            cand.rejected = reason
        self._target_cid, self._fallback = None, False
        self._to('EXPLORE', ctx, 'reject:' + reason)

    def _pick(self, ctx) -> bool:
        pool = self.memory.confirmed_for(self.target)
        if not pool:
            return False
        cand = min(pool, key=lambda c: math.dist(c.centroid_xy, ctx.robot_xy))
        self._target_cid, self._no_path, self._fallback = cand.cid, 0, False
        self._to('APPROACH', ctx, 'confirmed')
        return True

    def _rotate(self, ctx, rate: float, reason: str) -> PolicyAction:
        return PolicyAction(False, NavigationDecision(None, (), 0.0, float(rate), ctx.nav.revision, reason))

    def _hold(self, ctx, reason: str) -> PolicyAction:
        return PolicyAction(False, NavigationDecision(None, (), 0.0, 0.0, ctx.nav.revision, reason))

    def act(self, ctx) -> PolicyAction:
        self._ingest(ctx.now_ns)
        if self.state_since_ns is None:
            self.state_since_ns = ctx.now_ns
        self.state_cycles += 1
        self.state_cycle_counts[self.state] = self.state_cycle_counts.get(self.state, 0) + 1
        pose = (tuple(round(v, 4) for v in ctx.robot_xy), round(ctx.yaw_rad, 4))
        if self._still_since is None or self._still_since[1] != pose:
            self._still_since = (ctx.now_ns, pose)
        elif (self.state not in ('VERIFY',) and self.cfg.stuck_stop_s
              and (ctx.now_ns - self._still_since[0]) / 1e9 >= self.cfg.stuck_stop_s):
            return self._stop(ctx, 'stuck')
        elif (self.cfg.escape_after_s and self.state in ('SPIN', 'EXPLORE', 'APPROACH')
              and len(self.escapes) < self.cfg.escape_max_per_episode
              and (ctx.now_ns - self._still_since[0]) / 1e9 >= self.cfg.escape_after_s):
            self._enter_escape(ctx)
        handler = getattr(self, '_act_' + self.state.lower())
        return handler(ctx)

    # ------------------------------------------------------------ escape (approved 12/11/2026)
    def _needed_clearance(self, nav) -> float:
        # the planner's inflated footprint (radius + margin + 0.75 cell pad) plus one cell
        return self.robot_radius_m + self.robot_margin_m + 1.75 * float(nav.resolution_m)

    def _start_traversable(self, ctx):
        """The planner can start from the robot's cell (v3), or None if not asked / not available."""
        probe = getattr(ctx.navigator, 'start_traversable', None)
        if not self.cfg.escape_exit_on_start_traversable or probe is None:
            return None
        try:
            return bool(probe(ctx.nav, ctx.robot_xy))
        except Exception:                       # a diagnosis helper must never break an episode
            return None

    def _enter_escape(self, ctx) -> None:
        from ...navigation.safety import free_distance
        c0 = free_distance(ctx.nav, ctx.robot_xy, self.robot_height_m)
        start_ok = self._start_traversable(ctx)
        blocked = (not start_ok) if start_ok is not None else c0 < self._needed_clearance(ctx.nav)
        kind = 'clearance' if blocked else 'turn'
        if kind == 'turn' and self.cfg.escape_nudge and any(
                e['kind'] == 'turn' and math.dist(e['xy'], ctx.robot_xy) <= 0.15 for e in self.escapes):
            # A turn here already did not help: the planner is fine, the guard's fresh-frame
            # proof is not. Short escape steps (<= 5 cm each, guard-checked) change the view.
            kind = 'nudge'
        self._escape = dict(resume=self.state, kind=kind, start_yaw=ctx.yaw_rad, turned=0.0,
                            prev_yaw=ctx.yaw_rad, cycles=0, start_clearance=round(c0, 3),
                            start_xy=tuple(ctx.robot_xy))
        self.escapes.append(dict(cycle=ctx.cycle, sim_s=round(ctx.now_ns / 1e9, 3), kind=kind, from_state=self.state,
                                 clearance_m=round(c0, 3), xy=[round(v, 3) for v in ctx.robot_xy]))
        self._to('ESCAPE', ctx, 'escape:' + kind)
        self._still_since = (ctx.now_ns, self._still_since[1])        # the escape gets its own time

    def _leave_escape(self, ctx, note: str) -> PolicyAction:
        resume = self._escape['resume'] if self._escape else 'EXPLORE'
        self.escapes[-1].update(result=note, cycles=self._escape['cycles'] if self._escape else 0)
        self._escape = None
        resume = 'EXPLORE' if resume == 'SPIN' else resume
        self._to(resume, ctx, 'escape_done:' + note)
        return getattr(self, '_act_' + resume.lower())(ctx)

    def _act_escape(self, ctx) -> PolicyAction:
        from ...navigation.safety import free_distance
        e = self._escape
        e['cycles'] += 1
        e['turned'] += abs(wrap(ctx.yaw_rad - e['prev_yaw']))
        e['prev_yaw'] = ctx.yaw_rad
        h, need = self.robot_height_m, self._needed_clearance(ctx.nav)
        c0 = free_distance(ctx.nav, ctx.robot_xy, h)
        if e['kind'] == 'clearance':
            start_ok = self._start_traversable(ctx)
            if (start_ok if start_ok is not None else c0 >= need):
                return self._leave_escape(ctx, 'clear')
        if e['kind'] == 'turn' and e['turned'] >= math.radians(80):
            return self._leave_escape(ctx, 'turned')
        if e['kind'] == 'nudge' and math.dist(e['start_xy'], ctx.robot_xy) >= 0.10:
            return self._leave_escape(ctx, 'nudged')
        if e['cycles'] > self.cfg.escape_max_cycles:
            return self._leave_escape(ctx, 'gave_up')
        if e['kind'] == 'turn':
            return self._rotate(ctx, math.radians(29.5), 'escape_rotate')
        best = None
        for k in range(16):
            t = 2 * math.pi * k / 16
            end = (ctx.robot_xy[0] + 0.05 * math.cos(t), ctx.robot_xy[1] + 0.05 * math.sin(t))
            d = free_distance(ctx.nav, end, h)
            if d > c0 + 0.005 and d >= self.robot_radius_m + 0.03 and (best is None or d > best[0]):
                best = (d, t, end)
        if best is None and e['kind'] == 'nudge':
            return self._leave_escape(ctx, 'no_away_direction')
        if best is None:                                            # nothing better known: look around
            return self._rotate(ctx, math.radians(29.5), 'escape_rotate')
        _, t, end = best
        err = wrap(t - ctx.yaw_rad)
        if abs(err) > math.radians(10):
            return self._rotate(ctx, max(-math.radians(29.5), min(math.radians(29.5), err / 0.5)), 'escape_rotate')
        far = (ctx.robot_xy[0] + 0.15 * math.cos(t), ctx.robot_xy[1] + 0.15 * math.sin(t))
        return PolicyAction(False, NavigationDecision(None, (tuple(ctx.robot_xy), far), 0.1, 0.0, ctx.nav.revision,
                                                      'escape_step'))

    def _act_spin(self, ctx) -> PolicyAction:
        if self._spin_prev_yaw is not None:
            self._spin_turned += abs(wrap(ctx.yaw_rad - self._spin_prev_yaw))
        self._spin_prev_yaw = ctx.yaw_rad
        if self._spin_turned >= 2 * math.pi - math.radians(10) or self.state_cycles > self.cfg.spin_max_cycles:
            self._to('EXPLORE', ctx, 'spin_done' if self._spin_turned >= 6 else 'spin_cycles')
            return self._act_explore(ctx)
        return self._rotate(ctx, math.radians(29.5), 'b0_spin')

    def _act_explore(self, ctx) -> PolicyAction:
        if self._pick(ctx):
            return self._act_approach(ctx)
        decision = ctx.navigator.step(ctx.nav, ctx.robot_xy, ctx.yaw_rad, ctx.now_ns)
        self._exhausted = self._exhausted + 1 if exhausted_reason(decision.reason) else 0
        if self._exhausted >= self.cfg.exhausted_cycles:
            if self.cfg.fallback_best_unconfirmed:
                cand = self.memory.best_unconfirmed(self.target)
                if cand is not None:
                    self._target_cid, self._no_path, self._exhausted, self._fallback = cand.cid, 0, 0, True
                    self._to('APPROACH', ctx, 'fallback_best_unconfirmed')
                    return self._act_approach(ctx)
            return self._stop(ctx, 'frontiers_exhausted')
        return PolicyAction(False, decision)

    def _act_approach(self, ctx) -> PolicyAction:
        cand = self._target()
        if cand is None or cand.rejected:
            self._target_cid = None
            self._to('EXPLORE', ctx, 'target_gone')
            return self._act_explore(ctx)
        if not self._fallback and not self.memory.confirmed(cand, self.target):
            self._target_cid = None
            self._to('EXPLORE', ctx, 'unconfirmed')
            return self._act_explore(ctx)
        points = cand.points[:, :2]
        if footprint_distance(points, ctx.robot_xy) <= self.cfg.stop_distance_m:
            self._to('FACE', ctx, 'arrived')
            return self._act_face(ctx)
        since = self._approach_since_ns if self._approach_since_ns is not None else self.state_since_ns
        if (ctx.now_ns - since) / 1e9 > self.cfg.approach_timeout_s:
            self._reject(ctx, 'approach_timeout')
            return self._act_explore(ctx)
        aim = self.cfg.stop_distance_m - self.cfg.aim_margin_m
        decision = ctx.navigator.step_toward(
            ctx.nav, ctx.robot_xy, ctx.yaw_rad, ctx.now_ns,
            lambda grid, trav: approach_goals(grid, trav, points, cand.centroid_xy, aim_m=aim),
            'b0-cand-%d' % cand.cid)
        # No traversable cell within the near ring is known yet ('closer' goals): once the robot
        # stands on the closest reachable cell and is within the far distance, that is the stop.
        info = getattr(ctx.navigator, 'last_approach', None) or {}
        dist = footprint_distance(points, ctx.robot_xy)
        if (info.get('tag') == 'closer' and info.get('goal_xy') is not None and dist <= self.cfg.far_stop_distance_m
                and math.dist(info['goal_xy'], ctx.robot_xy) <= 0.1):
            self._to('FACE', ctx, 'arrived_far')
            return self._act_face(ctx)
        # v3: the follower says the chosen goal cell is reached, but the robot is not within a
        # stop distance (a 'closer'/'toward' goal at the robot's own cell): holding there only
        # waits for the timeout, so give the candidate up now.
        self._reached_far = self._reached_far + 1 if decision.reason == 'goal_reached' else 0
        if self.cfg.approach_reached_far_cycles and self._reached_far >= self.cfg.approach_reached_far_cycles:
            self._reject(ctx, 'approach_goal_reached_far')
            return self._act_explore(ctx)
        self._no_path = self._no_path + 1 if decision.reason in ('approach_no_path', 'approach_no_goal_cells') else 0
        if self._no_path >= self.cfg.approach_no_path_cycles:
            self._reject(ctx, 'approach_no_path')
            return self._act_explore(ctx)
        return PolicyAction(False, decision)

    def _act_face(self, ctx) -> PolicyAction:
        cand = self._target()
        if cand is None:
            self._to('EXPLORE', ctx, 'target_gone')
            return self._act_explore(ctx)
        rate, _err = facing_rate(ctx.robot_xy, ctx.yaw_rad, cand.centroid_xy,
                                 tol=math.radians(self.cfg.face_tolerance_deg))
        if rate == 0.0 or self.state_cycles > 15:
            self._verify_after_ns = ctx.now_ns
            self._to('VERIFY', ctx, 'faced' if rate == 0.0 else 'face_cycles')
            return self._hold(ctx, 'b0_verify')
        return self._rotate(ctx, rate, 'b0_face')

    def _act_verify(self, ctx) -> PolicyAction:
        cand = self._target()
        if cand is None:
            self._to('EXPLORE', ctx, 'target_gone')
            return self._act_explore(ctx)
        if self._verify_after_ns is not None and self.state_cycles <= self.cfg.verify_max_cycles:
            return self._hold(ctx, 'b0_verify_wait')
        fallback = self._fallback
        if not fallback and not self.memory.confirmed(cand, self.target):
            self._reject(ctx, 'verify_failed')
            return self._act_explore(ctx)
        limit = self.cfg.far_stop_distance_m if self.events[-2:] and any(
            e['note'] == 'arrived_far' for e in self.events[-2:]) else self.cfg.stop_distance_m
        if footprint_distance(cand.points[:, :2], ctx.robot_xy) > limit + 0.05:
            self._to('APPROACH', ctx, 'object_grew_away')          # near views moved the observed surface
            return self._act_approach(ctx)
        return self._stop(ctx, 'confirmed_target' if not fallback else 'fallback_target')

    def _dump_map(self, ctx, note: str) -> None:
        """Stuck diagnosis: the navigation map around the robot (robot's own map only)."""
        nav = getattr(ctx, 'nav', None)
        if self.evidence_dir is None or nav is None or not hasattr(nav, 'states'):
            return
        res = float(nav.resolution_m)
        ox, oy = nav.origin_xy
        c = int((ctx.robot_xy[0] - ox) / res)
        r = int((ctx.robot_xy[1] - oy) / res)
        k = int(round(3.0 / res))
        r0, r1 = max(0, r - k), min(nav.states.shape[0], r + k + 1)
        c0, c1 = max(0, c - k), min(nav.states.shape[1], c + k + 1)
        arrays = dict(states=np.asarray(nav.states)[r0:r1, c0:c1])
        for name in ('clearance', 'floor_support'):
            if hasattr(nav, name):
                arrays[name] = np.asarray(getattr(nav, name))[r0:r1, c0:c1]
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.evidence_dir / (self.episode_tag + '.%s.npz' % note), **arrays,
                            origin_xy=np.array([ox + c0 * res, oy + r0 * res]), resolution_m=res,
                            robot_xy=np.asarray(ctx.robot_xy, float), yaw_rad=float(ctx.yaw_rad))

    def _stop(self, ctx, note: str) -> PolicyAction:
        if note == 'stuck':
            try:
                self._dump_map(ctx, note)
            except Exception:                       # diagnosis must never break an episode
                pass
        cand = self._target()
        self.stop_record = dict(note=note, cycle=ctx.cycle, sim_s=round(ctx.now_ns / 1e9, 3), cid=self._target_cid,
                                robot_xy=[round(v, 3) for v in ctx.robot_xy],
                                distance_to_object_m=None if cand is None else round(
                                    footprint_distance(cand.points[:, :2], ctx.robot_xy), 3))
        self._to('STOPPED', ctx, note)
        return PolicyAction(True, note=note)

    # ------------------------------------------------------------ records
    def end_episode(self) -> dict:
        evidence_file = None
        if self.evidence_dir is not None and self.frames is not None:
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence_file = self.evidence_dir / (self.episode_tag + '.jsonl.gz')
            with gzip.open(evidence_file, 'wt') as stream:
                for row in self.frames:
                    stream.write(json.dumps(row) + '\n')
        walls = self.gate.wall_s if self.gate is not None else []
        return dict(config=self.cfg.name, target=self.target, final_state=self.state, stop=self.stop_record,
                    escapes=self.escapes,
                    events=self.events, state_cycles=self.state_cycle_counts,
                    detections=dict(frames=len(self.frames), wall_s_mean=round(float(np.mean(walls)), 4) if walls else None,
                                    wall_s_max=round(float(np.max(walls)), 4) if walls else None),
                    candidates=self.memory.summary(self.target) if self.memory is not None else [],
                    evidence_file=None if evidence_file is None else str(evidence_file))
