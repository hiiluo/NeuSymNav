"""Independent oracles from review of measured-geometry rendering."""
from dataclasses import replace
import numpy as np
import pytest
from PyQt5 import QtCore,QtWidgets
from test_spatial_scene import fixture,add_db
from test_display_snapshot import make_publisher
from neusymnav.contracts import FrameKey
from neusymnav.visualization.point_cloud import CommittedCloudReader,CloudSnapshot
from neusymnav.visualization.spatial_scene import SpatialSceneWidget


def view():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w=SpatialSceneWidget();w.resize(200,200)
    return app,w


def test_canonical_positive_z_projects_upward():
    app,w=view();area=QtCore.QRect(0,0,200,200)
    projected,_=w._project(np.array([[0,0,0],[0,0,1]]),area,np.zeros(3),20)
    assert projected[1,1]<projected[0,1]
    w.close()


def test_changed_clock_context_clears_old_cloud_and_camera():
    app,w=view();envelope=make_publisher()[0].read_latest();w.set_envelope(envelope)
    cloud=CloudSnapshot('e','clock',np.array([[0,0,0.]],np.float32),np.array([[1,2,3]],np.uint8),(),FrameKey('e','rgbd',0),100,1)
    w.set_cloud(cloud);w.zoom=2
    # Change all clock-bearing optional sources out of the envelope together.
    changed=replace(envelope,clock_domain='other',sources=replace(envelope.sources,nav=replace(envelope.sources.nav,clock_domain='other'),live_nav=None,rgb=None,best_views=(),observation=None,navigation=None,robot=None))
    w.set_envelope(changed)
    assert w.cloud is None and w.zoom==1.
    w.set_cloud(cloud);assert w.cloud is None
    w.close()


@pytest.mark.parametrize('dx,dy',[(1,0),(0,1),(1,1),(-1,0),(0,-1),(-1,-1),(1,-1),(-1,1)])
def test_nearest_splat_wins_across_all_offsets(dx,dy):
    app,w=view();w.yaw=0;w.pitch=0;w._episode='e'
    # Larger camera depth is nearer. Eye is above negative Y: far red (0,0,0),
    # near green (1,-1,0),
    # overlap at pixel(x+1,y+1) after the two-by-two splat.
    w.cloud=CloudSnapshot('e','clock',np.array([[0,0,0],[dx,-1,-dy]],np.float32),
        np.array([[255,0,0],[0,255,0]],np.uint8),(),FrameKey('e','rgbd',0),100,1)
    area=QtCore.QRect(0,0,200,200)
    image=w._cloud_image(area,np.zeros(3),1.)
    pos,_=w._project([[0,0,0]],area,np.zeros(3),1.)
    x,y=np.rint(pos[0]).astype(int)+[max(0,dx),max(0,dy)]
    assert image.pixelColor(int(x),int(y)).getRgb()[:3]==(0,255,0)
    w.close()


def test_empty_geometry_frame_cannot_refresh_age_of_old_cloud(tmp_path):
    envelope,root,obs=fixture(tmp_path);reader=CommittedCloudReader(root);before=reader.read(envelope)
    empty=replace(obs,key=FrameKey('e','rgbd',1),capture_monotonic_ns=150,valid_depth=np.zeros(obs.depth_m.shape,bool))
    add_db(root,empty)
    after=reader.read(envelope)
    assert after is before
    assert after.last_source==obs.key and after.last_capture_ns==100
    assert reader._row==2
