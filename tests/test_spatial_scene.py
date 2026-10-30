"""Spatial UI geometry/provenance, not model or simulator correctness."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import hashlib
import json
import sqlite3
import time

import numpy as np
import pytest
from PyQt5 import QtCore, QtTest, QtWidgets

from contract_helpers import observation
from test_display_snapshot import make_publisher, OID, ALIAS
from neusymnav.contracts import FrameKey
from neusymnav.contracts.serialization import dumps
from neusymnav.visualization.point_cloud import CommittedCloudReader, AsyncCloudReader, project_rgbd
from neusymnav.visualization.spatial_scene import SpatialSceneWidget


def fixture(tmp_path):
    envelope=make_publisher()[0].read_latest()
    root=tmp_path/'assets';root.mkdir()
    obs=observation(key=FrameKey('e','rgbd',0),clock_domain='clock',capture_monotonic_ns=100,
                    rgb=np.full((2,3,3),[10,20,30],np.uint8))
    add_db(root,obs,create=True)
    return envelope,root,obs


def add_db(root,obs,create=False,**changes):
    payload=dumps(obs).encode();ref=hashlib.sha256(payload).hexdigest();(root/ref).write_bytes(payload)
    data=dict(source=dict(episode_id=obs.key.episode_id,sensor_id=obs.key.sensor_id,frame_index=obs.key.frame_index),capture_monotonic_ns=obs.capture_monotonic_ns,
        clock_domain=obs.clock_domain,geometry_hash=obs.geometry_hash,
        calibration_id=obs.calibration_id,pose_version=obs.pose_version)
    data.update(changes)
    with sqlite3.connect(root.parent/'objects.sqlite3') as c:
        if create:
            c.execute('CREATE TABLE metadata(key TEXT,value TEXT)')
            c.execute('INSERT INTO metadata VALUES(?,?)',('config',json.dumps(dict(episode_id='e',clock_domain='clock',primary_sensor_id='rgbd'))))
            c.execute('CREATE TABLE batches(source_asset TEXT,data TEXT)')
        c.execute('INSERT INTO batches VALUES(?,?)',(ref,json.dumps(data)))
    return ref


def test_rgbd_projection_uses_full_k_and_measured_canonical_pose():
    # Pixel (2,1), skewed K, optical depth 2: camera (0.75, .5, 2),
    # then a 90deg canonical yaw and translation => (2.5,4.75,7).
    valid=np.zeros((2,3),bool);valid[1,2]=True
    pose=np.array([[0.,-1,0,3],[1,0,0,4],[0,0,1,5],[0,0,0,1]])
    obs=observation(depth_m=np.full((2,3),2,np.float32),valid_depth=valid,
        K=np.array([[2.,1.,1.],[0,2.,.5],[0,0,1.]]),T_world_camera=pose,
        rgb=np.full((2,3,3),[17,35,200],np.uint8))
    points,colors=project_rgbd(obs)
    assert np.allclose(points,[[2.5,4.75,7.]])
    assert colors.tolist()==[[17,35,200]]
    assert len(project_rgbd(replace(obs,valid_depth=np.zeros((2,3),bool)))[0])==0
    with pytest.raises(ValueError):project_rgbd(replace(obs,modality='depth_only'))


def test_cloud_reads_only_committed_hash_bound_source_and_is_idempotent(tmp_path):
    envelope,root,obs=fixture(tmp_path)
    reader=CommittedCloudReader(root);cloud=reader.read(envelope)
    assert len(cloud.points)==6 and cloud.last_source==obs.key
    assert cloud.last_capture_ns==100 and cloud.clock_domain=='clock'
    assert cloud.sources[0]['geometry_hash']==obs.geometry_hash
    assert cloud.sources[0]['calibration_id']==obs.calibration_id
    assert not cloud.points.flags.writeable and not cloud.colors.flags.writeable
    assert reader.read(envelope) is cloud
    assert len(reader._voxels)==6
    assert sqlite3.connect(root.parent/'objects.sqlite3').execute('SELECT count(*) FROM batches').fetchone()[0]==1


@pytest.mark.parametrize('mutation',['checksum','geometry','calibration','source','domain','symlink','path'])
def test_cloud_rejects_wrong_or_corrupt_provenance(tmp_path,mutation):
    envelope,root,obs=fixture(tmp_path)
    with sqlite3.connect(root.parent/'objects.sqlite3') as conn:
        ref,data=conn.execute('SELECT source_asset,data FROM batches').fetchone();data=json.loads(data)
        if mutation=='checksum':(root/ref).write_bytes(b'corrupt')
        if mutation=='geometry':data['geometry_hash']='a'*64
        if mutation=='calibration':data['calibration_id']='other'
        if mutation=='source':data['source']['frame_index']=99
        if mutation=='domain':data['clock_domain']='foreign'
        if mutation=='path':conn.execute('UPDATE batches SET source_asset=?',('../escape',))
        if mutation=='symlink':
            payload=(root/ref).read_bytes();(root/ref).unlink();outside=tmp_path/'outside';outside.write_bytes(payload);(root/ref).symlink_to(outside)
        conn.execute('UPDATE batches SET data=?',(json.dumps(data),))
    with pytest.raises((ValueError,OSError)):CommittedCloudReader(root).read(envelope)


def test_cloud_never_reads_future_commit_or_other_episode(tmp_path):
    envelope,root,obs=fixture(tmp_path)
    reader=CommittedCloudReader(root)
    assert reader.read(replace(envelope,published_monotonic_ns=99)) is None
    assert reader._row==0
    assert reader.read(envelope).last_capture_ns==100
    with sqlite3.connect(root.parent/'objects.sqlite3') as c:
        c.execute('UPDATE metadata SET value=?',(json.dumps(dict(episode_id='other',clock_domain='clock',primary_sensor_id='rgbd')),))
    with pytest.raises(ValueError):CommittedCloudReader(root).read(envelope)


def test_display_cloud_eviction_is_bounded_and_retains_origin_metadata(tmp_path,monkeypatch):
    import neusymnav.visualization.point_cloud as module
    envelope,root,obs=fixture(tmp_path)
    monkeypatch.setattr(module,'MAX_POINTS',5);monkeypatch.setattr(module,'MAX_SOURCES',1)
    reader=CommittedCloudReader(root);cloud=reader.read(envelope)
    assert len(cloud.points)==5
    shifted=np.eye(4);shifted[0,3]=2
    later=replace(obs,key=FrameKey('e','rgbd',1),capture_monotonic_ns=150,T_world_camera=shifted)
    add_db(root,later)
    cloud=reader.read(envelope)
    assert len(cloud.points)<=5 and len(cloud.sources)==1
    assert cloud.sources[0]['source']==dict(episode_id='e',sensor_id='rgbd',frame_index=1)
    assert np.all(cloud.points[:,0]>=1.5)


def test_background_reader_queue_and_shutdown_do_not_block_ui(tmp_path):
    envelope,root,_=fixture(tmp_path);reader=AsyncCloudReader(root)
    try:
        for _ in range(20):reader.offer(envelope)
        assert reader.pending.qsize()<=1
        deadline=time.monotonic()+3
        while reader.latest is None and time.monotonic()<deadline:time.sleep(.01)
        assert reader.latest is not None and reader.error is None
    finally:reader.close()
    assert not reader.thread.is_alive()


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_spatial_nodes_use_world_geometry_and_only_assigned_edges(app):
    envelope=make_publisher()[0].read_latest();original=tuple(envelope.hierarchy.edges)
    view=SpatialSceneWidget();view.set_envelope(envelope)
    assert np.array_equal(view.nodes[OID]['position'],envelope.hierarchy.nodes[OID].attributes['centroid'])
    assert np.allclose(view.nodes['r1']['position'][:2],[.5,.5])
    assigned={(e.source_id,e.target_id,e.kind) for e in envelope.hierarchy.edges if e.status=='assigned'}
    assert set(view.edges)<=assigned
    no_memberships=replace(envelope,hierarchy=replace(envelope.hierarchy,edges=tuple(e for e in original if e.kind!='in_region')))
    view.set_envelope(no_memberships)
    assert not any(kind=='in_region' for _,_,kind in view.edges)
    assert tuple(envelope.hierarchy.edges)==original
    view.close()


def test_default_spatial_tab_selection_zoom_and_camera_survive_publication(app):
    from neusymnav.visualization.desktop import DashboardWindow
    publisher,*_=make_publisher();window=DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:200)
    window.show();app.processEvents();view=window.spatial_view
    assert window.scene_tabs.tabText(0)=='3D Scene'
    window.select_object(ALIAS);assert view.selected==OID
    view.yaw=1.2;view.zoom=2.1
    view.set_envelope(publisher.read_latest())
    assert view.yaw==1.2 and view.zoom==2.1
    view.resize(900,400);view.show();app.processEvents();view.grab()
    point=view._screen_nodes[OID].toPoint()
    received=[];view.object_selected.connect(received.append)
    QtTest.QTest.mouseClick(view,QtCore.Qt.LeftButton,pos=point)
    assert received==[OID]
    assert window._selected_object_id==OID
    view.reset_view();assert view.zoom==1.
    window.close()
