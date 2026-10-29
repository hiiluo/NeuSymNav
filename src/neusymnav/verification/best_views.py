"""Bounded quality/baseline gallery, ported from NewOH3DSG best_view.py.

Quality is the source heuristic, never a probability of semantic correctness.
The durable consumer deduplicates event IDs; the gallery keeps only three rows.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from ..contracts.observations import FrameKey


@dataclass(frozen=True)
class BestView:
    object_id: str
    event_id: str
    source: FrameKey
    detection_id: str
    capture_monotonic_ns: int
    clock_domain: str
    geometry_hash: str
    object_revision: int
    camera_position_world: tuple[float, float, float]
    quality: float
    detector_score: float
    depth_quality: float
    mask_quality: float
    crop_ref: str
    mask_ref: str
    source_ref: str
    crop_bbox_xyxy: tuple[int, int, int, int]


class BestViewSelector:
    MIN_BASELINE_M = 0.3

    def __init__(self, object_id):
        self.object_id = object_id
        self._views = []

    def offer(self, sample: BestView):
        if sample.object_id != self.object_id:
            raise ValueError('best view canonical object mismatch')
        if any(v.event_id == sample.event_id for v in self._views):
            return self.snapshot()
        near = [v for v in self._views if math.dist(
            sample.camera_position_world, v.camera_position_world) < self.MIN_BASELINE_M]
        # Replacing only the nearest source view could violate the baseline to
        # another neighbor. Replace all competing views only if quality wins.
        if near and sample.quality <= max(v.quality for v in near):
            return self.snapshot()
        self._views = [v for v in self._views if v not in near] + [sample]
        self._views.sort(key=lambda v: (-v.quality, v.source.frame_index, v.detection_id))
        del self._views[3:]
        return self.snapshot()

    def snapshot(self):
        return tuple(self._views)
