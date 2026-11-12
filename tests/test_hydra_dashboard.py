"""Native Hydra display evidence stays separate from the control raster."""
from types import SimpleNamespace

import numpy as np

from neusymnav.visualization.hydra_display import object_crop, room_outlines


def test_room_outlines_follow_free_space_and_separate_adjacent_rooms():
    nodes = [
        SimpleNamespace(node_id=name, layer_id=layer, parent_id=parent, position=pos)
        for name, layer, parent, pos in [
            ('r1', 4, None, None), ('r2', 4, None, None),
            ('p1', 3, 'r1', (.3, .3, 0.)), ('p2', 3, 'r2', (1.7, .3, 0.)),
        ]
    ]
    graph = SimpleNamespace(nodes=nodes)
    states = np.zeros((4, 12), dtype=np.int8)
    states[:, 10] = 100
    raster = SimpleNamespace(states=states, origin_xy=(0., 0.), resolution_m=.2)
    segments = room_outlines(graph, raster)
    assert any(np.allclose([a[0], b[0]], [1., 1.]) for a, b in segments)
    assert max(x for line in segments for x, _ in line) <= 2.0
    assert any(np.allclose([a[1], b[1]], [.8, .8]) for a, b in segments)


def test_object_crop_excludes_equal_class_pixels_outside_native_bounds():
    frame = SimpleNamespace(
        valid_depth=np.ones((10, 20), dtype=bool),
        labels=np.full((10, 20), 4), depth_m=np.ones((10, 20)),
        rgb=np.zeros((10, 20, 3), dtype=np.uint8), K=np.eye(3),
        world_T_body=np.eye(4), body_T_camera=np.eye(4),
    )
    frame.rgb[:, 10:] = 255
    match = object_crop(frame, 4, ((0, 0, .9), (7, 9, 1.1)), ())
    assert match is not None
    assert not np.any(match[1])
    assert object_crop(frame, 4, ((0, 0, .9), (7, 9, 1.1)),
                       (((0, 0, .9), (7, 9, 1.1)),)) is None


def test_object_best_view_falls_back_to_archived_frame(tmp_path, monkeypatch):
    from dataclasses import replace
    from neusymnav.visualization import hydra_display
    from test_room_views import frame, graph, write_journal

    older = frame(0, 0, 40)
    recent = frame(1, 5, 80)
    journal = tmp_path / 'journal.jsonl'
    write_journal(journal, [(older, 1), (recent, 2)])
    metadata = {'room_label_input': {'semantic_labels': {'O(0)': 0}},
                'object_bounds': {'O(0)': ((-1., -1., .9), (1., 1., 1.1))}}
    snapshot = replace(graph(), native_metadata=metadata)
    monkeypatch.setattr(hydra_display, 'LOOKBACK_BYTES', journal.stat().st_size // 2)
    match = hydra_display.read_best_view(journal, snapshot, 'O(0)')
    assert match is not None
    assert match[2:] == (0, 1)
    assert np.all(match[1] == 40)
    assert hydra_display.read_best_view(journal, snapshot, 'O(1)') is None


def test_dashboard_draws_room_outlines_and_click_loads_crop(tmp_path, monkeypatch):
    from dataclasses import replace

    from PyQt5 import QtCore, QtTest, QtWidgets
    from test_display_snapshot import make_publisher
    from neusymnav.backends.hydra.graph_adapter import HydraGraphAdapter
    from neusymnav.visualization import desktop

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, hierarchy, metrics, _, nav, _ = make_publisher()
    x, y = nav.origin_xy
    nodes = [
        dict(native_id=name, layer_id=layer, parent_native_id=parent, position=pos)
        for name, layer, parent, pos in [
            ('R(0)', 4, None, (x+.25, y+.25, .4)),
            ('R(1)', 4, None, (x+.75, y+.25, 0.)),
            ('p(0)', 3, 'R(0)', (x+.25, y+.25, 0.)),
            ('p(1)', 3, 'R(1)', (x+.75, y+.25, 0.)),
            ('O(0)', 2, 'R(0)', (x+.3, y+.3, 0.)),
        ]
    ]
    graph = HydraGraphAdapter.project(
        dict(schema_version=1, graph_revision=1, input_prefix_sha256='a'*64, nodes=nodes,
             layer_counts={'2': 1, '3': 2, '4': 2},
             edges=[dict(source_native_id='p(0)', target_native_id='p(1)', kind='intralayer')]),
        episode_id=nav.episode_id, run_id='run', stale=False, replay_required=False,
        failure_reason=None, last_source={'clock_domain': nav.clock_domain},
        native_metadata={'object_categories': {'O(0)': 'chair'}})
    publisher.publish(hierarchy, {**metrics, 'sources': replace(metrics['sources'], hydra_graph=graph)})
    selected = []

    def read(journal, snapshot, native_id):
        selected.append((journal, snapshot.run_id, native_id))
        return 10, np.full((20, 30, 3), 128, dtype=np.uint8), 9, 1

    monkeypatch.setattr(desktop, 'read_best_view', read)
    journal = tmp_path / 'journal.jsonl'
    cloud = SimpleNamespace(object_journal=journal, offer=lambda _: None, latest=None, error=None)
    window = desktop.DashboardWindow(publisher, clock_domain=nav.clock_domain, cloud_reader=cloud)
    try:
        window.show()
        app.processEvents()
        assert window.image_tabs.count() == 1
        assert window.map_tabs.count() == 1
        assert not window.boxes_toggle.isVisible()
        assert not selected
        for _ in range(50):
            window.map_view._poll_room_outline()
            if window.map_view._hydra_outline:
                break
            QtTest.QTest.qWait(10)
        assert window.map_view._hydra_outline
        image = window.map_view.grab().toImage()
        start, end = max(window.map_view._hydra_outline, key=lambda line: np.linalg.norm(np.subtract(*line)))
        center = window.map_view._world_to_pixel(np.mean([start, end], axis=0)).toPoint()
        assert any(image.pixelColor(center.x()+dx, center.y()+dy).name() == '#f4b942'
                   for dx in range(-2, 3) for dy in range(-2, 3))
        room_a, room_b, obj = 'hydra:run:4:R(0)', 'hydra:run:4:R(1)', 'hydra:run:2:O(0)'
        labels = {room_a: 'SLM bathroom'}
        window.spatial_view.set_room_labels(labels)
        window.graph_view.set_room_labels(labels)
        assert not hasattr(window.map_view, '_hydra_markers')
        spatial = window.spatial_view.nodes
        assert spatial[room_a]['position'][2] == spatial[room_b]['position'][2] > spatial[obj]['position'][2]
        assert spatial[room_a]['measured_position'][2] == .4
        assert (obj, room_a, 'derived_room_membership') in window.spatial_view.edges
        assert window.graph_view.node_items[room_a].y() < window.graph_view.node_items[obj].y()
        window.graph_view.set_envelope(publisher.read_latest(), room_passages=((room_a, room_b),))
        paths = [item for item in window.graph_view.scene().items()
                 if isinstance(item, QtWidgets.QGraphicsPathItem)]
        assert {item.pen().style() for item in paths} == {QtCore.Qt.SolidLine, QtCore.Qt.DashLine}
        window.scene_tabs.setCurrentWidget(window.graph_view)
        window.graph_view.node_items[obj].setSelected(True)
        for _ in range(30):
            window._poll_object_view()
            if window.best_view.pixmap() is not None:
                break
            QtTest.QTest.qWait(10)
        assert selected == [(journal, 'run', 'O(0)')]
        assert window.best_view.pixmap() is not None
        assert 'frame 9' in window.best_view_caption.text()
    finally:
        window.close()


def test_room_passage_requires_direct_native_link_and_measured_clearance():
    from dataclasses import replace

    from neusymnav.visualization.hydra_display import room_passages
    from test_regions import nav as make_nav

    nav = make_nav()
    x, y = nav.origin_xy
    points = {
        'p1': (x+1.5*nav.resolution_m, y+1.5*nav.resolution_m, 0.),
        'p2': (x+3.5*nav.resolution_m, y+1.5*nav.resolution_m, 0.),
    }
    graph = SimpleNamespace(
        episode_id=nav.episode_id, status='available', last_source={'clock_domain': nav.clock_domain},
        native_metadata={'display_robot': {'geometry_id': nav.robot_geometry_id,
                                           'radius_m': .01, 'margin_m': 0., 'height_m': 1.}},
        nodes=[
            SimpleNamespace(node_id='r1', layer_id=4, parent_id=None, position=None),
            SimpleNamespace(node_id='r2', layer_id=4, parent_id=None, position=None),
            *(SimpleNamespace(node_id=pid, layer_id=3, parent_id=rid, position=points[pid])
              for pid, rid in [('p1', 'r1'), ('p2', 'r2')]),
        ],
        edges=[SimpleNamespace(source='p1', target='p2', kind='intralayer')],
    )
    states = np.zeros_like(nav.states)
    support = np.ones_like(nav.floor_support)
    clearance = np.full_like(nav.clearance, 2.)
    free = replace(nav, states=states, floor_support=support, clearance=clearance)
    assert room_passages(graph, free) == (('r1', 'r2'),)
    states[1, 2] = -1
    assert room_passages(graph, replace(free, states=states)) == ()
    clearance[1, 2] = .5
    assert room_passages(graph, replace(free, clearance=clearance)) == ()
    graph.edges.clear()
    assert room_passages(graph, free) == ()


def test_robot_trail_does_not_fill_the_polygon_when_brush_is_set():
    from PyQt5 import QtGui, QtWidgets
    from neusymnav.contracts import FrameKey
    from neusymnav.visualization.desktop import MapWidget
    from neusymnav.visualization.robot_overlay import RobotSample, RobotTrack
    from test_display_snapshot import make_publisher

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, _, _, _, nav, _ = make_publisher()
    widget = MapWidget()
    widget.resize(500, 400)
    widget.set_snapshot(nav, publisher.read_latest())
    x, y = nav.origin_xy
    widget._robot = RobotTrack(tuple(
        RobotSample(FrameKey(nav.episode_id, 'depth', i), 100+i, nav.clock_domain,
                    i, point, 0.)
        for i, point in enumerate(((x+1, y+1), (x+4, y+1), (x+4, y+4)))))
    image = QtGui.QImage(widget.size(), QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor('black'))
    painter = QtGui.QPainter(image)
    painter.setBrush(QtGui.QColor('#efb451'))
    try:
        widget._draw_robot(painter)
    finally:
        painter.end()
    point = widget._world_to_pixel((x+3, y+2)).toPoint()
    assert image.pixelColor(point).name() == '#000000'
    widget.close()
