import pytest

from neusymnav.backends.hydra.graph_adapter import HydraGraphAdapter
from neusymnav.backends.hydra.worker import _graph_summary


def graph_summary(revision=3, *, nodes=None, edges=None):
    default_nodes=[
            dict(native_id='O(2)', layer_id=2, name='chair', position=[1.,2.,3.], parent_native_id=None),
            dict(native_id='p(7)', layer_id=3, name='place', position=[1.,2.,0.], parent_native_id='R(1)'),
            dict(native_id='R(1)', layer_id=4, name='room', position=[1.,2.,0.], parent_native_id='B(0)'),
            dict(native_id='B(0)', layer_id=5, name='building', position=[1.,2.,0.], parent_native_id=None)]
    chosen_nodes=default_nodes if nodes is None else nodes
    counts={str(layer):sum(node['layer_id']==layer for node in chosen_nodes) for layer in (2,3,4,5)}
    return dict(schema_version=1, graph_revision=revision, input_prefix_sha256='a'*64,
        layer_counts=counts,nodes=chosen_nodes,
        edges=edges if edges is not None else [dict(source_native_id='p(7)', target_native_id='R(1)', kind='parent'),
            dict(source_native_id='R(1)', target_native_id='B(0)', kind='parent')])


def test_projection_namespaces_native_ids_and_keeps_membership_and_provenance():
    result = HydraGraphAdapter.project(graph_summary(), episode_id='episode-1', run_id='run-1',
        stale=False, replay_required=False, failure_reason=None,
        last_source=dict(sensor_id='rgbd', frame_index=8, capture_monotonic_ns=100,
                         clock_domain='host:boot1'))
    assert result.schema_version == 1
    assert result.node_counts['4'] == 1
    room = next(node for node in result.nodes if node.native_id == 'R(1)')
    place = next(node for node in result.nodes if node.native_id == 'p(7)')
    assert room.node_id == 'hydra:run-1:4:R(1)'
    assert place.parent_id == room.node_id
    assert result.edges[0].source == place.node_id
    assert result.provenance['input_prefix_sha256'] == 'a'*64
    assert result.status == 'available'


def test_projection_replaces_removed_nodes_and_drops_empty_room_layer_without_inventing_rooms():
    result = HydraGraphAdapter.project(graph_summary(nodes=[
        dict(native_id='O(2)', layer_id=2, name='chair', position=[1.,2.,3.], parent_native_id=None)],
        edges=[]), episode_id='episode-1', run_id='run-1', stale=False,
        replay_required=False, failure_reason=None, last_source=None)
    assert [node.native_id for node in result.nodes] == ['O(2)']
    assert result.node_counts['5'] == 0
    assert result.status == 'available'


def test_projection_fails_closed_on_dangling_edges_unknown_layers_and_stale_graph():
    bad = graph_summary(edges=[dict(source_native_id='p(7)', target_native_id='missing', kind='parent')])
    with pytest.raises(ValueError, match='edge endpoint'):
        HydraGraphAdapter.project(bad, episode_id='e', run_id='r', stale=False,
            replay_required=False, failure_reason=None, last_source=None)
    bad = graph_summary(nodes=[dict(native_id='x',layer_id=99,name='?',position=None,parent_native_id=None)],edges=[])
    with pytest.raises(ValueError, match='layer'):
        HydraGraphAdapter.project(bad, episode_id='e', run_id='r', stale=False,
            replay_required=False, failure_reason=None, last_source=None)
    stale = HydraGraphAdapter.project(graph_summary(), episode_id='e', run_id='r', stale=True,
        replay_required=True, failure_reason='worker timeout', last_source=None)
    assert stale.status == 'stale'
    assert stale.replay_required and stale.failure_reason == 'worker timeout'


def test_native_summary_captures_current_nodes_and_filters_edges_after_node_removal():
    class Edge:
        def __init__(self, source, target): self.source=source;self.target=target
    class Attr:
        def __init__(self,name,position):self.name=name;self.position=position
    class Node:
        def __init__(self,node_id,name,position,parent=None):
            self.id=node_id;self.attributes=Attr(name,position);self._parent=parent
        def get_parent(self):return self._parent
    class Layer:
        id=5
        def __init__(self,nodes,edges):self.nodes=nodes;self.edges=edges
    class Graph:
        layers=[Layer([Node('R(1)','room',[1.,2.,0.])],[Edge('R(1)','missing')])]
        interlayer_edges=[]

    summary=_graph_summary(Graph(),graph_revision=4,input_prefix_sha256='b'*64)
    assert summary['nodes'][0]['native_id']=='R(1)'
    assert summary['nodes'][0]['position']==[1.,2.,0.]
    assert summary['edges']==[]
    assert summary['graph_revision']==4


def test_native_summary_converts_numeric_parent_symbol_value_to_display_node_id():
    class NodeSymbol:
        def __init__(self, label, value): self.label=label;self.value=value
        def __str__(self): return self.label
    class Attr:
        def __init__(self,name,position):self.name=name;self.position=position
    class Node:
        def __init__(self,node_id,name,position,parent=None):
            self.id=node_id;self.attributes=Attr(name,position);self._parent=parent
        def get_parent(self):return self._parent
    class Layer:
        def __init__(self,layer_id,nodes):self.id=layer_id;self.nodes=nodes;self.edges=[]
    class Edge:
        def __init__(self,source,target):self.source=source;self.target=target
    class Graph:
        layers=[
            Layer(3,[Node(NodeSymbol('p(4)',8070450532247928836),'place',[0.,0.,0.],
                            5908722711110090752)]),
            Layer(4,[Node(NodeSymbol('R(0)',5908722711110090752),'room',[0.,0.,0.])]),
        ]
        interlayer_edges=[Edge(8070450532247928836,5908722711110090752)]

    summary=_graph_summary(Graph(),graph_revision=5,input_prefix_sha256='c'*64)
    place=next(node for node in summary['nodes'] if node['native_id']=='p(4)')
    assert place['parent_native_id']=='R(0)'
    assert summary['edges']==[dict(source_native_id='p(4)',target_native_id='R(0)',kind='interlayer')]
    projected=HydraGraphAdapter.project(summary,episode_id='e',run_id='r',stale=False,
        replay_required=False,failure_reason=None,last_source=None)
    assert next(node for node in projected.nodes if node.native_id=='p(4)').parent_id=='hydra:r:4:R(0)'


def test_hydra_projection_roundtrips_through_display_publication_and_ui_wire():
    import os
    os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PyQt5 import QtWidgets
    from neusymnav.contracts import HierarchySnapshot
    from neusymnav.visualization.publisher import DisplayPublisher,DisplaySources
    from neusymnav.runtime.ui_transport import _encode_value,_decode_value
    projection=HydraGraphAdapter.project(graph_summary(),episode_id='episode-1',run_id='run-1',
        stale=False,replay_required=False,failure_reason=None,last_source=None)
    publisher=DisplayPublisher(clock_domain='host:boot1',now_ns=lambda:100)
    hierarchy=HierarchySnapshot('episode-1',3,0,0,0,{},(),
        {'legacy_hierarchy':'unavailable_hydra_backend','hydra_graph':'available'},0,0)
    metrics=dict(captured_frame_id=None,processed_frame_id=None,published_frame_id=None,
        source_age_ns={},dropped_count=0,replaced_count=0,actual_profile='hydra',
        sources=DisplaySources(hydra_graph=projection))
    publisher.publish(hierarchy,metrics)
    decoded=_decode_value(_encode_value(publisher.read_latest()))
    assert decoded.sources.hydra_graph.nodes[0].node_id.startswith('hydra:run-1:')
    assert decoded.sources.hydra_graph.node_counts['4']==1
    assert decoded.sources.hydra_graph.node_counts['5']==1
    from neusymnav.visualization.scene_graph import SceneGraphWidget
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget=SceneGraphWidget();widget.set_envelope(decoded)
    # A1 defaults to Rooms + Objects; request all layers for this wire test.
    assert len(widget.node_items)==2
    widget.set_hydra_layer_filter({2,3,4,5})
    assert len(widget.node_items)==4
    widget.set_hydra_layer_filter({4})
    assert len(widget.node_items)==1
    # Object evidence picking applies to object nodes, not room anchors.
    widget.set_hydra_layer_filter({2})
    assert len(widget.node_items)==1
    node_id=next(iter(widget.node_items));widget.select_object(node_id)
    assert widget.node_items[node_id].isSelected()
    widget.close();app.processEvents()
