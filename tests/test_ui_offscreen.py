"""Offscreen UI rendering and external desktop-process lifecycle checks."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5 import QtWidgets  # noqa: E402

from neusymnav.visualization.publisher import DisplayPublisher, DisplaySources  # noqa: E402
from test_display_snapshot import (
    ALIAS, OID, VERIFIED, make_publisher, object_snapshot, verification_snapshot,
)  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["neusymnav-ui-test"])


def _tree_text(item):
    values = [item.text(0)]
    for index in range(item.childCount()):
        values.extend(_tree_text(item.child(index)))
    return values


def test_offscreen_dashboard_renders_pinned_rgb_map_hierarchy_and_alias(app):
    publisher, hierarchy, _metrics, _objects, _nav, _now = make_publisher(stale=True)
    from neusymnav.visualization.desktop import DashboardWindow

    window = DashboardWindow(publisher, clock_domain="clock", now_ns=lambda: 50_000_200)
    window.resize(1200, 720)
    window.show()
    app.processEvents()
    window.refresh()
    app.processEvents()

    assert window.map_view._nav.revision == hierarchy.map_revision
    assert window.map_view._stale is True
    assert window.rgb_view.pixmap() is not None and not window.rgb_view.pixmap().isNull()
    assert window.best_view.pixmap() is not None and not window.best_view.pixmap().isNull()
    assert "rgbd:2" in window.rgb_caption.text()
    assert "source age" in window.rgb_caption.text()
    assert "Best view · frame rgbd:0" in window.best_view_caption.text()
    assert "evidence evidence" in window.best_view_caption.text()
    labels = []
    for index in range(window.hierarchy.topLevelItemCount()):
        labels.extend(_tree_text(window.hierarchy.topLevelItem(index)))
    assert any("STALE" in value for value in labels)
    assert any("candidate" in value for value in labels)
    assert any("active" in value for value in labels)
    assert any("verified" in value for value in labels)
    assert "display publication age 50.0 ms" in window.telemetry.text()
    assert "profile cpu-fixture-v1" in window.telemetry.text()

    assert window.select_object(ALIAS) == OID
    window.object_id_input.setText(ALIAS)
    window._select_from_input()
    assert "Selected alias resolves" in window.object_details.text()
    assert "Lifecycle: active" in window.object_details.text()
    assert "Verification: verified" in window.object_details.text()
    assert "Verification source events: 2" in window.object_details.text()
    window.select_object(VERIFIED)
    assert "Lifecycle: active" in window.object_details.text()
    assert "Verification: unverified" in window.object_details.text()
    window.close()


def test_missing_rgb_best_view_or_map_is_explicitly_unavailable(app):
    publisher, _hierarchy, metrics, objects_value, _nav_value, _now = make_publisher(with_images=False)
    from neusymnav.visualization.desktop import DashboardWindow

    window = DashboardWindow(publisher, clock_domain="clock", now_ns=lambda: 250)
    window.show()
    app.processEvents()
    assert "RGB unavailable" in window.rgb_view.text()
    assert "Best view unavailable" in window.best_view.text()
    assert window.map_view._nav is not None
    window.close()

    missing_map = DisplayPublisher(clock_domain="clock", now_ns=lambda: 200)
    missing_map.publish(_hierarchy, {**metrics, "sources": DisplaySources(objects=objects_value)})
    window = DashboardWindow(missing_map, clock_domain="clock", now_ns=lambda: 250)
    window.show()
    app.processEvents()
    assert window.map_view._nav is None
    assert window.map_view._map_image is None
    assert "Map unavailable" in window.map_view.status_text
    window.close()


def test_offscreen_stale_verification_is_shown_as_unavailable(app):
    objects_value = object_snapshot()
    stale_verification = verification_snapshot(objects_value, stale_object_revision=True)
    publisher, _hierarchy, _metrics, _objects, _nav, _now = make_publisher(
        verification=stale_verification,
    )
    from neusymnav.visualization.desktop import DashboardWindow

    window = DashboardWindow(publisher, clock_domain="clock", now_ns=lambda: 250)
    window.show()
    app.processEvents()
    window.select_object(ALIAS)
    assert "Lifecycle: active" in window.object_details.text()
    assert "Verification: unavailable" in window.object_details.text()
    assert "verifier record object revision mismatch" in window.object_details.text()
    window.close()


def test_external_offscreen_desktop_process_starts_and_closes():
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    src = str(root / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(
        [sys.executable, "-m", "neusymnav.visualization.desktop", "--smoke-exit-ms", "40"],
        cwd=root, env=env, capture_output=True, text=True, timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert "NEUSYMNAV_UI_READY" in completed.stdout
