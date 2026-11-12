import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from dataclasses import replace
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from test_display_snapshot import make_publisher
from neusymnav.backends.hydra.graph_adapter import HydraGraphAdapter
from neusymnav.visualization.spatial_scene import SpatialSceneWidget
from neusymnav.visualization.graph_visibility import GraphVisibility
from neusymnav.visualization.desktop import DashboardWindow

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def projection():
    return HydraGraphAdapter.project({
        'schema_version': 1,
        'graph_revision': 7,
        'input_prefix_sha256': 'a' * 64,
        'layer_counts': {'2': 1, '3': 1},
        'nodes': [
            {'native_id': 'object-1', 'layer_id': 2, 'name': 'chair',
             'position': [1.25, -2.5, 0.75], 'parent_native_id': None},
            {'native_id': 'place-1', 'layer_id': 3, 'name': 'place',
             'position': [-1.0, 3.0, 1.5], 'parent_native_id': None},
        ],
        'edges': [{'source_native_id': 'object-1', 'target_native_id': 'place-1',
                   'kind': 'native-membership'}],
    }, episode_id='e', run_id='run', stale=False, replay_required=False,
       failure_reason=None, last_source=None)


def test_hydra_positions_and_edges_drive_3d_scene_when_legacy_hierarchy_is_empty():
    app = APP
    envelope = make_publisher()[0].read_latest()
    hierarchy = replace(envelope.hierarchy, nodes={}, edges=())
    sources = replace(envelope.sources, hydra_graph=projection())
    envelope = replace(envelope, hierarchy=hierarchy, sources=sources)

    view = SpatialSceneWidget()
    view.set_envelope(envelope)
    view.set_graph_visibility(GraphVisibility.for_preset('all_debug'))

    object_node = next(node for node in projection().nodes if node.native_id == 'object-1')
    assert np.array_equal(view.nodes[object_node.node_id]['position'], [1.25, -2.5, 0.75])
    assert view.edges == ((object_node.node_id,
                           next(node.node_id for node in projection().nodes if node.native_id == 'place-1'),
                           'native-membership'),)
    assert view.nodes[object_node.node_id]['row'].kind == 'object'
    view.close()
    app.processEvents()


def test_hydra_native_nodes_populate_selectable_tree_when_legacy_hierarchy_is_empty():
    app = APP
    envelope = make_publisher()[0].read_latest()
    hierarchy = replace(envelope.hierarchy, nodes={}, edges=())
    sources = replace(envelope.sources, hydra_graph=projection())
    envelope = replace(envelope, hierarchy=hierarchy, sources=sources)
    window = DashboardWindow(clock_domain=envelope.clock_domain)
    window._envelope = envelope

    window._render_hierarchy(envelope)

    assert window.hierarchy.topLevelItemCount() == 2
    ids = {window.hierarchy.topLevelItem(i).data(0, QtCore.Qt.UserRole)
           for i in range(window.hierarchy.topLevelItemCount())}
    assert ids == {'hydra:run:2:object-1', 'hydra:run:3:place-1'}
    window.close()
    app.processEvents()


def test_hydra_counts_are_not_read_from_empty_legacy_hierarchy():
    app = APP
    envelope = make_publisher()[0].read_latest()
    hierarchy = replace(envelope.hierarchy, nodes={}, edges=())
    sources = replace(envelope.sources, hydra_graph=projection())
    envelope = replace(envelope, hierarchy=hierarchy, sources=sources)
    window = DashboardWindow(clock_domain=envelope.clock_domain)
    window._envelope = envelope
    window._render_envelope(envelope)
    window._refresh_telemetry()

    text = window.overview.text()
    assert 'HYDRA OBJECTS 1' in text
    assert 'PLACES 1' in text
    assert 'ROOMS 0' in text
    assert 'HYDRA r7' in text
    window.close()
    app.processEvents()


def test_hydra_node_hover_uses_display_label_without_legacy_row_label():
    app = APP
    envelope = make_publisher()[0].read_latest()
    hierarchy = replace(envelope.hierarchy, nodes={}, edges=())
    sources = replace(envelope.sources, hydra_graph=projection())
    envelope = replace(envelope, hierarchy=hierarchy, sources=sources)
    view = SpatialSceneWidget()
    view.resize(640, 480)
    view.set_envelope(envelope)
    view.show()
    app.processEvents()
    view.grab()
    object_node = next(node for node in projection().nodes if node.layer_id == 2)
    point = view._screen_nodes[object_node.node_id].toPoint()
    event = QtGui.QMouseEvent(
        QtCore.QEvent.MouseMove,
        QtCore.QPointF(point),
        QtCore.Qt.NoButton,
        QtCore.Qt.NoButton,
        QtCore.Qt.NoModifier,
    )

    view.mouseMoveEvent(event)

    assert 'chair · object-1' in view.toolTip()
    assert object_node.node_id in view.toolTip()
    view.close()
