"""Headless regression coverage for optional stable-room debug presentation."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import replace

import numpy as np
import pytest
from PyQt5 import QtWidgets

from neusymnav.visualization.desktop import DashboardWindow, MapWidget
from neusymnav.visualization.hierarchy_view import room_debug_items
from neusymnav.visualization.spatial_scene import SpatialSceneWidget
from test_display_snapshot import make_publisher


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def debug_envelope():
    publisher, hierarchy, metrics, *_ = make_publisher()
    floor = hierarchy.nodes["floor:f"]
    debug = {
        "episode_id": "e",
        "source_map_revision": 1,
        "stale": False,
        "rooms": [
            {"room_id": "stable-confirmed", "status": "confirmed", "polygons": [
                [[0, 0], [1, 0], [1, 1], [0, 1]], [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]],
             "region_ids": ["r1"], "reason": "overlap remained above threshold", "support_count": 4,
             "predecessors": ["stable-old"]},
            {"room_id": "stable-tentative", "status": "tentative", "polygons": [[[1, 0], [2, 0], [2, 1], [1, 1]]],
             "region_ids": ["r2"], "reason": "insufficient repeated observations", "support_count": 1,
             "predecessors": []},
            {"room_id": "stable-disputed", "status": "disputed", "polygons": [[[2, 0], [3, 0], [3, 1], [2, 1]]],
             "region_ids": ["r3"], "reason": "competing predecessor match", "support_count": 3,
             "predecessors": ["stable-left", "stable-right"]},
        ],
        "portals": [{"portal_id": "portal-candidate-1", "endpoints": [[0.9, 0.5], [1.1, 0.5]],
                     "status": "tentative", "reason": "shared boundary candidate"}],
        "events": [],
    }
    nodes = dict(hierarchy.nodes)
    nodes[floor.node_id] = replace(floor, attributes={**floor.attributes, "floor_z_m": 1.25, "room_debug": debug})
    for region_id, stable_id, status, reason in (
        ("r1", "stable-confirmed", "confirmed", "overlap remained above threshold"),
        ("r2", "stable-tentative", "tentative", "insufficient repeated observations"),
        ("r3", "stable-disputed", "disputed", "competing predecessor match"),
    ):
        if region_id in nodes:
            region = nodes[region_id]
            nodes[region_id] = replace(region, attributes={**region.attributes,
                "stable_room_id": stable_id, "stable_room_status": status, "stable_room_reason": reason})
    envelope = replace(publisher.read_latest(), hierarchy=replace(hierarchy, nodes=nodes))
    return envelope


def test_debug_projection_preserves_ids_support_lineage_and_candidate_caveat():
    items = room_debug_items(debug_envelope())
    rooms = {item.item_id: item for item in items if item.kind == "room"}
    assert set(rooms) == {"stable-confirmed", "stable-tentative", "stable-disputed"}
    assert "Support: 4" in rooms["stable-confirmed"].detail
    assert "stable-old" in rooms["stable-confirmed"].detail
    assert "competing predecessor match" in rooms["stable-disputed"].detail
    portal = next(item for item in items if item.kind == "portal")
    assert "no door detection" in portal.detail
    assert np.array_equal(np.asarray(portal.geometry), [[0.9, 0.5], [1.1, 0.5]])


def test_map_only_projection_without_floor_needs_no_room_metadata():
    from types import SimpleNamespace
    envelope = SimpleNamespace(hierarchy=SimpleNamespace(nodes={}, map_revision=1))
    assert room_debug_items(envelope) == ()


def test_rebuild_backend_is_visible_and_portals_stay_opt_in(app):
    envelope = debug_envelope()
    envelope = replace(envelope, metrics=replace(envelope.metrics, actual_profile="baseline:rooms-rebuild_m4_m5"))
    window = DashboardWindow(lambda: envelope, clock_domain="clock", now_ns=lambda: 200)
    assert "Rebuild M4/M5" in window.subtitle.text()
    assert not window.portal_button.isChecked()
    assert window.room_debug_list.count() == 3
    window.close()


def test_dashboard_renders_status_layers_and_selected_debug_detail(app):
    envelope = debug_envelope()
    window = DashboardWindow(lambda: envelope, clock_domain="clock", now_ns=lambda: 200)
    window.resize(1100, 760)
    window.show()
    app.processEvents()
    assert {status for _, status, _ in window.map_view._stable_regions} == {"confirmed", "tentative", "disputed"}
    assert len(window.map_view._stable_regions) == 4
    assert len(window.map_view._regions) >= 2  # latest DuDe outlines remain a separate layer
    assert len(window.map_view._debug_portals) == 1
    assert not window.portal_button.isChecked()
    assert not window.map_view.show_portal_candidates
    assert not window.spatial_view.show_portal_candidates
    assert window.room_debug_list.count() == 3
    window.portal_button.setChecked(True)
    assert window.map_view.show_portal_candidates and window.spatial_view.show_portal_candidates
    assert window.room_debug_list.count() == 4
    assert "portal-candidate-1" in window.room_debug_list.item(3).text()
    # Select the disputed room and ensure the selected stable ID, reason, support and lineage are readable.
    disputed_index = next(i for i in range(window.room_debug_list.count())
                          if "stable-disputed" in window.room_debug_list.item(i).text())
    window.room_debug_list.setCurrentRow(disputed_index)
    app.processEvents()
    detail = window.room_debug_details.text()
    assert "Stable ID: stable-disputed" in detail
    assert "Status: disputed" in detail
    assert "Support: 3" in detail and "stable-left, stable-right" in detail
    assert window.map_view._selected_debug_id == "stable-disputed"
    scene = SpatialSceneWidget()
    scene.set_envelope(envelope)
    assert {status for _, status, _ in scene.stable_polygons} == {"confirmed", "tentative", "disputed"}
    assert len(scene.stable_polygons) == 4 and len(scene.portal_candidates) == 1
    assert all(np.allclose(polygon[:, 2], 1.265) for _, _, polygon in scene.stable_polygons)
    assert all(np.allclose(endpoints[:, 2], 1.265) for _, _, endpoints in scene.portal_candidates)
    latest_dude_max_x = max(float(np.max(region.attributes["polygon"][:, 0]))
                            for region in envelope.hierarchy.nodes.values() if region.kind == "region")
    disputed_bounds = np.vstack([polygon[:, :2] for room_id, _status, polygon in scene.stable_polygons
                                 if room_id == "stable-disputed"])
    assert latest_dude_max_x == 2.0 and np.max(disputed_bounds[:, 0]) == 3.0
    scene.resize(640, 420)
    scene.show()
    app.processEvents()
    scene_image = scene.grab().toImage()
    assert scene_image.width() > 200 and scene_image.height() > 150
    scene.close()
    map_widget = MapWidget()
    map_widget.set_snapshot(envelope.sources.live_nav or envelope.sources.nav, envelope)
    map_widget._now_ns = 200
    map_widget._clock_domain = "clock"
    map_widget.resize(640, 420)
    map_widget.show()
    app.processEvents()
    image = map_widget.grab().toImage()
    assert image.width() > 200 and image.height() > 150
    map_widget.close()
    window.close()


def test_older_publication_without_optional_room_debug_is_still_supported(app):
    publisher, hierarchy, *_ = make_publisher()
    nodes = {}
    for node_id, node in hierarchy.nodes.items():
        attrs = dict(node.attributes)
        if node.kind == "floor":
            attrs.pop("room_debug", None)
        if node.kind == "region":
            for key in ("stable_room_id", "stable_room_status", "stable_room_reason", "stable_room_support_count"):
                attrs.pop(key, None)
        nodes[node_id] = replace(node, attributes=attrs)
    envelope = replace(publisher.read_latest(), hierarchy=replace(hierarchy, nodes=nodes))
    window = DashboardWindow(lambda: envelope, clock_domain="clock", now_ns=lambda: 200)
    assert window.room_debug_list.count() == 1
    assert "debug unavailable" in window.room_debug_list.item(0).text().lower()
    assert "No stable room" in window.room_debug_details.text()
    window.close()


def test_mismatched_revision_and_invalid_nonfinite_or_outside_geometry_fail_closed():
    envelope = debug_envelope()
    floor = next(node for node in envelope.hierarchy.nodes.values() if node.kind == "floor")
    debug = dict(floor.attributes["room_debug"])
    debug["source_map_revision"] = envelope.hierarchy.map_revision + 1
    mismatched = replace(envelope, hierarchy=replace(envelope.hierarchy, nodes={
        **envelope.hierarchy.nodes,
        floor.node_id: replace(floor, attributes={**floor.attributes, "room_debug": debug}),
    }))
    assert room_debug_items(mismatched) == ()

    debug["source_map_revision"] = envelope.hierarchy.map_revision
    debug["rooms"] = [
        {"room_id": "nan-room", "status": "confirmed", "polygons": [np.array([[0, 0], [float("nan"), 0], [1, 1]])]},
        {"room_id": "outside-room", "status": "confirmed", "polygons": [np.array([[1000, 1000], [1001, 1000], [1001, 1001]])]},
    ]
    debug["portals"] = [{"portal_id": "outside-portal", "endpoints": np.array([[1000, 1000], [1001, 1001]])}]
    invalid = replace(envelope, hierarchy=replace(envelope.hierarchy, nodes={
        **envelope.hierarchy.nodes,
        floor.node_id: replace(floor, attributes={**floor.attributes, "room_debug": debug}),
    }))
    items = room_debug_items(invalid)
    assert len(items) == 3
    assert all(item.geometry is None for item in items)
    assert all(not item.geometries for item in items)
