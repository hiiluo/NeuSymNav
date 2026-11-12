"""Read-only Qt view for revision-pinned room-label debug snapshots.

This widget displays service-owned immutable records. It never builds a room
request, invokes a model, or attaches a label to the latest graph by room ID.
"""
from __future__ import annotations

import json
from dataclasses import replace
import time
from collections.abc import Mapping

from PyQt5 import QtCore, QtGui, QtWidgets

from ..rooms.debug_types import RoomLabelDebugRecord, record_is_current
from .graph_visibility import GraphVisibility
from .scene_graph import SceneGraphWidget


MAX_RECORD_REFS = 128
_NO_VALUE = object()


def _jsonable(value):
    """Convert immutable contract mappings to deterministic plain JSON data."""
    if isinstance(value, Mapping):
        return {str(key): _jsonable(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, 'to_dict'):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            pass
    return repr(value)


def _request_key(record: RoomLabelDebugRecord) -> tuple:
    key = record.job.request.key
    return (key.episode_id, key.run_id, key.room_id, key.graph_revision,
            key.input_prefix_sha256, key.context_hash, key.world_epoch)


def _result_signature(record: RoomLabelDebugRecord) -> tuple | None:
    result = record.result
    if result is None:
        return None
    return (result.room_id, result.geometry_revision, result.input_evidence_hash,
            result.label, tuple(result.alternatives), tuple(result.supporting_object_ids),
            tuple(result.supporting_view_ids),
            result.status, result.reason, result.model_sha256, result.prompt_sha256)


def _mapping_signature(value) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def _record_row_signature(record: RoomLabelDebugRecord) -> tuple:
    return (_request_key(record), record.state, _result_signature(record))


def _record_signature(record: RoomLabelDebugRecord) -> tuple:
    return (_record_row_signature(record), record.job.offered_ns, record.started_ns,
            record.completed_ns, record.error,
            _mapping_signature(record.backend_metrics),
            _mapping_signature(record.evidence_quality))


def _first_text(*values) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _short_hash(value: str | None) -> str:
    return value[:12] if isinstance(value, str) and value else 'unavailable'


def _plain_label(label: str, status: str) -> str:
    if status in {'available', 'proposed'}:
        return label
    if status == 'unknown' or label == 'unknown':
        return 'unknown'
    return label


def _status_value(status: Mapping, *names):
    for name in names:
        value = status.get(name, _NO_VALUE)
        if value is not _NO_VALUE:
            return value
    return _NO_VALUE


class RoomLabelDebugWidget(QtWidgets.QWidget):
    """Show pending and completed label hypotheses against their source graph."""

    def __init__(self, service, *, clock_domain: str,
                 now_ns=time.monotonic_ns, parent=None):
        super().__init__(parent)
        if not isinstance(clock_domain, str) or not clock_domain:
            raise ValueError('clock_domain must be nonempty text')
        if not callable(now_ns):
            raise TypeError('now_ns must be callable')

        self.service = service
        self.clock_domain = clock_domain
        self._now_ns = now_ns
        self._records: tuple[RoomLabelDebugRecord, ...] = ()
        self._records_by_request: dict[str, RoomLabelDebugRecord] = {}
        self._row_signature: tuple = ()
        self._selected_request_id: str | None = None
        self._displayed_graph = None
        self._displayed_support_ids: tuple[str, ...] = ()
        self._displayed_record_signature = None
        self._current_graph = None
        self._service_status: dict = {}
        self._restoring_selection = False

        self.setObjectName('roomLabelDebugWidget')
        self.setMinimumSize(900, 560)
        self._build_ui()
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setInterval(250)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)

        self.warning_caption = QtWidgets.QLabel('DEBUG HYPOTHESIS NOT VERIFIED', self)
        self.warning_caption.setObjectName('debugHypothesisCaption')
        self.warning_caption.setTextFormat(QtCore.Qt.PlainText)
        self.warning_caption.setStyleSheet(
            'QLabel { color: #ffd28b; background: #38291c; border: 1px solid #8c6030; '
            'padding: 7px 10px; font-weight: bold; letter-spacing: 1px; }')
        root.addWidget(self.warning_caption)

        self.service_status_label = QtWidgets.QLabel('Waiting for room-label service', self)
        self.service_status_label.setObjectName('roomLabelServiceStatus')
        self.service_status_label.setTextFormat(QtCore.Qt.PlainText)
        self.service_status_label.setWordWrap(True)
        root.addWidget(self.service_status_label)

        split = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        split.setChildrenCollapsible(False)
        root.addWidget(split, 1)

        history = QtWidgets.QWidget(split)
        history_layout = QtWidgets.QVBoxLayout(history)
        history_layout.setContentsMargins(0, 0, 7, 0)
        title = QtWidgets.QLabel('Requests and history', history)
        title.setStyleSheet('font-weight: bold; color: #d9e4f1;')
        history_layout.addWidget(title)
        self.record_list = QtWidgets.QListWidget(history)
        self.record_list.setObjectName('roomLabelHistory')
        self.record_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.record_list.currentItemChanged.connect(self._selection_changed)
        history_layout.addWidget(self.record_list, 1)
        split.addWidget(history)

        detail_panel = QtWidgets.QWidget(split)
        detail_layout = QtWidgets.QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(7, 0, 0, 0)
        detail_layout.setSpacing(6)

        self.currentness_label = QtWidgets.QLabel('Waiting for a source snapshot', detail_panel)
        self.currentness_label.setObjectName('roomLabelCurrentness')
        self.currentness_label.setTextFormat(QtCore.Qt.PlainText)
        self.currentness_label.setStyleSheet('font-weight: bold; color: #9bc7ff;')
        detail_layout.addWidget(self.currentness_label)

        self.snapshot_age_label = QtWidgets.QLabel('Snapshot age: unavailable', detail_panel)
        self.snapshot_age_label.setObjectName('roomLabelSnapshotAge')
        self.snapshot_age_label.setTextFormat(QtCore.Qt.PlainText)
        detail_layout.addWidget(self.snapshot_age_label)

        self.summary_label = QtWidgets.QLabel('No room-label snapshot selected', detail_panel)
        self.summary_label.setObjectName('roomLabelResultSummary')
        self.summary_label.setTextFormat(QtCore.Qt.PlainText)
        self.summary_label.setStyleSheet('font-size: 15px; font-weight: bold; color: #e5edf8;')
        detail_layout.addWidget(self.summary_label)

        self.evidence_warning = QtWidgets.QLabel('Waiting for room-label evidence', detail_panel)
        self.evidence_warning.setObjectName('roomLabelEvidenceWarning')
        self.evidence_warning.setTextFormat(QtCore.Qt.PlainText)
        self.evidence_warning.setWordWrap(True)
        self.evidence_warning.setStyleSheet('color: #f1bd79;')
        detail_layout.addWidget(self.evidence_warning)

        contents = QtWidgets.QSplitter(QtCore.Qt.Vertical, detail_panel)
        contents.setChildrenCollapsible(False)
        detail_layout.addWidget(contents, 1)

        self.details = QtWidgets.QPlainTextEdit(contents)
        self.details.setObjectName('roomLabelSnapshotDetails')
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.details.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.details.setPlaceholderText('Select a room-label request to inspect its full source and hashes.')
        contents.addWidget(self.details)

        self.snapshot_graph = SceneGraphWidget(contents)
        self.snapshot_graph.setObjectName('roomLabelSourceGraph')
        self.snapshot_graph.set_graph_visibility(
            replace(GraphVisibility.for_preset('rooms_objects'),show_point_cloud=False,show_derived_membership=True))
        self.snapshot_graph.setToolTip('Dashed links: room membership derived from the recorded native parent chain; not native edges or traversability proof.')
        contents.addWidget(self.snapshot_graph)
        contents.setSizes([300, 300])
        split.addWidget(detail_panel)
        split.setSizes([310, 900])

        self.setStyleSheet('''
            QWidget#roomLabelDebugWidget { background: #101923; color: #d9e4f1; }
            QWidget#roomLabelDebugWidget QLabel { color: #d9e4f1; }
            QListWidget, QPlainTextEdit { background: #0b131d; color: #d9e4f1;
                border: 1px solid #2b3b4c; selection-background-color: #264c70; }
            QListWidget::item { padding: 6px 5px; }
            QListWidget::item:selected { color: #ffffff; }
        ''')
        self._show_empty_graph('Waiting for a source graph snapshot')

    def offer_graph(self, graph) -> bool:
        """Forward one immutable graph projection to the bounded service queue."""
        if self.service is None:
            return False
        return bool(self.service.offer(graph))

    def refresh(self):
        """Read service snapshots and refresh only changed list/detail content."""
        if self.service is None:
            self._current_graph = None
            self._service_status = {}
            self.service_status_label.setText('Service unavailable · waiting for room-label service')
            self._update_record_list(())
            return

        try:
            # The service places the active record first, followed by history.
            # Preserve that order when applying the widget's display cap.
            records = tuple(self.service.records() or ())[:MAX_RECORD_REFS]
            current_graph = self.service.current_graph
            status = self.service.status()
            if not isinstance(status, Mapping):
                status = {}
            self._records = tuple(record for record in records
                                  if isinstance(record, RoomLabelDebugRecord))
            self._current_graph = current_graph
            self._service_status = dict(status)
            self._records_by_request = {
                record.job.request.request_id: record for record in self._records
            }
            self._update_service_status()
            self._update_record_list(self._records)
            self._refresh_selected_record()
        except Exception as exc:
            self.service_status_label.setText(
                f'Service snapshot unavailable · {type(exc).__name__}: {exc}')
            self.service_status_label.setTextFormat(QtCore.Qt.PlainText)

    def select_request(self, request_id: str) -> bool:
        """Select a record by its complete deterministic request ID."""
        if not isinstance(request_id, str):
            return False
        items = [self.record_list.item(index)
                 for index in range(self.record_list.count())
                 if self.record_list.item(index).data(QtCore.Qt.UserRole + 1) == request_id]
        if not items:
            return False
        item = items[-1]
        self.record_list.setCurrentItem(item)
        self._selected_request_id = request_id
        self._refresh_selected_record(force=True)
        return True

    @property
    def selected_record(self) -> RoomLabelDebugRecord | None:
        if self._selected_request_id is None:
            return None
        return self._records_by_request.get(self._selected_request_id)

    def _update_service_status(self):
        status = self._service_status
        queue = _status_value(status, 'queue_depth', 'queued', 'queue_size', 'pending')
        in_flight = _status_value(status, 'in_flight', 'active')
        coalesced = _status_value(status, 'coalesced_graphs', 'coalesced', 'replaced')
        dropped = _status_value(status, 'dropped', 'dropped_count', 'replaced_count')
        if dropped is _NO_VALUE:
            dropped = coalesced
        evicted = _status_value(status, 'evicted', 'evicted_count')
        startup_errors = _status_value(status, 'startup_errors', 'startup_error_count')
        errors = _status_value(status, 'errors', 'error_count', 'failed', 'failed_count')
        fields = []
        for name, value in (('queue', queue), ('in_flight', in_flight),
                            ('dropped', dropped), ('coalesced_graphs', coalesced),
                            ('evicted', evicted),
                            ('startup_errors', startup_errors), ('errors', errors)):
            fields.append(f'{name}={"unknown" if value is _NO_VALUE else value}')
        last_error = status.get('error')
        if isinstance(last_error, str) and last_error:
            fields.append(f'last_error={last_error}')
        if self._records:
            newest = self._records[-1]
            unverified = sum(item.association_status != 'native_confirmed'
                             for item in newest.job.request.context.objects)
            fields.append(f'association_unverified={unverified}')
        else:
            fields.append('association_unverified=unknown')
        service_state = _first_text(status.get('state'), status.get('status')) or 'active'
        self.service_status_label.setText(
            f'Room-label service: {service_state} · ' + ' · '.join(fields))

    def _update_record_list(self, records: tuple[RoomLabelDebugRecord, ...]):
        row_signature = tuple(_record_row_signature(record) for record in records)
        if row_signature == self._row_signature:
            return

        previous_selection = self._selected_request_id
        self._restoring_selection = True
        try:
            self.record_list.clear()
            for record in records:
                item = QtWidgets.QListWidgetItem(self._record_caption(record))
                item.setData(QtCore.Qt.UserRole, record.job.request.request_id)
                item.setData(QtCore.Qt.UserRole + 1, record.job.request.request_id)
                item.setToolTip(record.job.request.key.room_id)
                self.record_list.addItem(item)

            selected_item = None
            if previous_selection is not None:
                items = [self.record_list.item(index)
                         for index in range(self.record_list.count())
                         if self.record_list.item(index).data(QtCore.Qt.UserRole + 1)
                         == previous_selection]
                if items:
                    selected_item = items[-1]
            if selected_item is None and self.record_list.count():
                selected_item = self.record_list.item(self.record_list.count() - 1)
            self.record_list.setCurrentItem(selected_item)
            self._selected_request_id = (None if selected_item is None else
                                         selected_item.data(QtCore.Qt.UserRole))
            self._row_signature = row_signature
        finally:
            self._restoring_selection = False

    @staticmethod
    def _record_caption(record: RoomLabelDebugRecord) -> str:
        result = record.result
        if result is None:
            outcome = record.state
        else:
            outcome = f'{result.status}: {_plain_label(result.label, result.status)}'
        key = record.job.request.key
        return f'{record.state.upper()} · {outcome} · {key.room_id} · r{key.graph_revision}'

    def _selection_changed(self, current, _previous):
        if self._restoring_selection:
            return
        self._selected_request_id = None if current is None else current.data(QtCore.Qt.UserRole)
        self._refresh_selected_record(force=True)

    def _refresh_selected_record(self, *, force=False):
        record = self.selected_record
        if record is None:
            self._show_empty_selection()
            return

        key = record.job.request.key
        is_current = self._record_is_current_for_display(record)
        currentness = ('CURRENT SOURCE SNAPSHOT' if is_current else
                       'HISTORICAL SOURCE SNAPSHOT')
        if self._service_status.get('world_epoch', _NO_VALUE) != _NO_VALUE:
            currentness += f' · world epoch {self._service_status["world_epoch"]}'
        self.currentness_label.setText(currentness)
        self.currentness_label.setStyleSheet(
            'font-weight: bold; color: #8fd3ad;' if is_current else
            'font-weight: bold; color: #ffbb83;')
        self.snapshot_age_label.setText(self._snapshot_age(record))

        if record.result is None:
            self.summary_label.setText(f'State: {record.state} · no result attached')
        else:
            result = record.result
            self.summary_label.setText(
                f'State: {record.state} · result: {result.status} · '
                f'hypothesis: {_plain_label(result.label, result.status)}')

        self.evidence_warning.setText(self._evidence_warning(record))
        signature = (_record_signature(record), currentness)
        if force or signature != self._displayed_record_signature:
            self.details.setPlainText(self._details_text(record, currentness))
            self._displayed_record_signature = signature

        graph = record.job.graph
        if graph is not self._displayed_graph:
            self._displayed_graph = graph
            self.snapshot_graph._selected_id = None
            self.snapshot_graph._set_hydra_graph(graph)
            self._displayed_support_ids = ()
        support_ids = (() if record.result is None else
                       tuple(record.result.supporting_object_ids))
        if support_ids != self._displayed_support_ids:
            support_set = set(support_ids)
            support_node = next((node for node in graph.nodes
                                 if node.layer_id == 2 and node.native_id in support_set), None)
            self.snapshot_graph.select_object(None if support_node is None else support_node.node_id)
            self._displayed_support_ids = support_ids

    def _record_is_current_for_display(self, record: RoomLabelDebugRecord) -> bool:
        if not record_is_current(record, self._current_graph):
            return False
        current_epoch = self._service_status.get('world_epoch', _NO_VALUE)
        if current_epoch is not _NO_VALUE:
            return record.job.request.key.world_epoch == current_epoch
        return True

    def _snapshot_age(self, record: RoomLabelDebugRecord) -> str:
        source = record.job.graph.last_source or {}
        capture_ns = source.get('capture_monotonic_ns')
        capture_domain = source.get('clock_domain')
        if capture_ns is None:
            capture_ns = record.job.request.source_manifest.get('capture_monotonic_ns')
            capture_domain = record.job.request.source_manifest.get('clock_domain', capture_domain)
        if type(capture_ns) is not int or not isinstance(capture_domain, str):
            return 'Snapshot age: unavailable (capture timestamp not recorded)'
        if capture_domain != self.clock_domain:
            return 'Snapshot age: unavailable (clock domain mismatch)'
        try:
            now = self._now_ns()
        except Exception:
            return 'Snapshot age: unavailable (UI clock unavailable)'
        if type(now) is not int or now < capture_ns:
            return 'Snapshot age: unavailable (capture timestamp is in the future)'
        age_ms = (now - capture_ns) / 1_000_000
        if age_ms < 1000:
            return f'Snapshot age: {age_ms:.0f} ms · {capture_domain}'
        return f'Snapshot age: {age_ms / 1000:.2f} s · {capture_domain}'

    @staticmethod
    def _evidence_warning(record: RoomLabelDebugRecord) -> str:
        quality = record.evidence_quality
        tier = quality.get('tier')
        flags = quality.get('flags', ())
        quality_note = ''
        if quality.get('verified') is False:
            flag_text = ', '.join(str(flag) for flag in flags) if flags else 'no verified visual link'
            quality_note = f'Evidence quality {tier or "unverified"}; verified=False · {flag_text}. '
        supports = (() if record.result is None else record.result.supporting_object_ids)
        by_id = {row.native_id: row for row in record.job.request.context.objects}
        if record.result is None:
            if any(row.evidence_count <= 0 or row.association_status != 'native_confirmed'
                   for row in record.job.request.context.objects):
                return (quality_note + 'Graph-only context is unverified; no image evidence is confirmed for '
                        'the room objects in this request.')
            return quality_note + 'No result support is attached yet; this label remains a debug hypothesis.'
        rows = [by_id.get(native_id) for native_id in supports]
        if not supports:
            return quality_note + 'No supporting objects are attached; this label is a debug hypothesis.'
        if any(row is None or row.evidence_count <= 0 or
               row.association_status != 'native_confirmed' for row in rows):
            return (quality_note + 'Graph-only support is unverified: one or more supporting objects lack '
                    'native-confirmed visual association.')
        evidence_count = sum(row.evidence_count for row in rows if row is not None)
        return (quality_note + f'{evidence_count} linked visual evidence reference(s); image payload is not '
                'shown in this snapshot.')

    def _details_text(self, record: RoomLabelDebugRecord, currentness: str) -> str:
        request = record.job.request
        key = request.key
        result = record.result
        metrics = record.backend_metrics
        manifest = request.source_manifest
        model_hash = _first_text(
            None if result is None else result.model_sha256,
            metrics.get('model_sha256'), metrics.get('model_hash'),
            manifest.get('model_sha256'), self._service_status.get('model_sha256'))
        model_manifest_hash = _first_text(
            metrics.get('model_manifest_hash'), metrics.get('model_manifest_sha256'),
            manifest.get('model_manifest_hash'), self._service_status.get('model_manifest_hash'))
        grammar_hash = _first_text(
            metrics.get('grammar_sha256'), metrics.get('grammar_hash'),
            manifest.get('grammar_sha256'), self._service_status.get('grammar_sha256'))
        prompt_hash = _first_text(
            None if result is None else result.prompt_sha256,
            metrics.get('prompt_sha256'), manifest.get('prompt_sha256'))
        source_hashes = request.context.source_hashes
        geometry_signature = ((record.job.graph.native_metadata.get('room_label_input') or {})
                              .get('snapshot_sha256'))
        lines = [
            f'state: {record.state}',
            f'result_status: {"unavailable" if result is None else result.status}',
            f'label_hypothesis: {"unavailable" if result is None else _plain_label(result.label, result.status)}',
            f'episode_id: {key.episode_id}',
            f'run_id: {key.run_id}',
            f'room_id: {key.room_id}',
            f'geometry_revision: {key.graph_revision}',
            f'input_prefix_sha256_short: {_short_hash(key.input_prefix_sha256)}',
            f'input_prefix_sha256: {key.input_prefix_sha256}',
            f'context_sha256_short: {_short_hash(key.context_hash)}',
            f'context_sha256: {key.context_hash}',
            f'geometry_sha256: {key.geometry_hash or "unavailable"}',
            f'source_graph_geometry_signature_sha256: {geometry_signature or "unavailable"}',
            f'world_epoch: {key.world_epoch or "unavailable"}',
            f'currentness: {currentness}',
            f'model_id: {_first_text(metrics.get("model_id"), manifest.get("model_id"), self._service_status.get("model_id")) or "unavailable"}',
            f'model_sha256_short: {_short_hash(model_hash)}',
            f'model_sha256: {model_hash or "unavailable"}',
            f'model_manifest_sha256_short: {_short_hash(model_manifest_hash)}',
            f'model_manifest_sha256: {model_manifest_hash or "unavailable"}',
            f'grammar_sha256_short: {_short_hash(grammar_hash)}',
            f'grammar_sha256: {grammar_hash or "unavailable"}',
            f'prompt_sha256: {prompt_hash or "unavailable"}',
            f'grammar_policy_version: {_first_text(metrics.get("grammar_policy_version"), manifest.get("grammar_policy_version")) or "unavailable"}',
            f'offered_ns: {record.job.offered_ns}',
            f'started_ns: {record.started_ns if record.started_ns is not None else "unavailable"}',
            f'completed_ns: {record.completed_ns if record.completed_ns is not None else "unavailable"}',
            f'capture_clock_domain: {self._capture_clock_domain(record) or "unavailable"}',
            f'error: {record.error or "none"}',
            'source_manifest:',
            json.dumps(_jsonable(manifest), sort_keys=True, indent=2, ensure_ascii=True),
            'source_hashes:',
            json.dumps(_jsonable(source_hashes), sort_keys=True, indent=2, ensure_ascii=True),
            'backend_metrics:',
            json.dumps(_jsonable(metrics), sort_keys=True, indent=2, ensure_ascii=True),
            'evidence_quality:',
            json.dumps(_jsonable(record.evidence_quality), sort_keys=True, indent=2, ensure_ascii=True),
        ]
        if result is not None:
            lines.extend([
                f'reason: {result.reason or "none"}',
                f'alternatives: {", ".join(result.alternatives) if result.alternatives else "none"}',
                f'supporting_view_ids: {", ".join(result.supporting_view_ids) or "none"}',
            ])
        lines.append('supporting_object_ids:')
        supports = () if result is None else result.supporting_object_ids
        by_id = {row.native_id: row for row in request.context.objects}
        if not supports:
            lines.append('  none')
        for native_id in supports:
            row = by_id.get(native_id)
            if row is None:
                lines.append(f'  {native_id} · category unavailable · association=unavailable · evidence_count=0')
            else:
                lines.append(
                    f'  supporting object {native_id} · {row.category} · '
                    f'membership={row.membership_status} · association={row.association_status} · '
                    f'evidence_count={row.evidence_count}')
        lines.append('context_objects:')
        if not request.context.objects:
            lines.append('  none')
        for row in request.context.objects:
            lines.append(f'  {row.native_id} · {row.category} · membership={row.membership_status} · '
                         f'association={row.association_status} · evidence_count={row.evidence_count}')
        return '\n'.join(lines)

    @staticmethod
    def _capture_clock_domain(record: RoomLabelDebugRecord) -> str | None:
        source = record.job.graph.last_source or {}
        domain = source.get('clock_domain')
        if isinstance(domain, str):
            return domain
        value = record.job.request.source_manifest.get('clock_domain')
        return value if isinstance(value, str) else None

    def _show_empty_selection(self):
        self.currentness_label.setText('Waiting for a source snapshot')
        self.snapshot_age_label.setText('Snapshot age: unavailable')
        self.summary_label.setText('No room-label snapshot selected')
        self.evidence_warning.setText('Waiting for room-label evidence')
        if self.details.toPlainText():
            self.details.clear()
        self._displayed_record_signature = None
        if self._displayed_graph is not None:
            self._displayed_graph = None
            self._show_empty_graph('Waiting for a source graph snapshot')

    def _show_empty_graph(self, message: str):
        scene = self.snapshot_graph.scene()
        scene.clear()
        self.snapshot_graph.node_items = {}
        self.snapshot_graph.visible_graph = None
        self.snapshot_graph._selected_id = None
        text = scene.addSimpleText(message, QtGui.QFont('Sans Serif', 10))
        text.setBrush(QtGui.QColor('#93a3b5'))
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-24, -24, 24, 24))

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)


__all__ = ['RoomLabelDebugWidget']
