"""Display membership/topology use canonical edges, never geometric guesses."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from dataclasses import replace
import pytest
from PyQt5 import QtCore,QtWidgets
from test_display_snapshot import make_publisher,OID
from neusymnav.visualization.spatial_scene import SpatialSceneWidget
from neusymnav.visualization.scene_graph import SceneGraphWidget

@pytest.fixture(scope='module')
def app():return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

def test_3d_draws_room_object_and_room_connectivity(app):
    env=make_publisher()[0].read_latest();view=SpatialSceneWidget();view.set_envelope(env)
    assert ('r1',OID,'contains') in view.edges
    assert ('r1','r2','region_adjacent_to') in view.edges
    assert {n['row'].kind for n in view.nodes.values()}=={'floor','room','object'}
    assert not any(k=='place_connected_to' for _,_,k in view.edges)
    view.close()

def test_2d_draws_same_typed_relations_and_styles(app):
    env=make_publisher()[0].read_latest();view=SceneGraphWidget();view.set_envelope(env)
    paths=[item for item in view.scene().items() if isinstance(item,QtWidgets.QGraphicsPathItem)]
    room=[p for p in paths if p.data(0)==('r1','r2','region_adjacent_to')]
    assert len(room)==1
    assert room[0].pen().style()==QtCore.Qt.DashLine
    assert any(p.data(0)==('r1',OID,'contains') and p.pen().style()==QtCore.Qt.SolidLine for p in paths)
    assert 'structural' in room[0].toolTip().lower()
    view.close()

@pytest.mark.parametrize('bad',['stale','unassigned','other_floor','reverse_duplicate'])
def test_connectivity_respects_provenance_and_deduplicates(app,bad):
    env=make_publisher()[0].read_latest();h=env.hierarchy
    edge=next(e for e in h.edges if e.kind=='region_adjacent_to')
    nodes=dict(h.nodes);edges=list(h.edges)
    if bad=='stale':nodes['r2']=replace(nodes['r2'],attributes={**nodes['r2'].attributes,'stale':True})
    elif bad=='unassigned':edges[edges.index(edge)]=replace(edge,status='unavailable')
    elif bad=='other_floor':nodes['r2']=replace(nodes['r2'],attributes={**nodes['r2'].attributes,'floor_id':'other'})
    else:edges.append(replace(edge,source_id=edge.target_id,target_id=edge.source_id))
    env=replace(env,hierarchy=replace(h,nodes=nodes,edges=tuple(edges)))
    view=SpatialSceneWidget();view.set_envelope(env)
    links=[e for e in view.edges if e[2]=='region_adjacent_to']
    assert len(links)==(1 if bad=='reverse_duplicate' else 0)
    view.close()

def test_no_guessed_connectivity_when_source_has_no_adjacency(app):
    env=make_publisher()[0].read_latest();h=env.hierarchy
    env=replace(env,hierarchy=replace(h,edges=tuple(e for e in h.edges if e.kind!='region_adjacent_to')))
    view=SpatialSceneWidget();view.set_envelope(env)
    assert not any(k=='region_adjacent_to' for _,_,k in view.edges)
    view.close()
