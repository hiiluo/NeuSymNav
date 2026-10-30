"""Presentation-only Floor→Room→Object regression oracles."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
import numpy as np
import pytest
from PyQt5 import QtWidgets
from neusymnav.contracts import HierarchyNode
from neusymnav.visualization.hierarchy_view import hierarchy_rows
from neusymnav.visualization.spatial_scene import SpatialSceneWidget
from neusymnav.visualization.scene_graph import SceneGraphWidget
from test_display_snapshot import make_publisher, OID, ALIAS


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def changed(envelope, **node_changes):
    return replace(envelope, hierarchy=replace(envelope.hierarchy, nodes={**envelope.hierarchy.nodes, **node_changes}))


def test_exact_three_levels_keep_canonical_ids_and_source_membership(app):
    envelope = make_publisher()[0].read_latest()
    envelope = changed(envelope, internal=HierarchyNode('internal', 'place', {'xy': (0., 0.)}))
    rows = {r.node_id: r for r in hierarchy_rows(envelope)}
    assert {r.kind for r in rows.values()} == {'floor', 'room', 'object'}
    floor = next(r for r in rows.values() if r.kind == 'floor')
    assert floor.parent_id is None and rows['r1'].parent_id == floor.node_id
    assert rows[OID].parent_id == 'r1'
    assert rows[OID].aliases == (ALIAS,)
    assert envelope.hierarchy.nodes['r1'].kind == 'region'
    scene = SpatialSceneWidget(); scene.set_envelope(envelope)
    graph = SceneGraphWidget(); graph.set_envelope(envelope)
    assert {n['row'].kind for n in scene.nodes.values()} == {'floor', 'room', 'object'}
    assert {n.data(1) for n in graph.node_items.values()} == {'floor', 'room', 'object'}
    assert set(scene.edges) == {(r.parent_id, r.node_id, 'contains') for r in rows.values() if r.parent_id} | {('r1','r2','region_adjacent_to')}
    scene.select_object('internal')
    assert 'internal' not in scene.nodes
    scene.close(); graph.close()


def test_geometry_center_updates_concavity_floor_and_separate_display_height(app):
    from neusymnav.regions.geometry import ring_covers
    envelope = make_publisher()[0].read_latest()
    scene = SpatialSceneWidget(); scene.set_envelope(envelope)
    before = scene.nodes['r1']['position'].copy()
    # U-shaped room: area centroid and vertex mean both lie in the excluded notch.
    polygon = np.array([(0,0),(6,0),(6,6),(5,6),(5,1),(1,1),(1,6),(0,6)], float)
    room = envelope.hierarchy.nodes['r1']
    # Omit the new producer center to exercise compatibility with retained publications.
    attrs = {k:v for k,v in room.attributes.items() if k not in {'center_xy','center_method'}}
    attrs['polygon'] = polygon
    scene.set_envelope(changed(envelope, r1=replace(room, attributes=attrs)))
    center = scene.nodes['r1']['position']
    assert not np.array_equal(before[:2], center[:2])
    assert ring_covers(tuple(center[:2]), tuple(map(tuple, polygon)))
    floor = next(n for n in scene.nodes.values() if n['row'].kind == 'floor')
    assert np.allclose(floor['position'][:2], (16*center[:2]+np.array([1.5,.5]))/17)
    assert floor['position'][2] > center[2] > max(n['position'][2] for n in scene.nodes.values() if n['row'].kind == 'object')
    obj = scene.nodes[OID]
    assert np.array_equal(obj['measured_position'], envelope.hierarchy.nodes[OID].attributes['centroid'])
    assert np.array_equal(obj['measured_bounds'], envelope.hierarchy.nodes[OID].attributes['bounds'])
    assert np.array_equal(obj['position'],obj['measured_position'])
    assert np.array_equal(envelope.hierarchy.nodes[OID].attributes['centroid'], obj['measured_position'])
    scene.close()


def test_unassigned_or_stale_membership_never_draws_parent(app):
    envelope = make_publisher(stale=True)[0].read_latest()
    rows = hierarchy_rows(envelope)
    assert all(r.parent_id is None for r in rows if r.kind == 'object')
    scene = SpatialSceneWidget(); scene.set_envelope(envelope)
    assert not any(target == OID for _,target,_ in scene.edges)
    scene.close()


def test_node_caps_reserve_floor_and_room_before_objects(app):
    envelope = make_publisher()[0].read_latest()
    original = envelope.hierarchy.nodes[OID]
    nodes = {k:v for k,v in envelope.hierarchy.nodes.items() if v.kind != 'object'}
    nodes.update({f'a-object-{i:04}': replace(original,node_id=f'a-object-{i:04}') for i in range(305)})
    hierarchy = replace(envelope.hierarchy,nodes=nodes,edges=tuple(e for e in envelope.hierarchy.edges if e.kind != 'in_region'))
    envelope = replace(envelope,hierarchy=hierarchy)
    scene = SpatialSceneWidget(); scene.set_envelope(envelope)
    graph = SceneGraphWidget(); graph.set_envelope(envelope)
    for visible in (scene.nodes, graph.node_items):
        assert len(visible) == 300
        assert 'r1' in visible and 'floor:f' in visible
    assert scene.hidden_count == graph.hidden_count == 8
    scene.close(); graph.close()


def test_live_map_and_robot_advance_independently_of_pinned_room_geometry(app):
    from neusymnav.visualization.desktop import DashboardWindow
    from neusymnav.visualization.robot_overlay import RobotSample, RobotTrack
    publisher, hierarchy, metrics, _, pinned, _ = make_publisher()
    live = replace(pinned, revision=2, source=replace(pinned.source, frame_index=2), capture_monotonic_ns=180)
    robot = RobotTrack((RobotSample(live.source,180,'clock',1,(.7,.5),0.),))
    sources = replace(metrics['sources'], live_nav=live, robot=robot)
    publisher.publish(hierarchy, {**metrics,'sources':sources,'source_age_ns':{**metrics['source_age_ns'],'live_map':20}})
    now = [200]
    window = DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:now[0])
    window.show(); app.processEvents()
    assert window.map_view._nav is live and window.map_view._robot is robot
    assert window._envelope.hierarchy is hierarchy and window._envelope.sources.nav is pinned
    assert window.map_view._stale
    assert 'Map r2' in window.map_view._map_caption()
    assert 'room outlines map r1' in window.map_view._map_caption()
    assert 'STALE' in window.map_view._map_caption()
    assert np.array_equal(window.map_view._regions[0], hierarchy.nodes['r1'].attributes['polygon'])
    now[0] = 1_000_000_000
    window.refresh()
    assert 'capture 150 ns' in window.rgb_caption.text() and '1000.0 ms' in window.rgb_caption.text()
    assert 'depth:2' in window.telemetry.text() and 'capture 180 ns' in window.telemetry.text()
    assert 'RGB: rgbd:2' in window.telemetry.text()
    window.close()


def test_conflicting_or_missing_object_parent_stays_explicitly_disconnected(app):
    envelope = make_publisher()[0].read_latest()
    edge = next(e for e in envelope.hierarchy.edges if e.kind == 'in_region' and e.source_id == OID)
    bad = replace(envelope,hierarchy=replace(envelope.hierarchy,edges=envelope.hierarchy.edges+(replace(edge,target_id='r2'),)))
    rows = {r.node_id:r for r in hierarchy_rows(bad)}
    assert rows[OID].parent_id is None
    assert rows[OID].status == 'unassigned'
    scene = SpatialSceneWidget(); scene.set_envelope(bad)
    assert not any(target == OID for _,target,_ in scene.edges)
    scene.close()


def test_dynamic_layers_account_for_tall_measured_bounds(app):
    envelope = make_publisher()[0].read_latest()
    obj = envelope.hierarchy.nodes[OID]
    attrs = {**obj.attributes,'centroid':np.array([.5,.5,25.]),'bounds':np.array([[0.,0.,20.],[1.,1.,30.]])}
    scene = SpatialSceneWidget(); scene.set_envelope(changed(envelope,**{OID:replace(obj,attributes=attrs)}))
    z = {kind:[n['position'][2] for n in scene.nodes.values() if n['row'].kind == kind] for kind in ('floor','room','object')}
    assert min(z['floor']) > max(z['room']) > 30. > max(z['object'])
    assert max(z['object']) == 25.
    assert scene.nodes[OID]['measured_position'][2] == 25.
    assert scene.nodes[OID]['measured_bounds'][1,2] == 30.
    scene.close()


def test_2d_layout_places_floor_above_room_above_objects(app):
    envelope = make_publisher()[0].read_latest()
    view = SceneGraphWidget(); view.set_envelope(envelope)
    ys = {kind:[item.pos().y() for item in view.node_items.values() if item.data(1) == kind]
          for kind in ('floor','room','object')}
    assert max(ys['floor']) < min(ys['room']) < min(ys['object'])
    view.close()


def test_floor_center_uses_only_own_source_assigned_room_geometry(app):
    envelope = make_publisher()[0].read_latest()
    nodes = dict(envelope.hierarchy.nodes)
    nodes['floor:second'] = HierarchyNode('floor:second','floor',{'floor_id':'second','floor_z_m':3.})
    nodes['distant-room'] = HierarchyNode('distant-room','region',{'floor_id':'second','polygon':np.array([[100.,0.],[104.,0.],[104.,2.],[100.,2.]])})
    edge = next(e for e in envelope.hierarchy.edges if e.source_id == 'floor:f' and e.target_id == 'r1')
    hierarchy = replace(envelope.hierarchy,nodes=nodes,edges=envelope.hierarchy.edges+(replace(edge,source_id='floor:second',target_id='distant-room'),))
    scene = SpatialSceneWidget();scene.set_envelope(replace(envelope,hierarchy=hierarchy))
    assert np.allclose(scene.nodes['floor:f']['position'][:2],[1.,.5])
    assert np.allclose(scene.nodes['floor:second']['position'][:2],[102.,1.])
    scene.close()


@pytest.mark.parametrize('polygon',[(), 'bad polygon', ((0.,0.),(1.,1.),(2.,2.))])
def test_invalid_room_geometry_is_hidden_without_crashing_with_producer_center(app,polygon):
    envelope = make_publisher()[0].read_latest()
    room = envelope.hierarchy.nodes['r1']
    attrs = {**room.attributes,'polygon':polygon,'center_xy':(.5,.5)}
    scene = SpatialSceneWidget();scene.set_envelope(changed(envelope,r1=replace(room,attributes=attrs)))
    assert 'r1' not in scene.nodes
    scene.close()


def test_objects_keep_exact_measured_xyz_inside_rgbd_scene(app):
    envelope = make_publisher()[0].read_latest()
    scene = SpatialSceneWidget();scene.set_envelope(envelope)
    for node_id,node in scene.nodes.items():
        if node['row'].kind == 'object':
            assert np.array_equal(node['position'], envelope.hierarchy.nodes[node_id].attributes['centroid'])
    room_z = min(n['position'][2] for n in scene.nodes.values() if n['row'].kind == 'room')
    object_top = max(n['measured_bounds'][1,2] for n in scene.nodes.values() if n['row'].kind == 'object')
    assert room_z > object_top
    scene.close()


def test_tree_hides_internal_kinds_and_uses_same_canonical_selection(app):
    from PyQt5 import QtCore
    from neusymnav.visualization.desktop import DashboardWindow
    envelope = make_publisher()[0].read_latest()
    envelope = changed(envelope,internal=HierarchyNode('internal','place',{'xy':(0.,0.)}))
    window = DashboardWindow(lambda:envelope,clock_domain='clock',now_ns=lambda:200)
    def ids(item):
        return {item.data(0,QtCore.Qt.UserRole)}.union(*(ids(item.child(i)) for i in range(item.childCount())))
    displayed = set().union(*(ids(window.hierarchy.topLevelItem(i)) for i in range(window.hierarchy.topLevelItemCount())))
    assert displayed == {r.node_id for r in hierarchy_rows(envelope)}
    assert 'internal' not in displayed and 'building:e' not in displayed
    assert window.select_object(ALIAS) == OID
    assert window.spatial_view.selected == OID and window.graph_view.node_items[OID].isSelected()
    window.close()


def test_new_accepted_producer_center_moves_room_anchor_without_changing_id(app):
    from neusymnav.regions.geometry import room_center
    envelope = make_publisher()[0].read_latest()
    room = envelope.hierarchy.nodes['r1']
    polygon = np.asarray(room.attributes['polygon'])+np.array([4.,2.])
    attrs = {**room.attributes,'polygon':polygon,'center_xy':room_center(polygon)}
    view = SpatialSceneWidget();view.set_envelope(changed(envelope,r1=replace(room,attributes=attrs)))
    assert np.allclose(view.nodes['r1']['position'][:2],[4.5,2.5])
    assert envelope.hierarchy.nodes['r1'].node_id == view.nodes['r1']['row'].node_id
    view.close()
