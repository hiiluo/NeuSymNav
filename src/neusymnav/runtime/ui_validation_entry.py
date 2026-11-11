"""Artifact-only Qt wrapper for Hydra graph and room-stability UI evidence.

This file is deliberately outside the production package. It replaces only the
DashboardWindow class used by ui_transport.main(), observes accepted graph
projections after rendering, and never sends UI control commands.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# The assigned live validation uses Qt's real widget/render path with the
# offscreen platform. This is not evidence of a physical desktop display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtCore, QtWidgets
from neusymnav.visualization import desktop as desktop_module


BaseDashboardWindow = desktop_module.DashboardWindow
_NORMAL_SCREENSHOT_CAP = 12
_ERROR_EXIT_CODE = 86


def _process_qt_events():
    QtWidgets.QApplication.processEvents()


def _jsonable(value):
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_jsonable(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    raise TypeError(f"unsupported UI audit value: {type(value).__name__}")


def _membership_projection(graph):
    by_id = {node.node_id: node for node in graph.nodes}
    pairs = []
    memberships = []
    for node in graph.nodes:
        if node.layer_id != 3:
            continue
        parent = None
        if node.parent_id is not None:
            parent = by_id.get(node.parent_id)
            if parent is None:
                raise RuntimeError(f"place {node.native_id!r} has unresolved canonical parent {node.parent_id!r}")
        parent_native_id = None if parent is None else parent.native_id
        pairs.append([node.native_id, parent_native_id])

        room = None
        ancestor = parent
        seen = {node.node_id}
        while ancestor is not None:
            if ancestor.node_id in seen:
                raise RuntimeError(f"cycle in Hydra parent chain at native node {ancestor.native_id!r}")
            seen.add(ancestor.node_id)
            if ancestor.layer_id == 4:
                room = ancestor
                break
            if ancestor.parent_id is None:
                break
            ancestor = by_id.get(ancestor.parent_id)
            if ancestor is None:
                raise RuntimeError(f"unresolved canonical ancestor in parent chain for place {node.native_id!r}")
        memberships.append({
            "place_native_id": node.native_id,
            "direct_parent_native_id": parent_native_id,
            "direct_parent_layer_id": None if parent is None else parent.layer_id,
            "room_native_id": None if room is None else room.native_id,
        })

    pairs.sort()
    memberships.sort(key=lambda row: row["place_native_id"])
    canonical = json.dumps(pairs, separators=(",", ":"), ensure_ascii=True).encode()
    return pairs, memberships, hashlib.sha256(canonical).hexdigest()


def _meaningful_decision(decision):
    if not isinstance(decision, Mapping):
        return _jsonable(decision)
    fields = (
        "action", "enabled", "novel_observation", "pending_count",
        "raw_seed_count", "selected_seed_count",
    )
    return {key: _jsonable(decision[key]) for key in fields if key in decision}


def make_capture_dashboard_class(output_dir):
    """Return a DashboardWindow subclass that records post-render graph state."""
    output_dir = Path(output_dir)

    class CaptureDashboardWindow(BaseDashboardWindow):
        capture_output_dir = output_dir
        latest_instance = None

        def __init__(self, *args, **kwargs):
            self.capture_output_dir = Path(type(self).capture_output_dir)
            self.capture_output_dir.mkdir(parents=True, exist_ok=True)
            self._capture_seen_revisions = set()
            self._capture_observed_revisions = []
            self._capture_duplicate_publications = []
            self._capture_last_screenshot_signature = None
            self._capture_normal_screenshot_count = 0
            self._capture_screenshots = []
            self._capture_failed = False
            type(self).latest_instance = self
            super().__init__(*args, **kwargs)

        def _capture_error(self, stage, exc, graph_revision=None):
            self._capture_failed = True
            detail = {
                "schema_version": 1,
                "stage": stage,
                "graph_revision": graph_revision,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "timestamp_monotonic_ns": time.monotonic_ns(),
            }
            error_path = self.capture_output_dir / "capture-error.json"
            try:
                error_path.write_text(json.dumps(detail, indent=2, ensure_ascii=True) + "\n")
            except Exception:
                with (self.capture_output_dir / "capture-error-traceback.txt").open("a") as stream:
                    stream.write(detail["traceback"] + "\n")
            app = QtWidgets.QApplication.instance()
            if app is not None:
                app.exit(_ERROR_EXIT_CODE)

        def _append_jsonl(self, filename, record):
            path = self.capture_output_dir / filename
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
                stream.write("\n")
                stream.flush()

        def _record_graph_after_render(self, envelope):
            graph = envelope.sources.hydra_graph
            if graph is None:
                return
            revision = graph.graph_revision
            if revision in self._capture_seen_revisions:
                self._capture_duplicate_publications.append({
                    "graph_revision": revision,
                    "publication_sequence": envelope.publication_sequence,
                })
                return

            try:
                if self.graph_view.visible_graph is None:
                    raise RuntimeError("rendered Hydra graph has no SceneGraphWidget.visible_graph")
                pairs, memberships, fingerprint = _membership_projection(graph)
                native_metadata = _jsonable(graph.native_metadata)
                room_stability = native_metadata.get("room_stability") if isinstance(native_metadata, dict) else None
                last_decision = (room_stability.get("last_decision")
                                 if isinstance(room_stability, dict) else None)
                by_id = {node.node_id: node for node in graph.nodes}
                actual_ids = sorted(str(node_id) for node_id in self.graph_view.node_items)
                missing_display_ids = [node_id for node_id in actual_ids if node_id not in by_id]
                if missing_display_ids:
                    raise RuntimeError(f"graph widget contains IDs absent from canonical graph: {missing_display_ids[:8]}")
                actual_layers = sorted({by_id[node_id].layer_id for node_id in actual_ids})
                counts = self.graph_view.visible_graph.counts
                room_count = sum(node.layer_id == 4 for node in graph.nodes)
                screenshot_reason = None
                signature = (room_count, json.dumps(_meaningful_decision(last_decision),
                                                    separators=(",", ":"), sort_keys=True))
                if graph.nodes:
                    if self._capture_last_screenshot_signature is None:
                        screenshot_reason = "first_nonempty_graph"
                    elif signature[0] != self._capture_last_screenshot_signature[0]:
                        screenshot_reason = "room_count_changed"
                    elif signature[1] != self._capture_last_screenshot_signature[1]:
                        screenshot_reason = "decision_changed"
                self._capture_last_screenshot_signature = signature

                previous = self._capture_observed_revisions[-1] if self._capture_observed_revisions else None
                row = {
                    "schema_version": 1,
                    "capture_status": "rendered",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                    "timestamp_unix_ns": time.time_ns(),
                    "timestamp_monotonic_ns": time.monotonic_ns(),
                    "publication_sequence": envelope.publication_sequence,
                    "graph_revision": revision,
                    "previous_observed_graph_revision": previous,
                    "revision_gap_from_previous_rendered": None if previous is None else max(0, revision - previous - 1),
                    "last_source": _jsonable(graph.last_source),
                    "input_prefix_sha256": graph.input_prefix_sha256,
                    "graph_status": graph.status,
                    "room_count": room_count,
                    "native_metadata": native_metadata,
                    "room_stability": room_stability,
                    "last_decision": _jsonable(last_decision),
                    "place_membership_pairs": pairs,
                    "native_place_room_memberships": memberships,
                    "place_membership_sha256": fingerprint,
                    "semantic_graph_fingerprint_sha256": fingerprint,
                    "visible_layer_policy": sorted(self.graph_visibility.visible_layers),
                    "actual_displayed_layer_ids": actual_layers,
                    "actual_displayed_node_ids": actual_ids,
                    "actual_displayed_edge_count": len(self.graph_view.visible_graph.edges),
                    "widget_raw_node_counts_by_layer": {str(k): int(v) for k, v in counts.raw_by_layer.items()},
                    "widget_shown_node_counts_by_layer": {str(k): int(v) for k, v in counts.shown_by_layer.items()},
                    "widget_filtered_node_count": counts.filtered_count,
                    "widget_budget_hidden_node_count": counts.budget_hidden_count,
                    "screenshot_requested_reason": screenshot_reason,
                    "screenshot_cap": _NORMAL_SCREENSHOT_CAP,
                    "control_messages_sent_by_harness": 0,
                }
                self._append_jsonl("ui-render-audit.jsonl", row)
                self._capture_seen_revisions.add(revision)
                self._capture_observed_revisions.append(revision)
                if screenshot_reason is not None:
                    if self._capture_normal_screenshot_count < _NORMAL_SCREENSHOT_CAP:
                        self._capture_normal_screenshot_count += 1
                        self._save_screenshot(
                            screenshot_kind="change",
                            requested_revision=revision,
                            requested_sequence=envelope.publication_sequence,
                            reason=screenshot_reason,
                        )
                    else:
                        self._append_jsonl("screenshot-events.jsonl", {
                            "schema_version": 1,
                            "event": "screenshot_suppressed_cap",
                            "requested_graph_revision": revision,
                            "publication_sequence": envelope.publication_sequence,
                            "reason": screenshot_reason,
                            "normal_screenshot_cap": _NORMAL_SCREENSHOT_CAP,
                        })
            except Exception as exc:
                self._capture_error("post_render_graph_audit", exc, revision)
                raise

        def _render_envelope(self, envelope):
            # Capture only after the stock window has updated every panel and
            # SceneGraphWidget has built its view-filtered node/edge set.
            super()._render_envelope(envelope)
            self._record_graph_after_render(envelope)

        def _save_screenshot(self, *, screenshot_kind, requested_revision, requested_sequence, reason=None):
            try:
                old_size = self.size()
                old_state = self.windowState()
                old_focus = self.focus_selector.currentText()
                old_tab = self.scene_tabs.currentWidget()
                was_visible = self.isVisible()
                timer = self._refresh_timer
                timer_was_active = timer.isActive()
                timer_interval_ms = timer.interval()
                if timer_was_active:
                    timer.stop()
                try:
                    if not was_visible:
                        self.show()
                    self.showNormal()
                    self.resize(1600, 1000)
                    self.focus_selector.setCurrentText("SCENE GRAPH")
                    self.scene_tabs.setCurrentWidget(self.graph_view)
                    _process_qt_events()
                    before_grab = self._screenshot_provenance()
                    rendered = self.grab()
                    after_grab = self._screenshot_provenance()
                    if after_grab != before_grab:
                        raise RuntimeError("UI envelope or graph provenance changed during QWidget.grab")
                    serial = len(self._capture_screenshots) + 1
                    name = ("final-ui-view.png" if screenshot_kind == "final" else
                            f"ui-view-{serial:02d}-r{after_grab['graph_revision']}-p{after_grab['publication_sequence']}.png")
                    path = self.capture_output_dir / name
                    if rendered.isNull() or not rendered.save(str(path), "PNG"):
                        raise OSError(f"QWidget.grab().save failed for {path}")
                finally:
                    if old_tab is not None:
                        self.scene_tabs.setCurrentWidget(old_tab)
                    self.focus_selector.setCurrentText(old_focus)
                    self.resize(old_size)
                    if old_state & QtCore.Qt.WindowMaximized:
                        self.showMaximized()
                    elif old_state & QtCore.Qt.WindowMinimized:
                        self.showMinimized()
                    else:
                        self.showNormal()
                    if not was_visible:
                        self.hide()
                    if timer_was_active:
                        timer.start(timer_interval_ms)

                entry = {
                    "schema_version": 1,
                    "screenshot_kind": screenshot_kind,
                    "file": name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "width": rendered.width(),
                    "height": rendered.height(),
                    "requested_graph_revision": requested_revision,
                    "requested_publication_sequence": requested_sequence,
                    "actual_graph_revision": after_grab["graph_revision"],
                    "actual_publication_sequence": after_grab["publication_sequence"],
                    "actual_last_source": after_grab["last_source"],
                    "actual_input_prefix_sha256": after_grab["input_prefix_sha256"],
                    "actual_place_membership_sha256": after_grab["place_membership_sha256"],
                    "actual_displayed_node_ids": after_grab["displayed_node_ids"],
                    "actual_displayed_layer_ids": after_grab["displayed_layer_ids"],
                    "request_matches_actual_graph": (
                        requested_revision == after_grab["graph_revision"] and
                        requested_sequence == after_grab["publication_sequence"]),
                    "reason": reason,
                    "qt_platform": QtWidgets.QApplication.platformName(),
                    "qt_platform_requested": os.environ.get("QT_QPA_PLATFORM"),
                    "physical_desktop_proof": False,
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                    "timestamp_monotonic_ns": time.monotonic_ns(),
                }
                self._capture_screenshots.append(entry)
                self._append_jsonl("screenshot-events.jsonl", entry)
            except Exception as exc:
                self._capture_error("screenshot", exc, requested_revision)
                raise

        def _screenshot_provenance(self):
            envelope = self._envelope
            if envelope is None:
                return {
                    "publication_sequence": None,
                    "graph_revision": None,
                    "last_source": None,
                    "input_prefix_sha256": None,
                    "place_membership_sha256": None,
                    "displayed_node_ids": [],
                    "displayed_layer_ids": [],
                }
            graph = envelope.sources.hydra_graph
            if graph is None:
                return {
                    "publication_sequence": envelope.publication_sequence,
                    "graph_revision": None,
                    "last_source": None,
                    "input_prefix_sha256": None,
                    "place_membership_sha256": None,
                    "displayed_node_ids": [],
                    "displayed_layer_ids": [],
                }
            if getattr(self.graph_view, "_envelope", None) is not envelope:
                raise RuntimeError("SceneGraphWidget is not rendered from the current display envelope")
            _, _, fingerprint = _membership_projection(graph)
            by_id = {node.node_id: node for node in graph.nodes}
            displayed_ids = sorted(str(node_id) for node_id in self.graph_view.node_items)
            if any(node_id not in by_id for node_id in displayed_ids):
                raise RuntimeError("SceneGraphWidget contains a node absent from the current canonical graph")
            return {
                "publication_sequence": envelope.publication_sequence,
                "graph_revision": graph.graph_revision,
                "last_source": _jsonable(graph.last_source),
                "input_prefix_sha256": graph.input_prefix_sha256,
                "place_membership_sha256": fingerprint,
                "displayed_node_ids": displayed_ids,
                "displayed_layer_ids": sorted({by_id[node_id].layer_id for node_id in displayed_ids}),
            }

        def capture_final_screenshot(self):
            if self._capture_failed:
                return
            graph = None if self._envelope is None else self._envelope.sources.hydra_graph
            revision = None if graph is None else graph.graph_revision
            sequence = None if self._envelope is None else self._envelope.publication_sequence
            self._save_screenshot(screenshot_kind="final", requested_revision=revision,
                                  requested_sequence=sequence, reason="final_ui_state")
            revisions = sorted(self._capture_observed_revisions)
            gaps = []
            for left, right in zip(revisions, revisions[1:]):
                if right > left + 1:
                    gaps.append({"after": left, "before": right, "missing_integer_revisions": list(range(left + 1, right))})
            summary = {
                "schema_version": 1,
                "capture_status": "complete",
                "qt_platform": QtWidgets.QApplication.platformName(),
                "qt_platform_requested": os.environ.get("QT_QPA_PLATFORM"),
                "physical_desktop_proof": False,
                "observed_graph_revisions": revisions,
                "observed_revision_count": len(revisions),
                "numeric_revision_gaps": gaps,
                "numeric_revision_coverage_is_contiguous": len(gaps) == 0,
                "duplicate_graph_publications": self._capture_duplicate_publications,
                "screenshot_normal_count": self._capture_normal_screenshot_count,
                "screenshot_normal_cap": _NORMAL_SCREENSHOT_CAP,
                "screenshots": self._capture_screenshots,
                "final_graph_revision": revision,
                "final_publication_sequence": sequence,
                "control_messages_sent_by_harness": 0,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            }
            (self.capture_output_dir / "ui-render-summary.json").write_text(
                json.dumps(summary, indent=2, ensure_ascii=True, allow_nan=False) + "\n")

    return CaptureDashboardWindow


def main():
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", required=True)
    args, _ = parser.parse_known_args(sys.argv[1:])
    capture_dir = Path(args.root) / "ui-harness"
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_window = make_capture_dashboard_class(capture_dir)
    desktop_module.DashboardWindow = capture_window

    from neusymnav.runtime import ui_transport

    exit_code = 1
    try:
        exit_code = ui_transport.main()
        instance = capture_window.latest_instance
        if instance is not None:
            instance.capture_final_screenshot()
        return int(exit_code)
    except Exception as exc:
        instance = capture_window.latest_instance
        if instance is not None:
            instance._capture_error("wrapper_main", exc,
                                    None if instance._envelope is None or instance._envelope.sources.hydra_graph is None
                                    else instance._envelope.sources.hydra_graph.graph_revision)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
