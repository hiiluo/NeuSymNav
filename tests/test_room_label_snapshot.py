import hashlib
import json
from pathlib import Path

import pytest

from neusymnav.backends.hydra.labels import HydraLabelRasterizer
from test_hydra_scene_graph_query import _taxonomy
from tools.snapshot_room_label_requests import build_room_label_requests


def inputs():
    taxonomy = _taxonomy()
    rasterizer = HydraLabelRasterizer(taxonomy)
    prefix = 'a'*64
    source = {'episode_id':'ep-1','sensor_id':'primary','frame_index':42,
        'capture_monotonic_ns':123,'clock_domain':'mono:1',
        'vocabulary_id':taxonomy.vocabulary_id,'labelspace_id':rasterizer.LABELSPACE_ID,
        'labelspace_hash':rasterizer.labelspace_hash,'source_geometry_hash':'b'*64}
    nodes = [
        {'native_id':'O(0)','layer_id':2,'name':'chair','semantic_label':rasterizer.class_to_label['chair'],
         'position':[1.,2.,.5],'parent_native_id':'p(0)'},
        {'native_id':'p(0)','layer_id':3,'name':'place','position':[1.,2.,0.],
         'parent_native_id':'R(0)'},
        {'native_id':'R(0)','layer_id':4,'name':'room','position':[1.,2.,0.],
         'parent_native_id':'B(0)'},
        {'native_id':'B(0)','layer_id':5,'name':'building','position':[1.,2.,0.],
         'parent_native_id':None},
    ]
    summary = {'schema_version':1,'graph_revision':9,'input_prefix_sha256':prefix,
        'layer_counts':{str(layer):sum(n['layer_id']==layer for n in nodes) for layer in (2,3,4,5)},
        'nodes':nodes,'edges':[]}
    record = {'summary':summary,'graph_revision':9,'input_prefix_sha256':prefix,
        'calibration_hash':'c'*64,'graph_sha256':'d'*64,'build_sha256':'e'*64,
        'config_sha256':'f'*64,'source_geometry_hash':'b'*64,'calibration_id':'camera-1'}
    replay = {'episode_id':'ep-1','run_id':'replay-1','source_manifest_sha256':'1'*64,
        'selected_inputs':[{'graph_revision':9,'input_prefix_sha256':prefix,'source':source}]}
    profile = {'sensor_config':{'primary':{'calibration':{
        'calibration_id':'camera-1','coordinate_convention':'canonical_z_up_v1'}}}}
    return record,replay,profile


def test_snapshot_uses_explicit_semantic_ids_and_records_frozen_graph_identity(tmp_path):
    record,replay,profile=inputs()
    taxonomy_path=tmp_path/'taxonomy.json'
    taxonomy=_taxonomy()
    taxonomy_path.write_text(json.dumps({'schema_version':1,
        'vocabulary_id':taxonomy.vocabulary_id,'categories':list(taxonomy.categories),
        'aliases':dict(taxonomy.aliases),'provenance':taxonomy.provenance}))
    requests=build_room_label_requests(record,replay,profile,taxonomy_path)
    request,=requests
    assert request.key.run_id=='replay-1'
    assert request.key.graph_revision==9
    assert request.context.objects[0].category=='chair'
    assert request.context.objects[0].membership_status=='assigned'
    assert request.inference_block_reason is None
    assert request.source_manifest['native_graph_sha256']=='d'*64


def test_snapshot_rejects_revision_prefix_or_calibration_mismatch(tmp_path):
    record,replay,profile=inputs()
    taxonomy_path=tmp_path/'taxonomy.json'; taxonomy=_taxonomy()
    taxonomy_path.write_text(json.dumps({'schema_version':1,
        'vocabulary_id':taxonomy.vocabulary_id,'categories':list(taxonomy.categories),
        'aliases':dict(taxonomy.aliases),'provenance':taxonomy.provenance}))
    replay['selected_inputs'][0]['input_prefix_sha256']='2'*64
    with pytest.raises(ValueError,match='input prefix'):
        build_room_label_requests(record,replay,profile,taxonomy_path)

    replay['selected_inputs'][0]['input_prefix_sha256']='a'*64
    profile['sensor_config']['primary']['calibration']['calibration_id']='wrong'
    with pytest.raises(ValueError,match='calibration'):
        build_room_label_requests(record,replay,profile,taxonomy_path)
