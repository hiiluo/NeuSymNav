"""B3 low-confidence detection for weak goal categories (plant).

The shared detector profile drops every detection below 0.25. On DEV167 most failed plant episodes
never produced one plant detection at all (B0 instance recall for plant: 0.16), so the plant goal is
seen but never detected. For episodes whose target is listed here, the policy uses a second detector
worker with a lower confidence floor, and keeps the extra (below-profile) detections only for the
target's own labels: every other label is filtered back to the profile floor, so the rest of the
memory sees the same detections as B0. The target's confirmation threshold is lowered to the same
value; such weak candidates are expected to go through the SigLIP crop check before STOP.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Callable, Iterable

KEYS = {'targets', 'detector_confidence'}


def validate(spec: dict) -> None:
    if set(spec) != KEYS:
        raise ValueError('low_conf needs exactly %s' % sorted(KEYS))
    floor = float(spec['detector_confidence'])
    if not 0 < floor < 1:
        raise ValueError('low_conf.detector_confidence must be in (0, 1)')
    for goal, thr in spec['targets'].items():
        if not floor <= float(thr) < 1:
            raise ValueError('low_conf.targets[%r] must be in [detector_confidence, 1)' % goal)


class FilteredClient:
    """Wraps a low-floor detector client: below ``keep_floor`` only ``labels`` survive."""

    def __init__(self, client, labels: Iterable[str], keep_floor: float):
        self.client, self.labels, self.keep_floor = client, set(labels), float(keep_floor)
        self.extra = 0                                     # detections kept below the profile floor

    def infer(self, observation):
        batch = self.client.infer(observation)
        kept = []
        for d in batch.detections:
            if float(d.score) >= self.keep_floor:
                kept.append(d)
            elif d.raw_label in self.labels:
                kept.append(d)
                self.extra += 1
        if len(kept) == len(batch.detections):
            return batch
        return dataclasses.replace(batch, detections=tuple(kept))

    def close(self):
        if hasattr(self.client, 'close'):
            self.client.close()


def low_client_factory(profile: Path, confidence: float) -> Callable[[], object]:
    """Same worker and model as ``profile``, with its confidence floor replaced."""
    from ...b0.detection import recipe_from_profile
    from ....perception.detector_client import validate_recipe
    launch = recipe_from_profile(profile)
    recipe = validate_recipe(dict(launch['recipe'], confidence_threshold=float(confidence)))

    def make():
        from ....perception.detector_client import DetectorClient
        client = DetectorClient(python=launch['python'], worker_script=launch['worker_script'], recipe=recipe,
                                timeout_s=launch['timeout_s'], startup_timeout_s=launch['startup_timeout_s'])
        if recipe.get('backend') == 'openvino_gpu':
            client.start()
        return client
    return make


def profile_floor(profile: Path) -> float:
    import json
    return float(json.loads(Path(profile).read_text())['detector']['confidence_threshold'])
