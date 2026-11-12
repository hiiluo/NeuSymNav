"""Live latency path: threads/nice, warm prefix, compact transport, semantic reuse."""
import os
import time

from neusymnav.contracts.room_semantics import RoomLabelProposal
from neusymnav.rooms.compact_policy import STATIC_PREFIX
from test_room_persistent_backend import (FakeServerLauncher, backend_class, make_config,
    make_request, read_events)
from test_room_label_debug_service import FakeBackend, graph, wait
from test_hydra_scene_graph_query import _taxonomy


def test_persistent_compact_policy_end_to_end_with_threads_and_nice(tmp_path):
    events = tmp_path / 'events.jsonl'
    launcher = FakeServerLauncher(events_path=events)
    backend = backend_class()(make_config(tmp_path, prompt_policy='compact-v2', threads=4, nice=5),
        process_factory=launcher)
    try:
        result = backend.infer(make_request('O(7)'))
        assert result.status == 'proposed' and result.label == 'bathroom'
        assert result.supporting_object_ids == ('O(7)',)
        assert result.reason == 'supported by toilet O(7)'
        command = launcher.commands[0]
        threads = command[command.index('--threads') + 1]
        assert threads == command[command.index('--threads-batch') + 1]
        assert 1 <= int(threads) <= 4
        assert backend.last_metrics['prompt_policy'] == 'compact-v2'
        assert backend.last_metrics['scheduling']['nice'] in (5, 'failed')
        completion = [row for row in read_events(events) if row['event'] == 'completion'][0]
        assert completion['max_tokens'] <= 64 and completion['cache_prompt'] is True
        assert 'root ::=' in completion['grammar']
        pid = launcher.processes[0].pid
        if backend.last_metrics['scheduling']['nice'] == 5:
            assert os.getpriority(os.PRIO_PROCESS, pid) >= 5
    finally:
        assert backend.close(timeout_s=1.0)['clean_shutdown']


def test_warm_prefills_static_prefix_and_first_request_reuses_server(tmp_path):
    events = tmp_path / 'events.jsonl'
    launcher = FakeServerLauncher(modes=('warm_probe',), events_path=events)
    backend = backend_class()(make_config(tmp_path, prompt_policy='compact-v2'),
        process_factory=launcher)
    try:
        report = backend.warm()
        assert report['warmed'] is True, report
        warm = [row for row in read_events(events) if row['event'] == 'warm']
        assert warm and warm[0]['prefix_chars'] == len(STATIC_PREFIX) and warm[0]['cache_prompt'] is True
        result = backend.infer(make_request('O(0)'))
        assert result.status == 'proposed'
        assert backend.last_metrics['server_reused'] is True
        assert len(launcher.processes) == 1
    finally:
        assert backend.close(timeout_s=1.0)['clean_shutdown']


def test_warm_is_a_noop_for_json_v1_and_disabled(tmp_path):
    launcher = FakeServerLauncher()
    assert backend_class()(make_config(tmp_path), process_factory=launcher).warm()['warmed'] is False
    assert backend_class()(make_config(tmp_path, enabled=False, prompt_policy='compact-v2'),
        process_factory=launcher).warm()['reason'] == 'model_runtime_disabled'
    assert launcher.processes == []


class CountingBackend(FakeBackend):
    def __init__(self):
        super().__init__()
        self.release.set()
        self.warmed = 0

    def warm(self):
        self.warmed += 1
        return {'warmed': True}


def test_semantic_cache_reuses_unchanged_room_and_recomputes_changed_room():
    from neusymnav.rooms.service import RoomLabelDebugService
    from neusymnav.rooms.debug_types import record_is_current
    backend = CountingBackend()
    svc = RoomLabelDebugService(backend, _taxonomy(), debounce_s=0)
    try:
        wait(lambda: svc.status()['warmup'] == {'warmed': True})
        svc.offer(graph(rev=1))
        wait(lambda: len(backend.calls) == 1 and svc.status()['completed'] == 1)
        for rev in (2, 3, 4):
            svc.offer(graph(rev=rev))
            wait(lambda: any(r.state == 'complete' and r.job.request.key.graph_revision == rev
                for r in svc.records()))
        assert len(backend.calls) == 1
        latest = next(r for r in svc.records() if r.job.request.key.graph_revision == 4)
        assert record_is_current(latest, svc.current_graph)
        assert latest.result.label == 'bathroom' and latest.backend_metrics['semantic_cache'] == 'hit'
        # Reuse records replace each other; history keeps model answer + newest reuse.
        revisions = sorted(r.job.request.key.graph_revision for r in svc.records())
        assert revisions == [1, 4]
        assert svc.status()['semantic_cache_hits'] == 3 and svc.status()['model_inferences'] == 1

        svc.offer(graph(category='bed', rev=5))
        wait(lambda: len(backend.calls) == 2)
        assert backend.calls[-1].context.objects[0].category == 'bed'
    finally:
        assert svc.close(2)['clean_shutdown']


def test_failed_model_answers_are_not_cached():
    from neusymnav.rooms.service import RoomLabelDebugService

    class TimeoutBackend(CountingBackend):
        def infer(self, req):
            self.calls.append(req)
            return RoomLabelProposal(req.key.room_id, req.key.graph_revision, req.key.context_hash,
                'unknown', (), (), 'timeout', 'room_label_job_deadline', None, None)

    backend = TimeoutBackend()
    svc = RoomLabelDebugService(backend, _taxonomy(), debounce_s=0)
    try:
        svc.offer(graph(rev=1))
        wait(lambda: len(backend.calls) == 1 and svc.status()['completed'] == 1)
        svc.offer(graph(rev=2))
        wait(lambda: len(backend.calls) == 2)
        assert svc.status()['semantic_cache_hits'] == 0
    finally:
        assert svc.close(2)['clean_shutdown']


def test_history_artifact_writes_are_throttled(tmp_path):
    from neusymnav.rooms import service as module
    backend = CountingBackend()
    svc = module.RoomLabelDebugService(backend, _taxonomy(), artifact_root=tmp_path, debounce_s=0)
    writes = []
    original = svc._write
    svc._write = lambda: (writes.append(time.monotonic()), original())
    try:
        for rev in range(1, 30):
            svc.offer(graph(rev=rev))
            time.sleep(0.01)
        time.sleep(0.3)
        assert len(writes) <= 3
    finally:
        assert svc.close(2)['clean_shutdown']
    assert (tmp_path / 'history.json').exists()


def test_overlay_shows_only_exact_current_labels():
    from neusymnav.rooms.service import RoomLabelDebugService
    from neusymnav.rooms.label_overlay import current_room_labels
    backend = CountingBackend()
    svc = RoomLabelDebugService(backend, _taxonomy(), debounce_s=0)
    try:
        g1 = graph(rev=1)
        svc.offer(g1)
        wait(lambda: svc.status()['completed'] == 1)
        room = next(n.node_id for n in g1.nodes if n.layer_id == 4)
        assert current_room_labels(svc.records(), g1) == {room: 'SLM bathroom'}
        g2 = graph(rev=2)
        # Before the service has bound an answer to rev 2, nothing old is shown on it.
        assert current_room_labels(svc.records(), g2) == {}
        svc.offer(g2)
        wait(lambda: current_room_labels(svc.records(), g2) == {room: 'SLM bathroom'})
        assert current_room_labels(svc.records(), None) == {}
    finally:
        assert svc.close(2)['clean_shutdown']


def test_vlm_overlay_keeps_backend_name_while_waiting_and_abstaining():
    from dataclasses import replace

    from neusymnav.contracts.room_semantics import RoomLabelResult
    from neusymnav.rooms.debug_context import build_debug_jobs
    from neusymnav.rooms.debug_types import RoomLabelDebugRecord
    from neusymnav.rooms.label_overlay import current_room_labels

    g1, g2 = graph(rev=1), graph(rev=2)
    job = build_debug_jobs(g1, _taxonomy(), 0)[0]
    key = job.request.key
    running = RoomLabelDebugRecord(job, 'running')
    result = RoomLabelResult(key.room_id, key.graph_revision, key.context_hash,
                             'unknown', (), (), 'insufficient_evidence',
                             'room_geometry_unavailable', None, None)
    blocked = replace(running, state='complete', result=result)
    assert current_room_labels((), g1, backend='vlm') == {key.room_id: 'VLM pending'}
    assert current_room_labels((running,), g1, backend='vlm') == {key.room_id: 'VLM …'}
    assert current_room_labels((blocked,), g1, backend='vlm') == {key.room_id: 'VLM unknown'}
    assert current_room_labels((blocked,), g2, backend='vlm') == {key.room_id: 'VLM pending'}
