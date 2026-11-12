import hashlib
import json
from dataclasses import replace

import numpy as np

from neusymnav.backends.hydra.graph_adapter import HydraDisplayNode, HydraGraphProjection
from neusymnav.contracts import FrameKey, dumps
from neusymnav.contracts.hydra_graph import HydraFrame
from neusymnav.rooms.room_views import select_room_views


def frame(index, x, color):
    pose = np.eye(4); pose[0, 3] = x
    return HydraFrame(FrameKey('ep', 'rgbd', index), index + 1, 'clock', float(index),
        'a'*64, 'cal', 'v1', 'b'*64, 'det', 'vocab', index,
        'canonical_z_up_v1', 'optical_x_right_y_down_z_forward_v1', 'metric_axial_v1',
        np.full((32, 32, 3), color, np.uint8), np.ones((32, 32), np.float32),
        np.ones((32, 32), bool), np.zeros((32, 32), np.int32),
        np.array([[40.,0,16],[0,40.,16],[0,0,1]]), np.eye(4), pose,
        pose[:3,3], np.array([1.,0,0,0]), 'labels', 'c'*64)


def graph():
    nodes = (HydraDisplayNode('r1','R1',4,None,None,None),
             HydraDisplayNode('r2','R2',4,None,None,None),
             HydraDisplayNode('p1','P1',3,None,(0,0,1),'r1'),
             HydraDisplayNode('p2','P2',3,None,(5,0,1),'r2'))
    source = dict(episode_id='ep', sensor_id='rgbd', clock_domain='clock',
                  labelspace_hash='c'*64, vocabulary_id='vocab')
    return HydraGraphProjection(1,'ep','run',3,'d'*64,nodes,(),{},source,False,False,None,
                                'available',{}, {'transform': {'calibration_hash':'b'*64}})


def write_journal(path, frames):
    rows = []
    for f, rev in frames:
        source = dict(episode_id='ep', sensor_id='rgbd', frame_index=f.source_key.frame_index,
                      capture_monotonic_ns=f.capture_monotonic_ns, clock_domain='clock',
                      labelspace_hash=f.labelspace_hash, vocabulary_id=f.vocabulary_id,
                      source_geometry_hash=f.source_geometry_hash, calibration_hash=f.calibration_hash)
        payload = dumps(f)
        rows += [dict(run_id='run', event='started', source=source, selected_frame=payload,
                      payload_sha256=hashlib.sha256(payload.encode()).hexdigest()),
                 dict(run_id='run', event='accepted', source=source, accepted=True, graph_revision=rev)]
    path.write_text(''.join(json.dumps(r)+'\n' for r in rows))


def test_room_purity_revision_dedup_and_manifest(tmp_path):
    path = tmp_path/'journal'; a = frame(0,0,40)
    write_journal(path, [(a,1), (replace(a, source_key=FrameKey('ep','rgbd',1), capture_monotonic_ns=2),2),
                         (frame(2,5,80),3), (frame(3,0,120),4)])
    views = select_room_views(path, graph(), 'r1', limit=3)
    assert len(views) == 1
    assert views[0].view_id == hashlib.sha256(views[0].jpeg).hexdigest()
    assert views[0].frame_index == 0
    manifest = views[0].manifest()
    assert manifest['room_purity'] >= .8 and 'jpeg' not in manifest
    json.dumps(manifest)
    assert select_room_views(path, graph(), 'r2')[0].frame_index == 2


def test_missing_room_and_invalid_method(tmp_path):
    import pytest
    path = tmp_path/'journal'; write_journal(path, [(frame(0,0,40),1)])
    assert select_room_views(path, graph(), 'absent') == ()
    with pytest.raises(ValueError): select_room_views(path, graph(), 'r1', method='unknown')


def test_complementary_spatial_views_and_batch(tmp_path):
    from neusymnav.rooms.room_views import select_room_views_batch
    path = tmp_path/'journal'
    write_journal(path, [(frame(0,0,20),1), (frame(1,.8,60),2), (frame(2,5,90),3)])
    batch = select_room_views_batch(path, graph(), ('r1','r2'), method='geometry')
    assert len(batch['r1']) == 2
    assert {v.frame_index for v in batch['r1']} == {0,1}
    assert batch['r2'][0].frame_index == 2
    assert batch['r1'] == select_room_views(path, graph(), 'r1', method='geometry')


def test_calibration_mismatch_and_ambiguous_room_are_rejected(tmp_path):
    path = tmp_path/'journal'; write_journal(path, [(frame(0,0,20),1)])
    g = graph()
    assert select_room_views(path, replace(g, native_metadata={'last_transform': {'calibration_hash':'e'*64}}), 'r1') == ()
    nodes = list(g.nodes)
    nodes[3] = replace(nodes[3], position=(0,0,1))
    assert select_room_views(path, replace(g, nodes=tuple(nodes)), 'r1') == ()


def test_frames_without_epoch_cannot_support_a_graph_with_explicit_epoch(tmp_path):
    path = tmp_path/'journal'
    write_journal(path, [(frame(0, 0, 20), 1)])
    g = graph()
    g = replace(g, native_metadata={**g.native_metadata, 'graph_world_epoch': 'epoch-2'})
    assert select_room_views(path, g, 'r1') == ()


def test_kss_adds_distinct_confirmed_object_view(tmp_path):
    g = graph()
    objects = (HydraDisplayNode('o1','O1',2,None,None,'r1'),
               HydraDisplayNode('o2','O2',2,None,None,'r1'))
    metadata = {'last_transform': {'calibration_hash':'b'*64},
                'room_label_input': {'semantic_labels': {'O1':1, 'O2':2}},
                'object_bounds': {'O1': ((-1,-1,.9),(1,1,1.1)),
                                  'O2': ((-1,-1,.9),(1,1,1.1))}}
    g = replace(g, nodes=g.nodes + objects, native_metadata=metadata)
    a = replace(frame(0,0,20), labels=np.ones((32,32),np.int32))
    b = replace(frame(1,0,60), labels=np.full((32,32),2,np.int32))
    path = tmp_path/'journal'; write_journal(path, [(a,1),(b,2)])
    assert len(select_room_views(path,g,'r1',method='geometry')) == 1
    kss = select_room_views(path,g,'r1',method='kss')
    assert [v.frame_index for v in kss] == [0,1]
    assert [v.manifest()['visible_object_ids'] for v in kss] == [['o1'],['o2']]


def test_kss_follows_object_place_room_ancestry(tmp_path):
    g = graph()
    objects = (HydraDisplayNode('o1','O1',2,None,None,'p1'),
               HydraDisplayNode('o2','O2',2,None,None,'p1'))
    metadata = {'last_transform': {'calibration_hash':'b'*64},
                'room_label_input': {'semantic_labels': {'O1':1, 'O2':2}},
                'object_bounds': {'O1': ((-1,-1,.9),(1,1,1.1)),
                                  'O2': ((-1,-1,.9),(1,1,1.1))}}
    g = replace(g, nodes=g.nodes + objects, native_metadata=metadata)
    a = replace(frame(0,0,20), labels=np.ones((32,32),np.int32))
    b = replace(frame(1,0,60), labels=np.full((32,32),2,np.int32))
    path = tmp_path/'journal'; write_journal(path, [(a,1),(b,2)])
    views = select_room_views(path,g,'r1',method='kss')
    assert [v.frame_index for v in views] == [0,1]
    assert [v.manifest()['visible_object_ids'] for v in views] == [['o1'],['o2']]
    assert views[0].manifest()['target_graph_revision'] == 3


def test_kss_adds_clearer_view_of_same_object(tmp_path):
    g = graph()
    obj = HydraDisplayNode('o1', 'O1', 2, None, None, 'p1')
    metadata = {'last_transform': {'calibration_hash': 'b'*64},
                'room_label_input': {'semantic_labels': {'O1': 1}},
                'object_bounds': {'O1': ((-1, -1, .9), (1, 1, 1.1))}}
    g = replace(g, nodes=g.nodes + (obj,), native_metadata=metadata)
    weak = np.zeros((32, 32), np.int32)
    weak[14:16, 14:16] = 1
    a = replace(frame(0, 0, 20), labels=weak)
    b = replace(frame(1, 0, 60), labels=np.ones((32, 32), np.int32))
    path = tmp_path/'journal'
    write_journal(path, [(a, 1), (b, 2)])
    assert len(select_room_views(path, g, 'r1', method='geometry')) == 1
    assert [v.frame_index for v in select_room_views(path, g, 'r1')] == [0, 1]
