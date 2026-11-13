"""Per-episode memory of goal-object candidates for the B0 ObjectNav agent.

Built only from the robot's own RGB-D detections (projected with the runtime
``Projector``) and its simulator pose; no semantic ground truth. Every
detection whose label maps to an ObjectNav goal category (frozen mapping
``goal-categories-v1``) and whose score reaches the lowest rule threshold is
attached to a 3-D candidate object:

* association: the new detection's 5 cm voxels, dilated by 10 cm, touch at
  least ``ASSOC_MIN_SHARE`` of the smaller voxel set of an existing candidate,
  or (same goal category only) its floor-plan box overlaps the candidate's box
  grown by 10 cm, so the far side of an object joins its near side while two
  neighbouring objects of different categories stay apart;
* after an update, a candidate that overlaps another one the same way is
  merged into it (an object first seen from two sides);
* each candidate keeps, per goal category, the best score per distinct frame.

Confirmation follows ``b0-detection-v1`` exactly as phase 2 measured it: target
category C is confirmed on a candidate when >= ``min_views`` distinct frames
predict C on it at score >= C's threshold; with ``vote`` C must also be at
least as frequent as every other goal category counted at the same threshold.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import numpy as np

VOXEL_M = 0.05
ASSOC_DILATE_CELLS = 2                 # 10 cm
ASSOC_MIN_SHARE = 0.2
BOX_GROW_M = 0.10
MAX_VOXELS = 60_000
_BIAS = 1 << 20
_OFFSETS = np.array([(i, j, k) for i in range(-ASSOC_DILATE_CELLS, ASSOC_DILATE_CELLS + 1)
                     for j in range(-ASSOC_DILATE_CELLS, ASSOC_DILATE_CELLS + 1)
                     for k in range(-ASSOC_DILATE_CELLS, ASSOC_DILATE_CELLS + 1)], dtype=np.int64)


def _codes(cells: np.ndarray) -> np.ndarray:
    c = cells.astype(np.int64) + _BIAS
    return np.unique((c[:, 0] << 42) | (c[:, 1] << 21) | c[:, 2])


def _decode(codes: np.ndarray) -> np.ndarray:
    mask = (1 << 21) - 1
    return np.stack(((codes >> 42) & mask, (codes >> 21) & mask, codes & mask), axis=1) - _BIAS


def _dilated(codes: np.ndarray) -> np.ndarray:
    cells = _decode(codes)
    return _codes((cells[:, None, :] + _OFFSETS[None, :, :]).reshape(-1, 3))


@dataclass
class Candidate:
    cid: int
    voxels: np.ndarray                                   # sorted int64 codes
    views: Dict[str, Dict[int, float]] = field(default_factory=dict)   # category -> frame -> best score
    first_frame: int = 0
    last_frame: int = 0
    rejected: Optional[str] = None
    merged_from: List[int] = field(default_factory=list)

    @property
    def points(self) -> np.ndarray:
        return (_decode(self.voxels).astype(np.float64) + 0.5) * VOXEL_M

    @property
    def box_xy(self):
        p = self.points
        return p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()

    @property
    def centroid_xy(self):
        p = self.points
        return float(p[:, 0].mean()), float(p[:, 1].mean())

    def count(self, category: str, threshold: float) -> int:
        return sum(1 for s in self.views.get(category, {}).values() if s >= threshold)

    def best_score(self, category: str) -> float:
        return max(self.views.get(category, {}).values(), default=0.0)


def _box_overlap(a, b, grow):
    return not (a[2] + grow < b[0] or b[2] + grow < a[0] or a[3] + grow < b[1] or b[3] + grow < a[1])


class CandidateMemory:
    def __init__(self, categories, rule: dict, *, floor_z_m: float, robot_height_m: float):
        self.categories = categories
        self.rule = {c: dict(threshold=float(r['threshold']), min_views=int(r['min_views']), vote=bool(r['vote']))
                     for c, r in rule.items()}
        missing = set(categories.categories) - set(self.rule)
        if missing:
            raise ValueError('detection rule lacks categories %s' % sorted(missing))
        self.min_threshold = min(r['threshold'] for r in self.rule.values())
        self.floor_z_m, self.robot_height_m = float(floor_z_m), float(robot_height_m)
        self.candidates: Dict[int, Candidate] = {}
        self._next = 1

    @classmethod
    def from_files(cls, categories, rule_path: Path, **kw) -> 'CandidateMemory':
        data = json.loads(Path(rule_path).read_text())
        if data.get('schema_version') != 1:
            raise ValueError('detection rule needs schema_version 1')
        return cls(categories, data['categories'], **kw)

    # ------------------------------------------------------------ updates
    def add(self, frame_index: int, label: str, score: float, points_world: np.ndarray) -> Optional[int]:
        """Attach one projected detection; returns the candidate id (None if ignored)."""
        category = self.categories.goal_category(label)
        if category is None or score < self.min_threshold:
            return None
        pts = np.asarray(points_world, dtype=np.float64).reshape(-1, 3)
        z = pts[:, 2] - self.floor_z_m
        pts = pts[(z > 0.03) & (z < self.robot_height_m + 0.5)]
        if len(pts) < 10:
            return None
        codes = _codes(np.floor(pts / VOXEL_M))
        cand = self._associate(codes, category)
        if cand is None:
            cand = Candidate(self._next, codes, first_frame=frame_index)
            self.candidates[cand.cid] = cand
            self._next += 1
        elif len(cand.voxels) < MAX_VOXELS:
            cand.voxels = np.union1d(cand.voxels, codes)
        per = cand.views.setdefault(category, {})
        per[frame_index] = max(per.get(frame_index, 0.0), float(score))
        cand.last_frame = max(cand.last_frame, frame_index)
        return self._merge_into(cand).cid

    def _overlaps(self, codes: np.ndarray, box, categories, other: Candidate,
                  dilated: Optional[np.ndarray] = None) -> float:
        dilated = _dilated(codes) if dilated is None else dilated
        touched = np.isin(other.voxels, dilated, assume_unique=True).sum()
        share = touched / max(1, min(len(codes), len(other.voxels)))
        if share >= ASSOC_MIN_SHARE:
            return float(share)
        same = bool(set(categories) & set(other.views))
        return ASSOC_MIN_SHARE if same and _box_overlap(box, other.box_xy, BOX_GROW_M) else 0.0

    @staticmethod
    def _box(codes):
        p = (_decode(codes).astype(np.float64) + 0.5) * VOXEL_M
        return p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()

    def _associate(self, codes: np.ndarray, category: str) -> Optional[Candidate]:
        if not self.candidates:
            return None
        dilated, box = _dilated(codes), self._box(codes)
        best, best_share = None, 0.0
        for cand in self.candidates.values():
            share = self._overlaps(codes, box, (category,), cand, dilated)
            if share > best_share:
                best, best_share = cand, share
        return best

    def _merge_into(self, cand: Candidate) -> Candidate:
        while True:
            box, dilated = cand.box_xy, _dilated(cand.voxels)
            other = next((o for o in self.candidates.values()
                          if o.cid != cand.cid and self._overlaps(cand.voxels, box, tuple(cand.views), o, dilated) > 0),
                         None)
            if other is None:
                return cand
            keep, drop = (cand, other) if cand.cid < other.cid else (other, cand)
            keep.voxels = np.union1d(keep.voxels, drop.voxels)[:MAX_VOXELS]
            for cat, frames in drop.views.items():
                per = keep.views.setdefault(cat, {})
                for f, s in frames.items():
                    per[f] = max(per.get(f, 0.0), s)
            keep.first_frame = min(keep.first_frame, drop.first_frame)
            keep.last_frame = max(keep.last_frame, drop.last_frame)
            keep.merged_from += [drop.cid] + drop.merged_from
            if keep.rejected is None and drop.rejected is not None:
                keep.rejected = None          # new evidence: the merged object is judged again
            del self.candidates[drop.cid]
            cand = keep

    # ------------------------------------------------------------ queries
    def confirmed(self, cand: Candidate, target: str) -> bool:
        r = self.rule[target]
        n = cand.count(target, r['threshold'])
        if n < r['min_views']:
            return False
        if r['vote']:
            return n >= max(cand.count(c, r['threshold']) for c in cand.views)
        return True

    def confirmed_for(self, target: str) -> List[Candidate]:
        return [c for c in self.candidates.values() if c.rejected is None and self.confirmed(c, target)]

    def best_unconfirmed(self, target: str) -> Optional[Candidate]:
        pool = [c for c in self.candidates.values() if c.rejected is None and c.views.get(target)]
        return max(pool, key=lambda c: (c.count(target, self.rule[target]['threshold']), c.best_score(target)),
                   default=None)

    def summary(self, target: Optional[str] = None) -> List[dict]:
        out = []
        for c in sorted(self.candidates.values(), key=lambda c: c.cid):
            cx, cy = c.centroid_xy
            row = dict(cid=c.cid, centroid_xy=[round(cx, 3), round(cy, 3)], voxels=int(len(c.voxels)),
                       views={k: len(v) for k, v in sorted(c.views.items())},
                       best={k: round(max(v.values()), 3) for k, v in sorted(c.views.items())},
                       first_frame=c.first_frame, last_frame=c.last_frame, rejected=c.rejected,
                       merged_from=sorted(c.merged_from))
            if target is not None:
                row['confirmed'] = self.confirmed(c, target)
            out.append(row)
        return out


def footprint_distance(points_xy: np.ndarray, query_xy: Sequence[float]) -> float:
    p = np.asarray(points_xy, dtype=np.float64).reshape(-1, 2)
    return float(np.min(np.hypot(p[:, 0] - query_xy[0], p[:, 1] - query_xy[1]))) if len(p) else float('inf')
