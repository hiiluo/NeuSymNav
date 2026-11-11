"""Shared Hydra graph visibility must remain a view-only projection."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
from PyQt5 import QtWidgets

from test_display_snapshot import make_publisher
from neusymnav.backends.hydra.graph_adapter import HydraGraphAdapter
from neusymnav.visualization.graph_visibility import (
    GraphVisibility,
    select_visible_nodes,
)
from neusymnav.visualization.desktop import DashboardWindow
from neusymnav.visualization.scene_graph import SceneGraphWidget
from neusymnav.visualization.spatial_scene import SpatialSceneWidget


def graph_with_places_first(place_count=205, episode_id='episode'):
    nodes = [
        {'native_id': f'place-{index:03}', 'layer_id': 3, 'name': 'place',
         'position': [float(index), 0.0, 0.0],
         'parent_native_id': 'room-a' if index == 0 else None}
        for index in range(place_count)
    ]
    nodes.extend([
        {'native_id': 'chair-a', 'layer_id': 2, 'name': 'chair',
         'position': [1.0, 2.0, 0.0], 'parent_native_id': 'place-000'},
        {'native_id': 'room-a', 'layer_id': 4, 'name': 'room',
         'position': [0.0, 0.0, 0.0], 'parent_native_id': None},
        {'native_id': 'building-a', 'layer_id': 5, 'name': 'building',
         'position': [0.0, 0.0, 0.0], 'parent_native_id': None},
    ])
    return HydraGraphAdapter.project({
        'schema_version': 1,
        'graph_revision': 8,
        'input_prefix_sha256': 'b' * 64,
        'layer_counts': {'2': 1, '3': place_count, '4': 1, '5': 1},
        'nodes': nodes,
        'edges': [
            {'source_native_id': 'chair-a', 'target_native_id': 'place-000', 'kind': 'belongs'},
            {'source_native_id': 'place-000', 'target_native_id': 'room-a', 'kind': 'belongs'},
        ],
    }, episode_id=episode_id, run_id='run', stale=False, replay_required=False,
       failure_reason=None, last_source=None)


def test_rooms_objects_preset_hides_places_but_preserves_objects_and_rooms():
    graph = graph_with_places_first()
    policy = GraphVisibility.for_preset('rooms_objects')

    visible = select_visible_nodes(graph, policy)

    assert {node.layer_id for node in visible.nodes} == {2, 4}
    assert {node.native_id for node in visible.nodes} == {'chair-a', 'room-a'}
    assert {layer: count for layer, count in visible.counts.raw_by_layer.items() if count} == {
        2: 1, 3: 205, 4: 1, 5: 1
    }
    assert visible.counts.filtered_count == 206
    assert visible.counts.budget_hidden_count == 0
    assert graph.node_counts == {'2': 1, '3': 205, '4': 1, '5': 1}


def test_places_budget_does_not_hide_room_or_object_and_edges_are_view_filtered():
    graph = graph_with_places_first()
    policy = GraphVisibility.for_preset('all_debug')
    visible = select_visible_nodes(graph, policy)

    assert len([node for node in visible.nodes if node.layer_id == 3]) == 200
    assert {node.native_id for node in visible.nodes if node.layer_id in {2, 4, 5}} == {
        'chair-a', 'room-a', 'building-a'
    }
    visible_ids = {node.node_id for node in visible.nodes}
    assert all(edge.source in visible_ids and edge.target in visible_ids for edge in visible.edges)
    assert visible.counts.budget_hidden_count == 5
    assert visible.counts.filtered_count == 5
    assert visible.counts.shown_count == 203
    assert len(graph.nodes) == 208


def test_selected_place_is_retained_inside_place_budget():
    graph = graph_with_places_first(place_count=205)
    selected = next(node.node_id for node in graph.nodes if node.native_id == 'place-204')
    visible = select_visible_nodes(graph, GraphVisibility.for_preset('all_debug'), selected_id=selected)

    assert selected in {node.node_id for node in visible.nodes}
    assert visible.counts.budget_hidden_count == 5


def test_filter_and_repaint_are_shared_by_2d_and_3d_without_losing_cloud_or_view():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, *_ = make_publisher()
    envelope = publisher.read_latest()
    graph = graph_with_places_first(place_count=3, episode_id=envelope.hierarchy.episode_id)
    envelope = replace(envelope, sources=replace(envelope.sources, hydra_graph=graph))
    cloud = SimpleNamespace(
        episode_id=envelope.hierarchy.episode_id,
        clock_domain=envelope.clock_domain,
        revision=1,
        points=np.array([[0., 0., 1.]], dtype=np.float32),
        colors=np.array([[1, 2, 3]], dtype=np.uint8),
    )
    spatial = SpatialSceneWidget()
    graph_view = SceneGraphWidget()
    spatial.set_envelope(envelope)
    spatial.set_cloud(cloud)
    spatial.yaw = .9
    spatial.zoom = 2.
    policy = GraphVisibility.for_preset('rooms_objects')

    spatial.set_graph_visibility(policy)
    graph_view.set_envelope(envelope)
    graph_view.set_graph_visibility(policy)

    assert {item['row'].kind for item in spatial.nodes.values()} == {'object', 'room'}
    assert {item.data(1) for item in graph_view.node_items.values()} == {2, 4}
    assert len(spatial.visible_cloud()[0]) == 1
    assert spatial.yaw == .9 and spatial.zoom == 2.
    assert graph_view.hidden_count == 4
    assert len(graph.nodes) == 6
    spatial.close(); graph_view.close(); app.processEvents()


def test_hidden_nodes_cannot_be_picked_and_derived_membership_is_typed():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, *_ = make_publisher()
    envelope = publisher.read_latest()
    graph = graph_with_places_first(place_count=2, episode_id=envelope.hierarchy.episode_id)
    envelope = replace(envelope, sources=replace(envelope.sources, hydra_graph=graph))
    policy = replace(GraphVisibility.for_preset('rooms_objects'), show_derived_membership=True)
    view = SceneGraphWidget()
    view.set_envelope(envelope)
    view.set_graph_visibility(policy)

    assert 'hydra:run:3:place-000' not in view.node_items
    assert 'hydra:run:2:chair-a' in view.node_items
    assert any(edge.kind == 'derived_room_membership' for edge in view.visible_graph.edges)
    assert all(item.data(0) != 'hydra:run:3:place-000'
               for item in view.scene().selectedItems())
    view.close(); app.processEvents()


def test_dashboard_preset_and_individual_checks_apply_to_both_graph_views():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, *_ = make_publisher()
    envelope = publisher.read_latest()
    graph = graph_with_places_first(place_count=3, episode_id=envelope.hierarchy.episode_id)
    envelope = replace(envelope, sources=replace(envelope.sources, hydra_graph=graph))
    window = DashboardWindow(clock_domain=envelope.clock_domain)
    window._render_envelope(envelope)

    assert window.graph_visibility.preset == 'rooms_objects'
    assert {node.layer_id for node in window.graph_view.visible_graph.nodes} == {2, 4}
    assert {item['row'].kind for item in window.spatial_view.nodes.values()} == {'object', 'room'}

    window.hydra_layer_filter.setCurrentIndex(2)
    assert {node.layer_id for node in window.graph_view.visible_graph.nodes} == {2, 3, 4, 5}
    assert {item['row'].kind for item in window.spatial_view.nodes.values()} == {
        'object', 'place', 'room', 'building'
    }

    window.hydra_layer_actions[3].setChecked(False)
    assert window.graph_visibility.preset == 'custom'
    assert 3 not in window.graph_view.graph_visibility.visible_layers
    assert 3 not in window.spatial_view.graph_visibility.visible_layers
    window.close(); app.processEvents()
