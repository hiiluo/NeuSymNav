"""Detector access for B0 in the lockstep runner: the runtime YOLOE worker, with
its latency charged in simulated time.

The control loop never waits for the detector (AGENTS.md invariant). In the
lockstep runner the simulator is paused while the worker computes, so a
synchronous call would hand the robot a detector of zero latency. Instead a
frame captured at simulated time t is released to the policy only once the
simulated clock reaches t + ``latency_ms``, and only one frame is in flight at
a time: the robot keeps moving meanwhile, exactly like a 2.5 Hz detector on a
real robot. Results are a deterministic function of the frames, so runs stay
reproducible.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ...perception.detector_client import RECIPE_CONFIG_ASSETS, validate_recipe


def _pinned(entry: dict, name: str) -> Tuple[str, str]:
    # The path is returned as written, NOT resolved: a venv's bin/python is a
    # symlink to the system interpreter, and launching the resolved target
    # silently leaves the venv (its site-packages are then missing).
    path = Path(entry['path'])
    if not path.is_absolute() or not path.is_file():
        raise FileNotFoundError('%s asset missing or not absolute: %s' % (name, path))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry['sha256']:
        raise ValueError('%s checksum differs from the profile pin (%s)' % (name, path))
    return str(path), digest


def recipe_from_profile(profile: Path) -> dict:
    """Closed detector recipe + worker launch facts, as the runtime launcher builds them."""
    data = json.loads(Path(profile).read_text())
    d, worker = data['detector'], data['workers']['detector']
    recipe = {k: v for k, v in d.items() if k not in RECIPE_CONFIG_ASSETS}
    names = ['checkpoint', 'encoder', 'taxonomy']
    if d.get('backend', 'torch') == 'openvino_gpu':
        names += ['openvino_model', 'openvino_bin', 'openvino_metadata']
    for name in names:
        recipe[name + '_path'], recipe[name + '_sha256'] = _pinned(d[name], name)
    python, _ = _pinned(worker['python'], 'detector python')
    script, _ = _pinned(worker['script'], 'detector worker script')
    return dict(recipe=validate_recipe(recipe), python=python, worker_script=script,
                timeout_s=float(worker.get('timeout_s', 5.0)),
                startup_timeout_s=float(worker.get('startup_timeout_s', 60.0)))


def client_factory(profile: Path) -> Callable[[], object]:
    launch = recipe_from_profile(profile)

    def make():
        from ...perception.detector_client import DetectorClient
        client = DetectorClient(python=launch['python'], worker_script=launch['worker_script'],
                                recipe=launch['recipe'], timeout_s=launch['timeout_s'],
                                startup_timeout_s=launch['startup_timeout_s'])
        if launch['recipe'].get('backend') == 'openvino_gpu':
            try:
                client.start()
            except Exception as exc:
                tail = ' | '.join(str(d)[-400:] for d in list(client.diagnostics)[-6:])
                raise RuntimeError('%s; worker stderr: %s' % (exc, tail or '<none>')) from exc
        return client
    return make


@dataclass
class Pending:
    observation: object
    batch: object
    ready_ns: int
    wall_s: float


class LatencyGate:
    """At most one frame in flight; results released at capture + latency (simulated)."""

    def __init__(self, infer: Callable, *, latency_ms: float, clock=None):
        if not 0 <= latency_ms <= 5000:
            raise ValueError('detector latency must be in [0, 5000] ms')
        self.infer = infer
        self.latency_ns = int(round(latency_ms * 1e6))
        self._pending: Optional[Pending] = None
        self._clock = clock
        self.submitted = 0
        self.wall_s: List[float] = []

    def busy(self, now_ns: int) -> bool:
        return self._pending is not None and now_ns < self._pending.ready_ns

    def submit(self, observation) -> bool:
        if self._pending is not None:
            return False
        import time
        t0 = time.perf_counter()
        batch = self.infer(observation)
        wall = time.perf_counter() - t0
        self.wall_s.append(wall)
        self.submitted += 1
        self._pending = Pending(observation, batch, observation.capture_monotonic_ns + self.latency_ns, wall)
        return True

    def ready(self, now_ns: int) -> List[Pending]:
        if self._pending is not None and now_ns >= self._pending.ready_ns:
            done, self._pending = self._pending, None
            return [done]
        return []

    @property
    def in_flight(self) -> bool:
        return self._pending is not None
