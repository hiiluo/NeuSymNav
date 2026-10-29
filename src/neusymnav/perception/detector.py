"""Explicit deterministic CPU detector for fixtures; never a native fallback."""
from ..contracts.observations import Detector, require_rgbd, validate_detection_batch


class FixtureDetector:
    def __init__(self, batches):
        self._batches = dict(batches)

    def infer(self, observation):
        require_rgbd(observation)
        batch = self._batches[observation.key]
        validate_detection_batch(observation, batch)
        return batch


__all__ = ['Detector', 'FixtureDetector']
