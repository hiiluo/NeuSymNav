from test_hydra_scene_graph_query import _projection,_taxonomy
from neusymnav.backends.hydra.labels import HydraLabelRasterizer


def graph(label=None,x=1):
    taxonomy=_taxonomy();value=HydraLabelRasterizer(taxonomy).class_to_label['toilet'] if label is None else label
    return _projection(nodes=[{'native_id':'O(0)','layer_id':2,'name':'misleading unrelated name','semantic_label':value,'position':[x,2.,.5],'parent_native_id':'R(0)'}, {'native_id':'R(0)','layer_id':4,'name':'room','position':[0.,0.,0.],'parent_native_id':None}])


def test_display_projection_carries_explicit_source_bound_semantics():
    g=graph();s=g.native_metadata['room_label_input']
    assert s['semantic_labels']=={'O(0)':HydraLabelRasterizer(_taxonomy()).class_to_label['toilet']}
    assert s['graph_revision']==g.graph_revision and s['input_prefix_sha256']==g.input_prefix_sha256
    assert len(s['snapshot_sha256'])==64


def test_same_revision_different_geometry_or_semantics_has_different_snapshot_digest():
    a=graph();b=graph(x=2);c=graph(label=2)
    assert len({g.native_metadata['room_label_input']['snapshot_sha256'] for g in(a,b,c)})==3
