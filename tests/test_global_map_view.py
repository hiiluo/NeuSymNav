"""Full accumulated map rather than a zoomed moving navigation window."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
import json
import numpy as np
import pytest
from PyQt5 import QtCore,QtWidgets
from neusymnav.mapping.overview import MapOverview
from neusymnav.visualization.desktop import MapWidget
from neusymnav.visualization.publisher import DisplayPublisher
from neusymnav.runtime.ui_transport import encode_publication,decode_publication
from test_display_snapshot import make_publisher


def envelope():
    env=make_publisher()[0].read_latest();nav=env.sources.nav
    states=np.full((20,100),-1,np.int8);states[4:8,2:8]=0;states[4:8,85:95]=100
    overview=MapOverview(nav,(-10.,-2.),nav.resolution_m,states)
    metrics=replace(env.metrics,source_age_ns={**env.metrics.source_age_ns,'live_map':100,'overview':100})
    return replace(env,metrics=metrics,sources=replace(env.sources,live_nav=nav,overview=overview))


def test_global_map_transport_and_old_wire_optional_default():
    env=envelope();wire=encode_publication(env);decoded=decode_publication(wire)
    assert np.array_equal(decoded.sources.overview.states,env.sources.overview.states)
    assert decoded.sources.overview.source_nav.source==env.sources.live_nav.source
    data=json.loads(wire);del data['payload']['fields']['sources']['fields']['overview']
    assert decode_publication(json.dumps(data).encode()).sources.overview is None


def test_global_source_must_not_come_from_future_local_revision():
    env=envelope();future=replace(env.sources.live_nav,revision=99)
    with pytest.raises(ValueError,match='overview'):
        replace(env,sources=replace(env.sources,overview=replace(env.sources.overview,source_nav=future)))


def test_whole_map_fit_covers_both_distant_areas_and_manual_focus_survives_robot_move():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);env=envelope()
    widget=MapWidget();widget.resize(600,400);widget.set_snapshot(env.sources.live_nav,env);widget.show();app.processEvents()
    overview=env.sources.overview
    a=(overview.origin_xy[0]+3*overview.resolution_m,overview.origin_xy[1]+5*overview.resolution_m)
    b=(overview.origin_xy[0]+90*overview.resolution_m,a[1])
    assert widget._viewport_rect().contains(widget._world_to_pixel(a))
    assert widget._viewport_rect().contains(widget._world_to_pixel(b))
    assert widget._map_image.width()==100
    widget._manual_camera();widget._view_center=QtCore.QPointF(*a);widget._layout_map()
    before=widget._world_to_pixel(a)
    nav=replace(env.sources.live_nav,revision=2,source=replace(env.sources.live_nav.source,frame_index=2),capture_monotonic_ns=101,origin_xy=(10.,0.))
    new=replace(env,sources=replace(env.sources,live_nav=nav))
    widget.set_snapshot(nav,new);app.processEvents()
    assert (widget._world_to_pixel(a)-before).manhattanLength()<1e-6
    assert widget._map_image.width()==100
    widget.fit_view();app.processEvents()
    assert widget._viewport_rect().contains(widget._world_to_pixel(b))
    assert 'Accumulated' in widget._map_caption()
    widget.close()


def test_global_provider_publishes_all_history_before_graph_without_local_window_stitching(tmp_path):
    from neusymnav.mapping.overview import OverviewTiles
    from test_ui_publication_cadence import ui_process
    from test_live_map_publication import wait_envelope,live
    _,_,metrics,*_=make_publisher();nav=live(metrics['sources'].nav)
    values={(0,0):np.zeros((2,2),np.int8),(0,50):np.full((2,2),100,np.int8)}
    tiles=OverviewTiles(nav,(0.,0.),nav.resolution_m,2,values)
    with ui_process(tmp_path,live_nav_provider=lambda:nav,overview_provider=lambda:tiles,publish_hz=5) as ui:
        env=wait_envelope(ui,lambda e:e.sources.overview is not None)
        overview=env.sources.overview
        assert overview.states.shape[1]>=102
        assert overview.states[0,0]==0 and overview.states[0,-1]==100
        assert np.all(overview.states[:,2:100]==-1)
        assert env.hierarchy.revision==0 and env.sources.nav is None
        assert overview.source_nav.revision==env.sources.live_nav.revision
        assert 'overview' in env.metrics.source_age_ns


def test_focusing_robot_on_large_overview_wheel_up_never_zooms_out():
    from test_map_interaction import wheel
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([]);env=envelope()
    global_map=MapOverview(env.sources.live_nav,(-10.,-2.),env.sources.live_nav.resolution_m*1024,np.zeros((20,100),np.int8))
    env=replace(env,sources=replace(env.sources,overview=global_map))
    widget=MapWidget();widget.resize(600,400);widget.set_snapshot(env.sources.live_nav,env);widget.show();app.processEvents()
    widget.focus_robot();app.processEvents()
    before=(widget._world_to_pixel((1.,0.))-widget._world_to_pixel((0.,0.))).x()
    wheel(widget,widget.rect().center(),1)
    after=(widget._world_to_pixel((1.,0.))-widget._world_to_pixel((0.,0.))).x()
    assert after>before
    widget.close()
