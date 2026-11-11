import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace

from PyQt5 import QtWidgets
import pytest

from neusymnav.contracts.room_semantics import RoomLabelResult
from neusymnav.rooms.debug_types import RoomLabelDebugJob, RoomLabelDebugRecord
from neusymnav.rooms.requests import make_room_label_request
from test_room_context import candidate, query, support


APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
CAPTURE_CLOCK = 'host_monotonic:boot-1'
MODEL_SHA = 'c' * 64
PROMPT_SHA = 'd' * 64
MODEL_MANIFEST_SHA = 'e' * 64
GRAMMAR_SHA = 'f' * 64


def _record(*, state='complete', world_epoch='world-1', result=True,
            evidence_quality=None, error=None):
    scene_query = query([candidate('O(0)', 'chair')])
    request, = make_room_label_request(scene_query, {}, support(), world_epoch=world_epoch)
    graph = replace(scene_query._projection, native_metadata={
        **scene_query._projection.native_metadata,
        'room_label_input': {'snapshot_sha256': 'b' * 64},
        'graph_world_epoch': world_epoch,
    })
    job = RoomLabelDebugJob(request, graph, offered_ns=9_000_000_001)
    label_result = None
    if result:
        label_result = RoomLabelResult(request.key.room_id, request.key.graph_revision,
            request.key.context_hash, 'kitchen', ('dining_room',), ('O(0)',), 'available',
            '<img src=x onerror=alert(1)>', MODEL_SHA, PROMPT_SHA)
    return RoomLabelDebugRecord(job, state, label_result, started_ns=9_000_000_002,
        completed_ns=9_000_000_003 if state in {'complete', 'error', 'cancelled'} else None,
        backend_metrics={'model_id': 'fixture-model', 'model_manifest_hash': MODEL_MANIFEST_SHA,
                         'grammar_sha256': GRAMMAR_SHA},
        evidence_quality=evidence_quality or {
            'tier': 'graph_only', 'verified': False,
            'association_counts': {'not_recorded': 1},
            'flags': ['no_visual_evidence'],
            'objects': [{'native_id': 'O(0)', 'association_status': 'not_recorded'}],
        }, error=error)


class FakeService:
    def __init__(self, records=(), *, current_graph=None, status=None):
        self.items = tuple(records)
        self.current_graph = current_graph
        self.status_value = dict(status or {})
        self.offers = []
        self.calls = []
        self.close_calls = []

    def offer(self, graph):
        self.calls.append('offer')
        self.offers.append(graph)
        return True

    def records(self):
        self.calls.append('records')
        return self.items

    def status(self):
        self.calls.append('status')
        return dict(self.status_value)

    def close(self, timeout_s=3):
        self.close_calls.append(timeout_s)
        return {'clean_shutdown': True}


def _widget(service, *, clock_domain=CAPTURE_CLOCK, now_ns=10_000_000_000):
    from neusymnav.visualization.room_label_debug import RoomLabelDebugWidget
    return RoomLabelDebugWidget(service, clock_domain=clock_domain, now_ns=lambda: now_ns)


def test_offer_graph_forwards_only_to_nonblocking_service_offer():
    record = _record()
    service = FakeService(current_graph=record.job.graph)
    widget = _widget(service)
    try:
        service.calls.clear()
        assert widget.offer_graph(record.job.graph) is True
        assert service.offers == [record.job.graph]
        assert service.calls == ['offer']
    finally:
        widget.close()
        APP.processEvents()


def test_selection_renders_the_record_source_graph_and_marks_newer_revision_historical():
    record = _record()
    latest_graph = replace(record.job.graph, graph_revision=10,
                           input_prefix_sha256='b' * 64)
    service = FakeService((record,), current_graph=latest_graph)
    widget = _widget(service)
    try:
        widget.refresh()
        assert widget.select_request(record.job.request.request_id) is True

        assert widget._displayed_graph is record.job.graph
        assert {node.native_id for node in widget.snapshot_graph.visible_graph.nodes} == {
            'O(0)', 'R(0)'}
        assert widget.snapshot_graph.graph_visibility.visible_layers == frozenset({2, 4})
        assert widget.snapshot_graph.graph_visibility.show_point_cloud is False
        assert 'HISTORICAL SOURCE SNAPSHOT' in widget.currentness_label.text()
        assert 'DEBUG HYPOTHESIS NOT VERIFIED' in widget.warning_caption.text()

        items_before = tuple(id(item) for item in widget.snapshot_graph.node_items.values())
        widget.refresh()
        assert tuple(id(item) for item in widget.snapshot_graph.node_items.values()) == items_before
    finally:
        widget.close()
        APP.processEvents()


def test_same_native_room_id_from_another_run_is_not_shown_as_current():
    record = _record()
    current = replace(record.job.graph, run_id='run-2')
    service = FakeService((record,), current_graph=current)
    widget = _widget(service)
    try:
        widget.refresh()
        assert widget.select_request(record.job.request.request_id)
        assert any(node.native_id == 'R(0)' for node in current.nodes)
        assert 'HISTORICAL SOURCE SNAPSHOT' in widget.currentness_label.text()
    finally:
        widget.close()
        APP.processEvents()


def test_epoch_reset_hides_old_record_from_current_badge():
    record = _record(world_epoch='world-before-reset')
    service = FakeService((record,), current_graph=record.job.graph,
        status={'world_epoch': 'world-after-reset'})
    widget = _widget(service)
    try:
        widget.refresh()
        assert widget.select_request(record.job.request.request_id)
        assert 'HISTORICAL SOURCE SNAPSHOT' in widget.currentness_label.text()
    finally:
        widget.close()
        APP.processEvents()


def test_details_are_plain_text_and_include_full_hashes_support_status_and_graph_only_warning():
    record = _record()
    service = FakeService((record,), current_graph=record.job.graph)
    widget = _widget(service)
    try:
        widget.refresh()
        assert widget.select_request(record.job.request.request_id)

        details = widget.details.toPlainText()
        assert f"input_prefix_sha256: {'a' * 64}" in details
        assert f"context_sha256: {record.job.request.key.context_hash}" in details
        assert f'model_sha256: {MODEL_SHA}' in details
        assert f'model_manifest_sha256: {MODEL_MANIFEST_SHA}' in details
        assert f'grammar_sha256: {GRAMMAR_SHA}' in details
        assert f'source_graph_geometry_signature_sha256: {"b" * 64}' in details
        assert 'supporting object O(0) · chair' in details
        assert 'association=not_recorded' in details
        assert 'evidence_count=0' in details
        assert '<img src=x onerror=alert(1)>' in details
        assert 'Graph-only support is unverified' in widget.evidence_warning.text()
        assert 'verified=False' in widget.evidence_warning.text()
        assert isinstance(widget.details, QtWidgets.QPlainTextEdit)
    finally:
        widget.close()
        APP.processEvents()


@pytest.mark.parametrize('state', ['pending', 'running', 'error', 'cancelled', 'complete'])
def test_refresh_exposes_each_service_state_without_losing_the_snapshot(state):
    record = _record(state=state, result=state == 'complete', error='worker failed' if state == 'error' else None)
    service = FakeService((record,), current_graph=record.job.graph)
    widget = _widget(service)
    try:
        widget.refresh()
        assert widget.select_request(record.job.request.request_id)
        assert state.upper() in widget.record_list.currentItem().text().upper()
        assert f'state: {state}' in widget.details.toPlainText()
        assert widget._displayed_graph is record.job.graph
        if state == 'pending':
            assert 'Graph-only context is unverified' in widget.evidence_warning.text()
        if state == 'complete':
            assert 'CURRENT SOURCE SNAPSHOT' in widget.currentness_label.text()
    finally:
        widget.close()
        APP.processEvents()


def test_snapshot_age_is_unavailable_when_capture_clock_domain_differs():
    record = _record()
    service = FakeService((record,), current_graph=record.job.graph)
    widget = _widget(service, clock_domain='ui_clock:other_boot')
    try:
        widget.refresh()
        assert widget.select_request(record.job.request.request_id)
        assert widget.snapshot_age_label.text() == 'Snapshot age: unavailable (clock domain mismatch)'
    finally:
        widget.close()
        APP.processEvents()


def test_service_counters_and_record_history_are_bounded_to_128_references():
    record = _record()
    active = _record(state='pending', result=False)
    service = FakeService((active,) + (record,) * 139, current_graph=record.job.graph,
        status={'pending': 2, 'in_flight': 1, 'coalesced_graphs': 4, 'evicted': 1,
                'error': 'fixture startup failure'})
    widget = _widget(service)
    try:
        widget.refresh()
        assert widget.record_list.count() == 128
        assert widget._records[0].state == 'pending'
        assert widget.record_list.item(0).text().startswith('PENDING')
        status = widget.service_status_label.text()
        assert 'queue=2' in status
        assert 'in_flight=1' in status
        assert 'dropped=4' in status
        assert 'coalesced_graphs=4' in status
        assert 'evicted=1' in status
        assert 'startup_errors=unknown' in status
        assert 'errors=unknown' in status
        assert 'last_error=fixture startup failure' in status
    finally:
        widget.close()
        APP.processEvents()


def test_missing_service_shows_waiting_state_and_close_does_not_close_service():
    record = _record()
    service = FakeService((record,), current_graph=record.job.graph)
    widget = _widget(None)
    widget.refresh()
    assert 'unavailable' in widget.service_status_label.text().lower()
    assert widget.record_list.count() == 0
    assert widget.offer_graph(record.job.graph) is False

    active = _widget(service)
    timer = active._refresh_timer
    assert timer.interval() == 250
    active.close()
    APP.processEvents()
    assert timer.isActive() is False
    assert service.close_calls == []
    widget.close()
    APP.processEvents()


def test_snapshot_draws_derived_membership_through_hidden_native_places():
    from neusymnav.visualization.room_label_debug import RoomLabelDebugWidget
    record=_record();widget=RoomLabelDebugWidget(FakeService((record,),current_graph=record.job.graph),clock_domain=CAPTURE_CLOCK)
    try:
        widget.refresh();assert widget.select_request(record.job.request.request_id)
        edges=widget.snapshot_graph.visible_graph.edges
        assert len([e for e in edges if e.kind=='derived_room_membership'])==1
        assert 'native parent' in widget.snapshot_graph.toolTip()
        assert not any(e.kind=='derived_room_membership' for e in record.job.graph.edges)
    finally:widget.close()
