"""Display-only height cutaway relative to the pinned floor datum."""
from dataclasses import replace
import numpy as np
import pytest
from PyQt5 import QtWidgets
from test_display_snapshot import make_publisher
from neusymnav.contracts import FrameKey
from neusymnav.visualization.point_cloud import CloudSnapshot
from neusymnav.visualization.spatial_scene import SpatialSceneWidget


@pytest.fixture(scope='module')
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def scene(floor=0.):
    env=make_publisher()[0].read_latest()
    env=replace(env,sources=replace(env.sources,nav=replace(env.sources.nav,floor_z_m=floor)))
    heights=np.array([0,.05,.1,.5,1.2,2.,2.5,3.],np.float32)
    points=np.column_stack((np.arange(len(heights)),np.zeros(len(heights)),heights+floor)).astype(np.float32)
    colors=np.repeat(np.arange(len(heights),dtype=np.uint8)[:,None],3,axis=1)
    cloud=CloudSnapshot('e','clock',points,colors,(),FrameKey('e','rgbd',0),100,1)
    view=SpatialSceneWidget();view.set_envelope(env);view.set_cloud(cloud)
    return env,cloud,view


@pytest.mark.parametrize('floor',[0.,3.,-1.6])
def test_cutaway_uses_calibrated_floor_and_keeps_matching_measured_colors(app,floor):
    _,cloud,view=scene(floor)
    points,colors=view.visible_cloud()
    assert points[:,0].tolist()==[0,1,2,3,4,5]
    assert colors[:,0].tolist()==[0,1,2,3,4,5]
    assert len(cloud.points)==8 and cloud.last_capture_ns==100
    assert not points.flags.writeable and not colors.flags.writeable
    view.close()


def test_cutaway_is_reversible_and_does_not_modify_graph_or_camera(app):
    env,cloud,view=scene()
    original_points=cloud.points.copy();nodes=set(view.nodes);edges=view.edges
    view.yaw=1.1;view.zoom=2.;view.pan[:]=[20,30]
    assert len(view.visible_cloud()[0])==6
    view.configure_height_filter(False)
    assert np.array_equal(view.visible_cloud()[0],original_points)
    view.configure_height_filter(True,.1,1.5)
    assert view.visible_cloud()[0][:,0].tolist()==[3,4]
    assert np.array_equal(cloud.points,original_points)
    assert set(view.nodes)==nodes and view.edges==edges
    assert view.yaw==1.1 and view.zoom==2. and list(view.pan)==[20,30]
    view.close()


def test_no_floor_datum_does_not_guess_zero_or_drop_geometry(app):
    env,cloud,view=scene(3.)
    nodes={key:(replace(node,attributes={k:v for k,v in node.attributes.items() if k!='floor_z_m'}) if node.kind=='floor' else node)
           for key,node in env.hierarchy.nodes.items()}
    env=replace(env,hierarchy=replace(env.hierarchy,nodes=nodes),sources=replace(env.sources,nav=None))
    view.set_envelope(env)
    assert view._floor_elevation() is None
    assert len(view.visible_cloud()[0])==len(cloud.points)
    view.close()


def test_cloud_menu_changes_only_display_filter(app):
    from neusymnav.visualization.desktop import DashboardWindow
    env,cloud,unused=scene();unused.close()
    window=DashboardWindow(lambda:env,clock_domain='clock',now_ns=lambda:200)
    window.spatial_view.set_cloud(cloud)
    assert window.cloud_cutaway_action.isChecked()
    assert window.cloud_lower_spin.value()==0
    assert len(window.spatial_view.visible_cloud()[0])==6
    window.cloud_upper_spin.setValue(1.5)
    assert window.spatial_view.visible_cloud()[0][:,0].tolist()==[0,1,2,3,4]
    window.cloud_cutaway_action.setChecked(False)
    assert len(window.spatial_view.visible_cloud()[0])==8
    assert window._envelope is env
    window.close()


@pytest.mark.parametrize('low,high',[(-1,2),(.2,.1),(0,11),(0,float('nan'))])
def test_bad_height_ranges_rejected(app,low,high):
    _,_,view=scene()
    with pytest.raises(ValueError):view.configure_height_filter(True,low,high)
    view.close()
