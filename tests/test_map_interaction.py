"""Exercise Qt map input and shared world transform across live map updates."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
import pytest
from PyQt5 import QtCore,QtGui,QtWidgets,QtTest
from neusymnav.visualization.desktop import MapWidget
from test_display_snapshot import make_publisher

@pytest.fixture
def view():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    env=make_publisher()[0].read_latest();nav=env.sources.nav
    nav=replace(nav,origin_xy=(-5.,-5.),resolution_m=.5,states=np.zeros((20,20),np.int8),floor_support=np.ones((20,20),bool),clearance=np.ones((20,20)))
    env=replace(env,sources=replace(env.sources,nav=nav))
    widget=MapWidget();widget.resize(520,420);widget.set_snapshot(nav,env);widget.show();app.processEvents()
    yield widget,app,env
    widget.close()

def wheel(widget,point,steps=1):
    event=QtGui.QWheelEvent(QtCore.QPointF(point),QtCore.QPointF(widget.mapToGlobal(point)),QtCore.QPoint(),QtCore.QPoint(0,120*steps),QtCore.Qt.NoButton,QtCore.Qt.NoModifier,QtCore.Qt.NoScrollPhase,False)
    QtWidgets.QApplication.sendEvent(widget,event)
    QtWidgets.QApplication.processEvents()

def drag(widget,start,end):
    QtTest.QTest.mousePress(widget,QtCore.Qt.LeftButton,pos=start)
    event=QtGui.QMouseEvent(QtCore.QEvent.MouseMove,QtCore.QPointF(end),QtCore.Qt.NoButton,QtCore.Qt.LeftButton,QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(widget,event)
    QtTest.QTest.mouseRelease(widget,QtCore.Qt.LeftButton,pos=end)
    QtWidgets.QApplication.processEvents()

def test_wheel_zooms_at_cursor_and_drag_moves_world(view):
    widget,app,_=view;xy=(1.,1.);anchor=widget._world_to_pixel(xy);point=anchor.toPoint()
    before=(widget._world_to_pixel((1.,0.))-widget._world_to_pixel((0.,0.))).manhattanLength()
    wheel(widget,point,3)
    after=(widget._world_to_pixel((1.,0.))-widget._world_to_pixel((0.,0.))).manhattanLength()
    assert after>before*1.2
    assert (widget._world_to_pixel(xy)-anchor).manhattanLength()<2
    old=widget._world_to_pixel((0.,0.));drag(widget,QtCore.QPoint(250,240),QtCore.QPoint(290,265))
    assert np.allclose([widget._world_to_pixel((0.,0.)).x()-old.x(),widget._world_to_pixel((0.,0.)).y()-old.y()],[40,25])

def test_manual_world_view_survives_moving_origin_and_resize_and_fit_restores(view):
    widget,app,env=view;wheel(widget,QtCore.QPoint(260,210),3)
    drag(widget,QtCore.QPoint(250,240),QtCore.QPoint(280,260));before=widget._world_to_pixel((0.,0.))
    nav=replace(env.sources.nav,revision=2,source=replace(env.sources.nav.source,frame_index=2),origin_xy=(-4.,-3.))
    widget.set_snapshot(nav,SimpleNamespace(sources=SimpleNamespace(nav=nav,robot=None),hierarchy=env.hierarchy));app.processEvents()
    assert (widget._world_to_pixel((0.,0.))-before).manhattanLength()<1e-6
    unit=(widget._world_to_pixel((1.,0.))-widget._world_to_pixel((0.,0.))).x()
    widget.resize(620,520);app.processEvents()
    assert (widget._world_to_pixel((1.,0.))-widget._world_to_pixel((0.,0.))).x()==pytest.approx(unit)
    QtTest.QTest.mouseDClick(widget,QtCore.Qt.LeftButton,pos=QtCore.QPoint(300,260));app.processEvents()
    map_center=(nav.origin_xy[0]+5,nav.origin_xy[1]+5)
    assert (widget._world_to_pixel(map_center)-QtCore.QRectF(widget.rect().adjusted(8,8,-8,-8)).center()).manhattanLength()<1e-6

def test_zoomed_raster_and_outlines_are_clipped_to_map_viewport(view):
    widget,app,_=view;wheel(widget,QtCore.QPoint(260,210),12)
    image=widget.grab().toImage()
    # Neither zoomed raster nor world overlays may fill the widget's outer margin.
    for x,y in [(2,200),(517,200),(250,417)]:
        assert image.pixelColor(x,y).getRgb()[:3]==(12,20,33)

def test_new_episode_resets_manual_view(view):
    widget,app,env=view;wheel(widget,QtCore.QPoint(260,210),3)
    nav=replace(env.sources.nav,episode_id='new',source=replace(env.sources.nav.source,episode_id='new'))
    widget.set_snapshot(nav,SimpleNamespace(sources=SimpleNamespace(nav=nav,robot=None),hierarchy=SimpleNamespace(nodes={},map_revision=nav.revision)))
    app.processEvents()
    center=widget._world_to_pixel((0.,0.))
    assert (center-QtCore.QRectF(widget.rect().adjusted(8,8,-8,-8)).center()).manhattanLength()<1e-6
    expected=min(widget.width()-16,widget.height()-16)/10
    assert (widget._world_to_pixel((1.,0.))-center).x()==pytest.approx(expected)

def test_zoomed_robot_goal_and_occupied_cell_share_raster_transform(view):
    from neusymnav.visualization.navigation_overlay import NavigationOverlay
    from neusymnav.visualization.robot_overlay import RobotSample,RobotTrack
    widget,app,env=view;nav=env.sources.nav
    states=nav.states.copy();states[10,6]=100
    nav=replace(nav,states=states)
    robot=RobotTrack((RobotSample(nav.source,nav.capture_monotonic_ns,nav.clock_domain,0,(0.,0.),0.),))
    plan=NavigationOverlay(nav.source,nav.capture_monotonic_ns,nav.clock_domain,nav.revision,
        nav.capture_monotonic_ns,(),(),'goal',(2.,0.),((0.,0.),(2.,0.)),'moving',False)
    env=replace(env,sources=replace(env.sources,nav=nav,robot=robot,navigation=plan))
    widget._now_ns=nav.capture_monotonic_ns;widget._clock_domain=nav.clock_domain
    widget.set_snapshot(nav,env);app.processEvents()
    wheel(widget,QtCore.QPoint(260,210),3)
    drag(widget,QtCore.QPoint(250,240),QtCore.QPoint(270,250))
    image=widget.grab().toImage()
    def color_at(xy):
        p=widget._world_to_pixel(xy).toPoint()
        return image.pixelColor(p).getRgb()[:3]
    assert color_at((0.,0.))==(105,186,255)
    assert color_at((2.,0.))==(255,97,214)
    assert color_at((-1.75,.25))==(245,91,79)

def test_robot_world_label_stays_inside_map_viewport(view):
    from neusymnav.visualization.robot_overlay import RobotSample,RobotTrack
    widget,app,env=view;nav=env.sources.nav
    robot=RobotTrack((RobotSample(nav.source,nav.capture_monotonic_ns,nav.clock_domain,0,(4.99,0.),0.),))
    widget._now_ns=nav.capture_monotonic_ns;widget._clock_domain=nav.clock_domain
    widget.set_snapshot(nav,replace(env,sources=replace(env.sources,robot=robot)));app.processEvents()
    image=widget.grab().toImage()
    assert all(image.pixelColor(x,y).getRgb()[:3]==(12,20,33) for x in range(513,520) for y in range(175,225))
