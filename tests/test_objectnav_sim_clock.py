import hashlib
import importlib
from pathlib import Path

import pytest

from neusymnav.objectnav import sim_worker_entry as sim

LOCKED_WORKER = Path(__file__).resolve().parents[1] / 'src/neusymnav/sensors/habitat_worker.py'


@pytest.fixture
def hw():
    # A fresh, unpatched module per test; habitat_sim itself is never imported.
    import neusymnav.sensors.habitat_worker as module
    module.__dict__.pop('_neusymnav_sim_clock', None)
    module = importlib.reload(module)
    yield module
    module.__dict__.pop('_neusymnav_sim_clock', None)
    importlib.reload(module)


def _command(v, deadline, issued):
    return dict(linear_mps=v, yaw_radps=0.0 if v else 0.5, deadline_monotonic_ns=deadline,
                issued_monotonic_ns=issued)


def test_clock_domain_and_time_source_are_replaced_without_touching_the_file(hw):
    before = hashlib.sha256(LOCKED_WORKER.read_bytes()).hexdigest()
    clock = sim.install(hw, 'run1')
    assert hw.host_clock_domain() == 'sim_lockstep:run1'
    assert hw.time.monotonic_ns() == sim.START_NS and hw.time.sleep is not None
    assert hashlib.sha256(LOCKED_WORKER.read_bytes()).hexdigest() == before
    with pytest.raises(RuntimeError):
        sim.install(hw, 'run2')
    assert clock is hw._neusymnav_sim_clock


def test_capture_and_execute_advance_simulated_time_deterministically(hw, monkeypatch):
    calls = []
    monkeypatch.setattr(hw.HabitatCapture, 'capture', lambda self, lane: calls.append(('c', hw.time.monotonic_ns())) or {})
    monkeypatch.setattr(hw.HabitatCapture, 'execute',
                        lambda self, command, pv: {'executed': command['linear_mps'] != 99})
    clock = sim.install(hw, 'r')
    worker = object.__new__(hw.HabitatCapture)
    worker.capture('navigation'); worker.capture('primary')
    t = clock.now_ns
    assert [c[1] for c in calls] == [sim.START_NS, sim.START_NS + sim.CAPTURE_TICK_NS]
    worker.execute(_command(0.3, t + 250_000_000, t), 0)          # translation granted 250 ms
    assert clock.now_ns == t + 250_000_000
    t = clock.now_ns
    worker.execute(_command(0.3, t + 900_000_000, t), 0)          # capped at 300 ms
    assert clock.now_ns == t + hw.MAX_TRANSLATION_PULSE_NS
    t = clock.now_ns
    worker.execute(_command(0.0, t + 900_000_000, t), 0)          # rotation capped at 500 ms
    assert clock.now_ns == t + hw.MAX_ROTATION_PULSE_NS
    t = clock.now_ns
    worker.execute(_command(99, t + 50_000_000, t), 0)            # not executed: idle tick
    assert clock.now_ns == t + sim.IDLE_TICK_NS


def test_bad_run_id_and_backwards_time_are_refused(hw):
    with pytest.raises(ValueError):
        sim.install(hw, 'a:b')
    clock = sim.SimTime()
    with pytest.raises(ValueError):
        clock.advance(-1)
