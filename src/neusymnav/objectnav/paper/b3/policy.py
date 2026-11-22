"""B3-semsearch policy (paper mode): B0's state machine with semantic exploration and crop verification.

Differences from B0 (each one a config block; B0 behaviour when absent):
- ``semantic``: every new view is embedded by a SigLIP image encoder (worker on the iGPU); its similarity
  to "a <target>" is fused into a value map (b3/value_map.py). Frontier choice:
      cost = path cost - value_weight_m * rel(frontier) [- B1 context bonus]
  rel = (v - min) / (max - min) over the current frontiers whose value is known, 0 when the spread is
  below ``min_spread`` (no semantic signal: B0 nearest frontier).
- ``clip_verify``: before STOP on a target listed in ``targets``, the candidate's latest crop is
  classified among the target prompt (first) and its confusable prompts; STOP only when the target
  prompt scores highest. One check per candidate. A target's prompts are a list (the first one is
  the target) or {pos: [...], neg: [...]}; with ``reject_margin`` a candidate is rejected only when the
  best negative prompt beats the best positive one by at least that much (v2).
- ``low_conf`` (v2, b3/low_conf.py): for weak categories (plant) a detector worker with a lower
  confidence floor, the extra detections kept only for the target's labels, and a lower confirmation
  threshold for the target (v4: no SigLIP veto needed — on DEV167 it rejected 21/32 true plants as "a vase").
- ``endgame`` (v3): an episode must not end without a decision while the memory holds objects seen as
  the target. When frontiers are exhausted, or when the steps left are about what reaching the best
  such object needs, the policy approaches it as a fallback and stops there without the confirmation
  rule or the SigLIP veto (clip-rejected and motion-rejected objects included; each tried once).
  Ranking: highest detector score for the target (offline on B3 v1 DEV167 non-decision failures it
  picks an object within 1 m of a true goal in 14/24 episodes vs 12/24 for view count).
  v3 result: 30 triggers, 0 successes -> not used from v5.
- ``early_stop`` (v5, b3/early_stop.py): arrive one forward step early, so the last approach step does not
  carry the robot past the goal's view points.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from ...b0.memory import footprint_distance
from ..b0 import PaperB0Config, PaperB0Policy

SEMANTIC_KEYS = {'model_dir', 'device', 'prompts', 'value_weight_m', 'min_spread', 'window_cells'}
VERIFY_KEYS = {'targets', 'margin'}
VERIFY_OPTIONAL = {'reject_margin'}
ENDGAME_KEYS = {'max_steps', 'min_step', 'check_every', 'step_m', 'overhead', 'margin_steps'}


def verify_prompts(spec):
    """(prompts, number of positive prompts at the front) for one clip_verify target."""
    if isinstance(spec, dict):
        if set(spec) != {'pos', 'neg'} or not spec['pos'] or not spec['neg']:
            raise ValueError('clip_verify target needs non-empty pos and neg lists')
        return list(spec['pos']) + list(spec['neg']), len(spec['pos'])
    if len(spec) < 2:
        raise ValueError('clip_verify target needs the target prompt and at least one confusable')
    return list(spec), 1


@dataclass(frozen=True)
class PaperB3Config(PaperB0Config):
    semantic: Optional[dict] = None
    clip_verify: Optional[dict] = None
    low_conf: Optional[dict] = None
    endgame: Optional[dict] = None
    early_stop: Optional[dict] = None

    def __post_init__(self):
        super().__post_init__()
        if self.semantic is not None and set(self.semantic) != SEMANTIC_KEYS:
            raise ValueError('semantic needs exactly %s' % sorted(SEMANTIC_KEYS))
        if self.clip_verify is not None:
            keys = set(self.clip_verify)
            if not VERIFY_KEYS <= keys <= VERIFY_KEYS | VERIFY_OPTIONAL:
                raise ValueError('clip_verify needs %s (optional %s)' % (sorted(VERIFY_KEYS), sorted(VERIFY_OPTIONAL)))
            for spec in self.clip_verify['targets'].values():
                verify_prompts(spec)
        if self.early_stop is not None:
            from .early_stop import validate
            validate(self.early_stop)
        if self.endgame is not None:
            if set(self.endgame) != ENDGAME_KEYS:
                raise ValueError('endgame needs exactly %s' % sorted(ENDGAME_KEYS))
            if not 0 < int(self.endgame['min_step']) < int(self.endgame['max_steps']) or int(self.endgame['check_every']) < 1:
                raise ValueError('endgame needs 0 < min_step < max_steps and check_every >= 1')
        if self.low_conf is not None:
            from .low_conf import validate
            validate(self.low_conf)
        if (self.semantic or self.clip_verify) and not self.semantic:
            raise ValueError('clip_verify uses the semantic model: give a semantic block')
        if self.vlm_verify is not None and self.clip_verify is not None:
            raise ValueError('use either vlm_verify or clip_verify')


def crop_box(rgb: np.ndarray, bbox, mask_shape, margin: float) -> np.ndarray:
    h, w = rgb.shape[:2]
    sy, sx = h / mask_shape[0], w / mask_shape[1]
    x0, y0, x1, y1 = bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy
    bw, bh = x1 - x0, y1 - y0
    r0, r1 = int(max(0, y0 - margin * bh)), int(min(h, y1 + margin * bh))
    c0, c1 = int(max(0, x0 - margin * bw)), int(min(w, x1 + margin * bw))
    return np.ascontiguousarray(rgb[r0:r1, c0:c1, :3])


class PaperB3Policy(PaperB0Policy):
    def __init__(self, config: PaperB3Config, *, clip=None, low_detector_factory=None, keep_floor=0.25, **kw):
        super().__init__(config, **kw)
        self.clip = clip
        self._base_rule = self.rule
        self.low_detector_factory, self.keep_floor = low_detector_factory, float(keep_floor)
        self._base_client, self._low = None, None
        if self.clip is None and config.semantic is not None:
            from .clip_client import ClipClient
            self.clip = ClipClient(config.semantic['model_dir'], device=config.semantic['device'])

    def reset(self, episode) -> None:
        if self._base_client is not None:              # the previous episode used the low-floor worker
            self._client, self._base_client = self._base_client, None
        low = self.cfg.low_conf
        self.rule = self._base_rule
        if low is not None and episode.object_category in low['targets']:
            import copy
            self.rule = copy.deepcopy(self._base_rule)
            self.rule['categories'][episode.object_category]['threshold'] = float(low['targets'][episode.object_category])
        super().reset(episode)
        self._low_extra0 = None
        if low is not None and self.target in low['targets']:
            if self._low is None:
                from .low_conf import FilteredClient
                if self.low_detector_factory is None:
                    raise ValueError('low_conf needs a low_detector_factory')
                self._low = FilteredClient(self.low_detector_factory(), self.categories.labels[self.target],
                                           self.keep_floor)
            self._base_client, self._client = self._client, self._low
            self._low_extra0 = self._low.extra
        self.vmap = None
        self.sem = dict(views=0, embed_s=0.0, choices=0, changed=0, flat=0, flat_unknown=0)
        self.clip_events = []
        self._sem_view = None
        self._endgame, self._eg_tried, self.endgame_events = None, set(), []   # _endgame: cid
        self.early_events = []

    def close(self) -> None:
        if self._base_client is not None:
            self._client, self._base_client = self._base_client, None
        super().close()
        if self._low is not None:
            self._low.close()
            self._low = None
        if self.clip is not None:
            self.clip.close()

    # ---------------------------------------------------------------- perception
    def _perceive(self, obs) -> None:
        super()._perceive(obs)
        sem = self.cfg.semantic
        if sem is None or self._last_view == self._sem_view:
            return
        self._sem_view = self._last_view
        if self.vmap is None:
            from .value_map import ValueMap
            self.vmap = ValueMap(self._hfov(obs))
        t0 = time.perf_counter()
        feat = self.clip.embed([np.asarray(obs.observation.rgb)])
        self._last_feat = feat                           # kept for subclasses that reuse the embedding
        score = float(self.clip.scores(feat, [sem['prompts'][self.target]])[0, 0])
        self.sem['embed_s'] += time.perf_counter() - t0
        self.sem['views'] += 1
        self.vmap.update(self.nav.map, self.nav.robot_xy, self.nav.yaw, score)

    @staticmethod
    def _hfov(obs) -> float:
        K = np.asarray(obs.observation.K, float)
        w = np.asarray(obs.observation.rgb).shape[1]
        return float(np.degrees(2 * np.arctan(w / (2 * K[0, 0]))))

    # ---------------------------------------------------------------- exploration
    def _choose_frontier(self, frontiers):
        sem = self.cfg.semantic
        if sem is None or self.vmap is None:
            return super()._choose_frontier(frontiers)
        score, costs = self._frontier_scores(frontiers)
        pick, nearest = int(np.argmin(score)), int(np.argmin(costs))
        self.sem['choices'] += 1
        self.sem['changed'] += int(pick != nearest)
        return frontiers[pick]

    def _frontier_scores(self, frontiers):
        """(score, path cost) per frontier; the lowest score is chosen (subclasses may add terms)."""
        sem = self.cfg.semantic
        m = self.nav.map
        costs = np.array([self.nav.path_length_m(f.cell) for f in frontiers])
        vals = [self.vmap.at(m, f.cell, int(sem['window_cells'])) for f in frontiers]
        known = [v for v in vals if v is not None]
        rel = np.zeros(len(frontiers))
        if len(known) >= 2 and max(known) - min(known) >= float(sem['min_spread']):
            lo, hi = min(known), max(known)
            rel = np.array([0.0 if v is None else (v - lo) / (hi - lo) for v in vals])
        else:
            self.sem['flat'] += 1
            self.sem['flat_unknown'] += int(len(known) < 2)       # v2 diagnostic: no value vs no spread
        score = costs - float(sem['value_weight_m']) * rel
        if self.ctx is not None:
            score = score - np.array([self.ctx.bonus(f.xy, m.level.z_m) for f in frontiers])
        return score, costs

    # ---------------------------------------------------------------- endgame
    def _reach_m(self, cand) -> float:
        from ...b0.approach import approach_goals
        aim = self.cfg.stop_distance_m - self.cfg.aim_margin_m
        cells, _c, _t = approach_goals(self._grid(), self.nav.trav, cand.points[:, :2], cand.centroid_xy, aim_m=aim)
        goal = self.nav.field.nearest_reachable(cells) if cells else None
        return float('inf') if goal is None else self.nav.path_metres(goal)

    def _eg_pool(self):
        pool = [c for c in self.memory.candidates.values() if c.views.get(self.target) and c.cid not in self._eg_tried]
        return sorted(pool, key=lambda c: -c.best_score(self.target))

    def _start_endgame(self, cand, why: str, reach_m: float) -> None:
        self._eg_tried.add(cand.cid)
        self.endgame_events.append(dict(step=self.step, why=why, cid=cand.cid, was_rejected=cand.rejected,
                                        best=round(cand.best_score(self.target), 3), reach_m=round(reach_m, 2)))
        cand.rejected = None
        self._endgame, self._target_cid, self._fallback = cand.cid, cand.cid, True
        self._frontier = None
        self._to('APPROACH', 'endgame_' + why)

    def _exhausted_hook(self) -> bool:
        if self.cfg.endgame is None:
            return False
        for cand in self._eg_pool():
            reach = self._reach_m(cand)
            if math.isfinite(reach):
                self._start_endgame(cand, 'exhausted', reach)
                return True
            self._eg_tried.add(cand.cid)
        return False

    def _act_explore(self):
        eg = self.cfg.endgame
        if (eg is not None and self.step >= int(eg['min_step']) and self.step % int(eg['check_every']) == 0
                and not self.memory.confirmed_for(self.target)):
            left = int(eg['max_steps']) - self.step
            for cand in self._eg_pool():
                reach = self._reach_m(cand)
                if not math.isfinite(reach):
                    continue                              # unreachable now: maybe later, keep it untried
                need = math.ceil(reach / float(eg['step_m']) * float(eg['overhead'])) + int(eg['margin_steps'])
                if need >= left:
                    self._start_endgame(cand, 'budget', reach)
                    return None
                break                                     # the best reachable one still has time: explore on
        return super()._act_explore()

    # ---------------------------------------------------------------- verification
    def _wants_crop(self, goal: str) -> bool:
        cv = self.cfg.clip_verify
        return (cv is not None and goal in cv['targets']) or super()._wants_crop(goal)

    def _make_crop(self, rgb, bbox, mask_shape):
        cv = self.cfg.clip_verify
        if cv is not None:
            return crop_box(rgb, bbox, mask_shape, float(cv['margin']))
        return super()._make_crop(rgb, bbox, mask_shape)

    def _stop_veto(self, cand) -> Optional[str]:
        if self._endgame is not None and cand.cid == self._endgame:
            return None                                   # endgame: stopping here beats ending undecided
        cv = self.cfg.clip_verify
        if cv is None or self.target not in cv['targets']:
            return super()._stop_veto(cand)
        for e in self.clip_events:
            if e['cid'] == cand.cid:
                return None if e['accepted'] else 'clip_rejected'
        crop = self._best_crop(cand)
        if crop is None or min(crop[2].shape[:2]) < 8:
            self.clip_events.append(dict(step=self.step, cid=cand.cid, top=None, accepted=True))
            return None
        prompts, n_pos = verify_prompts(cv['targets'][self.target])
        s = self.clip.scores(self.clip.embed([crop[2]]), prompts)[0]
        gap = float(np.max(s[n_pos:]) - np.max(s[:n_pos]))       # > 0: a confusable prompt wins
        ok = gap <= 0 or gap < float(cv.get('reject_margin', 0.0))
        self.clip_events.append(dict(step=self.step, cid=cand.cid, frame=crop[0], top=prompts[int(np.argmax(s))],
                                     scores=[round(float(v), 4) for v in s], gap=round(gap, 4), accepted=ok))
        return None if ok else 'clip_rejected'

    # ---------------------------------------------------------------- early stop
    def _act_approach(self):
        action = super()._act_approach()
        es = self.cfg.early_stop
        if es is None or action != 'move_forward' or self.state != 'APPROACH':
            return action
        cand = self._target()
        if cand is None:
            return action
        from . import early_stop
        if early_stop.arrives_next_step(cand.points[:, :2], self.nav.robot_xy, self.nav.yaw, float(es['step_m']),
                                        self.cfg.stop_distance_m, footprint_distance):
            self.early_events.append(dict(step=self.step, cid=cand.cid, distance_m=round(
                footprint_distance(cand.points[:, :2], self.nav.robot_xy), 3)))
            self._to('FACE', early_stop.NOTE)
            return None
        return action

    def _stop_limit_m(self) -> float:
        limit = super()._stop_limit_m()
        if self.cfg.early_stop is not None and any(e['note'] == 'arrived_early' for e in self.events[-2:]):
            limit = max(limit, self.cfg.stop_distance_m + float(self.cfg.early_stop['step_m']))
        return limit

    # ---------------------------------------------------------------- record
    def end_episode(self) -> dict:
        rec = super().end_episode()
        if self.cfg.semantic is not None:
            rec['semantic'] = dict(self.sem, embed_s=round(self.sem['embed_s'], 2),
                                   value_updates=0 if self.vmap is None else self.vmap.updates)
        if self.cfg.clip_verify is not None:
            rec['clip_verify'] = self.clip_events
        if self.cfg.endgame is not None:
            rec['endgame'] = self.endgame_events
        if self.cfg.early_stop is not None:
            rec['early_stop'] = self.early_events
        if self._low_extra0 is not None:
            rec['low_conf'] = dict(extra_detections=self._low.extra - self._low_extra0,
                                   threshold=self.rule['categories'][self.target]['threshold'])
        return rec


def make_policy_factory(config_path, *, evidence_dir=None, clip_factory=None, config_cls=None, policy_cls=None,
                        name='paper_b3'):
    """Factory of B3 policies (a subclass may pass its own config and policy classes)."""
    config_cls, policy_cls = config_cls or PaperB3Config, policy_cls or PaperB3Policy
    cfg = config_cls.load(config_path)
    from ...b0.detection import client_factory
    from ...detector_eval.categories import GoalCategories
    categories = GoalCategories.load(cfg.resolve('mapping'))
    profile = cfg.resolve('detector_profile')
    make_client = client_factory(profile)
    make_low, floor = None, 0.25
    if cfg.low_conf is not None:
        from .low_conf import low_client_factory, profile_floor
        make_low, floor = low_client_factory(profile, cfg.low_conf['detector_confidence']), profile_floor(profile)

    def factory():
        policy = policy_cls(cfg, categories=categories, detector_factory=make_client, evidence_dir=evidence_dir,
                               clip=None if clip_factory is None else clip_factory(),
                               low_detector_factory=make_low, keep_floor=floor)
        policy.name = name
        return policy
    return factory
