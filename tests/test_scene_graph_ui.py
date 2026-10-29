"""Graph selection must preserve canonical provenance and leave unknown parents disconnected."""
import os
from dataclasses import replace
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt5 import QtCore, QtWidgets
from test_display_snapshot import make_publisher, OID, ALIAS
from neusymnav.visualization.desktop import DashboardWindow
from neusymnav.visualization.scene_graph import SceneGraphWidget


def test_graph_selection_alias_and_refresh_are_view_only():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, hierarchy, metrics, objects, nav, now = make_publisher(stale=True)
    before = tuple(hierarchy.edges)
    window = DashboardWindow(publisher, clock_domain='clock', now_ns=lambda:250)
    window.show(); app.processEvents()
    item = window.graph_view.node_items[OID]
    item.setSelected(True); app.processEvents()
    assert window._selected_object_id == OID
    assert 'Lifecycle: active' in window.object_details.text()
    assert window.select_object(ALIAS) == OID
    assert window.graph_view.node_items[OID].isSelected()
    publisher.publish(hierarchy, metrics)
    window.refresh(); app.processEvents()
    assert window.graph_view.node_items[OID].isSelected()
    assert tuple(hierarchy.edges) == before
    assert window.map_view._stale
    window.close()


def test_unknown_parent_is_not_invented_and_graph_projection_is_capped():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, hierarchy, *_ = make_publisher()
    envelope = publisher.read_latest()
    original = hierarchy.nodes[OID]
    # Excessive display projection; no corresponding source objects are manufactured.
    nodes = {f'object-{i:04}': replace(original, node_id=f'object-{i:04}') for i in range(305)}
    value = replace(envelope, hierarchy=replace(hierarchy,nodes=nodes,edges=()))
    view = SceneGraphWidget()
    view.set_envelope(value)
    assert len(view.node_items) == 300 and view.hidden_count == 5
    assert not any(isinstance(item,QtWidgets.QGraphicsPathItem) for item in view.scene().items())
    view.close()


def test_resize_and_historical_status_remain_explicit():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, *_ = make_publisher()
    window = DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:1_000_000_000)
    window.resize(1100,720);window.show();app.processEvents()
    window.resize(1440,900);app.processEvents()
    assert window.status_badge.text() == 'STALE PUBLICATION'
    assert window.rgb_view.pixmap() is not None
    assert window.rgb_caption.wordWrap() and window.best_view_caption.wordWrap()
    window.close()


def test_map_palette_keeps_unknown_distinct_and_draws_positive_y_up():
    from neusymnav.visualization.desktop import MapWidget
    publisher, *_ = make_publisher()
    nav = publisher.read_latest().sources.nav
    import numpy as np
    states = np.array([[-1, 0], [100, -1]], dtype=np.int8)
    value = replace(nav, states=states,
                    floor_support=np.zeros((2,2),dtype=bool),
                    clearance=np.zeros((2,2),dtype=float))
    image = MapWidget._raster_image(value)
    assert image.pixelColor(0,0).getRgb()[:3] == (245,91,79)
    assert image.pixelColor(0,1).getRgb()[:3] == (68,82,101)
    assert image.pixelColor(1,1).getRgb()[:3] == (58,145,111)


def test_hierarchy_rank_labels_do_not_overlap_adjacent_columns():
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher,*_=make_publisher(stale=True)
    from neusymnav.contracts import HierarchyNode
    envelope=publisher.read_latest()
    nodes={**envelope.hierarchy.nodes,'display-place':HierarchyNode('display-place','place'),
           'display-region':HierarchyNode('display-region','region',{'stale':True})}
    envelope=replace(envelope,hierarchy=replace(envelope.hierarchy,nodes=nodes))
    view=SceneGraphWidget();view.set_envelope(envelope)
    labels=[item for item in view.scene().items() if isinstance(item,QtWidgets.QGraphicsSimpleTextItem)]
    for index,left in enumerate(labels):
        for right in labels[index+1:]:
            assert not left.sceneBoundingRect().intersects(right.sceneBoundingRect()),(left.text(),right.text())
    view.close()
