#!/usr/bin/env python3
"""Evaluation-only Habitat sensor worker with a simulated lockstep clock.

Runs the UNCHANGED ``neusymnav.sensors.habitat_worker`` (locked in
baseline-3dsg-v11) but replaces its time source at runtime:

* time only moves when the simulator does: each capture advances the clock by
  ``CAPTURE_TICK_NS`` (keeps capture stamps strictly increasing), each executed
  motion pulse by exactly its duration, and every other ``execute`` (stop, zero
  or rejected command) by ``IDLE_TICK_NS``;
* the clock domain is ``sim_lockstep:<run id>``, never ``host_monotonic:`` or
  ``replay:``, so simulated stamps cannot be mistaken for host or recorded time;
* the clock starts at 1 s, far below the host monotonic clock, so the
  "capture in the future" guards in the mapper and detector stay valid.

Motion per command then depends only on the command, not on how busy the host
is, which makes episodes reproducible. Launch it through
``HabitatPoseSource(worker_script=<this file>)`` with ``PYTHONPATH`` containing
``src`` and ``NEUSYMNAV_SIM_RUN_ID`` naming the run.
"""
from __future__ import annotations

import os
import time as _host_time

SIM_DOMAIN_PREFIX = 'sim_lockstep:'
START_NS = 1_000_000_000
CAPTURE_TICK_NS = 1_000_000          # 1 ms per capture
IDLE_TICK_NS = 100_000_000           # 100 ms per non-moving control cycle
WORKER_HEIGHT_TOLERANCE_M = 0.05     # habitat_worker's planar adapter (unchanged)


def height_tolerant_filter(step_filter, tolerance_m: float):
    """Wrap the simulator's step filter for the planar adapter (approved 12/11/2026).

    HM3D navmesh heights vary by a few cm across one floor; the unchanged
    worker rejects any step whose filtered endpoint is more than 5 cm off the
    launch height, so the body stops dead on such patches. Within
    ``tolerance_m`` the endpoint height is replaced by the start height (the
    planar body stays at its launch height); horizontal motion, wall contact
    and sliding are exactly what the simulator returned, so every other check
    of the worker still applies. Beyond ``tolerance_m`` the endpoint is
    returned unchanged and the worker rejects it as before.
    """
    def wrapped(start, end):
        candidate = step_filter(start, end)
        try:
            cy, sy = float(candidate[1]), float(start[1])
        except (TypeError, IndexError, ValueError):
            return candidate
        dy = abs(cy - sy)
        if WORKER_HEIGHT_TOLERANCE_M < dy <= tolerance_m:
            return type(candidate)(float(candidate[0]), sy, float(candidate[2]))
        return candidate
    wrapped.neusymnav_height_tolerance_m = tolerance_m
    return wrapped


class SimTime:
    """Drop-in for the ``time`` module inside habitat_worker: only the
    monotonic clock is simulated; everything else is the host's."""

    def __init__(self, start_ns: int = START_NS):
        self.now_ns = int(start_ns)

    def monotonic_ns(self) -> int:
        return self.now_ns

    def monotonic(self) -> float:
        return self.now_ns / 1e9

    def advance(self, ns: int) -> None:
        if type(ns) is not int or ns < 0:
            raise ValueError('simulated time only moves forward')
        self.now_ns += ns

    def __getattr__(self, name):
        return getattr(_host_time, name)


def executed_pulse_ns(hw, command: dict, now_ns: int) -> int:
    """Duration the worker grants a command issued at ``now_ns`` (mirrors its budget rule)."""
    cap = hw.MAX_ROTATION_PULSE_NS if command['linear_mps'] == 0 else hw.MAX_TRANSLATION_PULSE_NS
    return max(0, min(int(command['deadline_monotonic_ns']) - now_ns, cap))


def install(hw, run_id: str, height_tolerance_m: float = WORKER_HEIGHT_TOLERANCE_M) -> SimTime:
    """Patch an imported habitat_worker module in place; returns the clock."""
    if not WORKER_HEIGHT_TOLERANCE_M <= height_tolerance_m <= 0.15:
        raise ValueError('planar height tolerance must be in [0.05, 0.15] m')
    if not run_id or any(c in run_id for c in ' \n:'):
        raise ValueError('run id must be a nonempty token without spaces or colons')
    if getattr(hw, '_neusymnav_sim_clock', None) is not None:
        raise RuntimeError('simulated clock already installed')
    clock = SimTime()
    domain = SIM_DOMAIN_PREFIX + run_id
    hw.time = clock
    hw.host_clock_domain = lambda: domain
    capture_original = hw.HabitatCapture.capture
    execute_original = hw.HabitatCapture.execute

    def capture(self, lane):
        try:
            return capture_original(self, lane)
        finally:
            clock.advance(CAPTURE_TICK_NS)

    def execute(self, command, pose_version):
        sim = getattr(self, 'sim', None)
        if (height_tolerance_m > WORKER_HEIGHT_TOLERANCE_M and sim is not None
                and getattr(getattr(sim, 'step_filter', None), 'neusymnav_height_tolerance_m', None) is None):
            try:
                sim.step_filter = height_tolerant_filter(sim.step_filter, height_tolerance_m)
            except (AttributeError, TypeError) as exc:     # never run silently without the approved rule
                raise RuntimeError('cannot install the planar height tolerance on this simulator') from exc
        before = clock.now_ns
        result = execute_original(self, command, pose_version)
        pulse = executed_pulse_ns(hw, command, before) if result.get('executed') else 0
        clock.advance(max(pulse, IDLE_TICK_NS))
        return result

    hw.HabitatCapture.capture = capture
    hw.HabitatCapture.execute = execute
    hw._neusymnav_sim_clock = clock
    return clock


def main() -> int:
    from neusymnav.sensors import habitat_worker as hw
    install(hw, os.environ.get('NEUSYMNAV_SIM_RUN_ID', 'objectnav'),
            float(os.environ.get('NEUSYMNAV_PLANAR_HEIGHT_TOLERANCE_M', WORKER_HEIGHT_TOLERANCE_M)))
    return hw.main()


if __name__ == '__main__':
    raise SystemExit(main())
