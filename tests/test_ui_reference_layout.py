"""Bounded offscreen checks for reference-style demo controls."""
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
import pytest
from PyQt5 import QtCore, QtWidgets
from test_display_snapshot import make_publisher


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["reference-ui"])


def test_demo_size_caps_to_screen_and_panels_can_focus(app):
    from neusymnav.visualization.desktop import DashboardWindow
    window = DashboardWindow()
    assert window.preferred_size == QtCore.QSize(2160, 1350)
    available = window.screen().availableGeometry()
    assert window.width() <= available.width()
    assert window.height() <= available.height()
    window.show()
    app.processEvents()
    assert window.workspace_split.orientation() == QtCore.Qt.Vertical
    window.focus_panel("SCENE GRAPH")
    assert window.graph_panel.isVisible()
    assert not window.sensor_panel.isVisible()
    window.focus_panel("All panels")
    assert window.sensor_panel.isVisible()
    window.close()


def test_observation_tab_keeps_live_rgb_separate_and_toggles(app):
    from neusymnav.visualization.desktop import DashboardWindow
    from neusymnav.visualization.publisher import DisplayInstance, DisplayObservation
    publisher, hierarchy, metrics, _, _, _ = make_publisher()
    source = replace(metrics["sources"].rgb, source=replace(metrics["sources"].rgb.source, frame_index=1), pixels=np.full((40, 60, 3), 25, dtype=np.uint8))
    mask = np.zeros((40, 60), dtype=bool)
    mask[12:30, 10:42] = True
    observation = DisplayObservation(source, (DisplayInstance("det-1", "chair", .9, mask),), 1, "complete", False)
    sources = replace(metrics["sources"], observation=observation)
    publisher.publish(hierarchy, {**metrics, "sources": sources})
    window = DashboardWindow(publisher, clock_domain="clock", now_ns=lambda: 100_000_150)
    window.show()
    app.processEvents()
    assert window.image_tabs.tabText(0) == "Detector observation"
    assert window.image_tabs.currentIndex() == 0
    assert "rgbd:1" in window.observation_caption.text()
    assert "rgbd:2" in window.rgb_caption.text()
    assert "historical" in window.observation_caption.text()
    assert "100.0 ms" in window.observation_caption.text()
    assert "1/1" in window.observation_caption.text()
    assert window.rgb_view.pixmap() is not None
    annotated = window.observation_view.pixmap().toImage()
    window.boxes_toggle.setChecked(False)
    window.masks_toggle.setChecked(False)
    app.processEvents()
    plain = window.observation_view.pixmap().toImage()
    assert annotated != plain
    assert plain.pixelColor(plain.width() // 2, plain.height() // 2).red() == 25
    window.image_tabs.setCurrentIndex(1)
    app.processEvents()
    assert window.rgb_view.isVisible()
    live = window.rgb_view.pixmap().toImage()
    assert live.pixelColor(live.width() // 2, live.height() // 2).red() == 120
    assert not window.observation_view.isVisible()
    window.close()
