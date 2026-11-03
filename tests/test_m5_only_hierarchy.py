"""Regression coverage for the Rebuild M1–M5 room source of truth."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt5 import QtWidgets

from neusymnav.hierarchy import HierarchyComposer
from neusymnav.visualization.desktop import DashboardWindow
from test_membership import OID, objects, regions
from test_regions import nav
from test_room_hierarchy import _rebuild_publication


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_rebuild_hierarchy_uses_m5_only_for_rooms_and_object_membership():
    hierarchy = HierarchyComposer().compose(
        objects(), nav(), regions(), latest_nav_revision=1, now_ns=200,
        clock_domain="clock", room_pipeline=_rebuild_publication(),
    )

    m5_nodes = [node for node in hierarchy.nodes.values() if node.kind == "source_region"]
    assert len(m5_nodes) == 1
    assert not any(node.kind == "region" for node in hierarchy.nodes.values())
    assert not any("stable_room_" in key or key == "room_debug"
                   for node in hierarchy.nodes.values() for key in node.attributes)
    assert hierarchy.nodes[OID].attributes["membership_status"] == "assigned"
    assert hierarchy.nodes[OID].attributes["rebuild_region_membership_id"] == "m5-raw-1"
    assert not any(edge.kind == "in_region" for edge in hierarchy.edges)
    assert any(edge.kind == "in_source_region" and edge.source_id == OID
               and edge.status == "assigned" for edge in hierarchy.edges)


def test_stale_m5_never_assigns_a_room_or_object_membership():
    hierarchy = HierarchyComposer().compose(
        objects(), nav(), regions(), latest_nav_revision=1, now_ns=200,
        clock_domain="clock", room_pipeline=_rebuild_publication(latest_revision=2, stale=True),
    )

    assert not any(node.kind == "region" for node in hierarchy.nodes.values())
    assert all(node.attributes["stale"] for node in hierarchy.nodes.values()
               if node.kind == "source_region")
    assert hierarchy.nodes[OID].attributes["membership_status"] == "unavailable"
    assert not any(edge.kind in {"in_region", "in_source_region"} for edge in hierarchy.edges)


def test_wrong_episode_m5_publication_does_not_fall_back_to_generic_regions():
    publication = _rebuild_publication(episode="another-episode")
    hierarchy = HierarchyComposer().compose(
        objects(), nav(), regions(), latest_nav_revision=1, now_ns=200,
        clock_domain="clock", room_pipeline=publication,
    )

    assert not any(node.kind in {"region", "source_region"}
                   for node in hierarchy.nodes.values())
    assert hierarchy.nodes[OID].attributes["membership_status"] == "unavailable"
    assert hierarchy.statuses["rebuild_regions"] == "unavailable"
    assert not any(edge.kind in {"in_region", "in_source_region"}
                   for edge in hierarchy.edges)


def test_dashboard_has_no_roomowner_debug_or_stable_room_overlay(app):
    window = DashboardWindow(lambda: None, clock_domain="clock", now_ns=lambda: 200)
    try:
        assert not hasattr(window, "room_debug_list")
        assert not hasattr(window, "portal_button")
        assert not hasattr(window.spatial_view, "stable_polygons")
        assert "Tentative" not in window.map_legend.text()
        assert "Confirmed" not in window.map_legend.text()
        assert "Disputed" not in window.map_legend.text()
        assert "Portal candidate" not in window.map_legend.text()
        assert all(window.scene_tabs.tabText(index) != "Room stability"
                   for index in range(window.scene_tabs.count()))
        window._map_tab_changed(0)
        assert "Tentative" not in window.map_legend.text()
        assert "Portal candidate" not in window.map_legend.text()
        window._map_tab_changed(1)
        assert "Source M5 region" in window.map_legend.text()
    finally:
        window.close()
