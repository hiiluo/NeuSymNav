"""Graph lane polls Hydra only after state changes (00806 v6 GIL contention).

`HydraSession.snapshot()` deep-copies the whole graph summary and the runtime
projection re-validates every node; the graph lane used to call both on every
wake (up to ~100 Hz), which took ~60 % of a core and starved control.
"""
from types import SimpleNamespace

from test_hydra_session import worker
from neusymnav.backends.hydra.session import HydraSession
from neusymnav.backends.hydra.runtime import HydraGraphRuntime


def test_session_state_token_tracks_snapshot_relevant_state(tmp_path):
    session = HydraSession('ep', command=worker(tmp_path, ''), journal_path=tmp_path / 'j.jsonl')
    try:
        token = session.state_token()
        assert session.state_token() == token  # stable without changes
        with session._condition:
            session._revision += 1
        advanced = session.state_token()
        assert advanced != token
        with session._condition:
            session._failure = 'boom'
        assert session.state_token() != advanced
    finally:
        session.close(2.)


class _Session:
    def __init__(self):
        self.token = (0,)
        self.snapshots = 0

    def state_token(self):
        return self.token

    def snapshot(self):
        self.snapshots += 1
        return SimpleNamespace(graph_summary=None)


def test_runtime_projection_is_reused_until_the_session_token_changes():
    runtime = HydraGraphRuntime.__new__(HydraGraphRuntime)
    runtime.session = _Session()
    calls = []
    runtime._project = lambda snapshot: calls.append(snapshot) or object()
    first = runtime.projection()
    assert runtime.projection() is first and len(calls) == 1 and runtime.session.snapshots == 1
    runtime.session.token = (1,)
    second = runtime.projection()
    assert second is not first and len(calls) == 2
    # An explicit snapshot is always projected (query path keeps its semantics).
    runtime.projection(_snapshot=SimpleNamespace(graph_summary=None))
    assert len(calls) == 3


def test_graph_lane_polls_only_on_token_change():
    from neusymnav.runtime import Pipeline
    p = Pipeline.__new__(Pipeline)
    p._hydra_polled_token = None
    p.hydra_poll_counts = dict(polled=0, skipped=0)
    runtime = SimpleNamespace(token=(0,))
    runtime.state_token = lambda: runtime.token
    assert p._hydra_poll_due(runtime)
    assert not p._hydra_poll_due(runtime) and not p._hydra_poll_due(runtime)
    runtime.token = (1,)
    assert p._hydra_poll_due(runtime)
    assert p.hydra_poll_counts == dict(polled=2, skipped=2)
    # Runtimes without a token keep the previous always-poll behaviour.
    assert p._hydra_poll_due(SimpleNamespace())
