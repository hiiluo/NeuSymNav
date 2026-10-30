"""User gestures, splitter resizing and detached graph lifecycle."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import math
from PyQt5 import QtCore,QtGui,QtTest,QtWidgets
import pytest
from test_display_snapshot import make_publisher,OID
from neusymnav.visualization.desktop import DashboardWindow


@pytest.fixture
def window():
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher,*_=make_publisher()
    w=DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:200)
    w.setWindowState(QtCore.Qt.WindowNoState);w.resize(1500,1050);w.show();app.processEvents()
    yield app,w,publisher
    w.close();app.processEvents()


def drag(widget,start,end,button=QtCore.Qt.LeftButton,mods=QtCore.Qt.NoModifier):
    for kind,pos,changed,buttons in (
        (QtCore.QEvent.MouseButtonPress,start,button,button),
        (QtCore.QEvent.MouseMove,end,QtCore.Qt.NoButton,button),
        (QtCore.QEvent.MouseButtonRelease,end,button,QtCore.Qt.NoButton),
    ):
        local=QtCore.QPointF(pos);global_pos=QtCore.QPointF(widget.mapToGlobal(pos))
        event=QtGui.QMouseEvent(kind,local,local,global_pos,changed,buttons,mods)
        QtWidgets.QApplication.sendEvent(widget,event)
    QtWidgets.QApplication.processEvents()


def wheel(widget,delta,mods=QtCore.Qt.NoModifier):
    p=QtCore.QPointF(60,60)
    event=QtGui.QWheelEvent(p,QtCore.QPointF(widget.mapToGlobal(p.toPoint())),
        QtCore.QPoint(),QtCore.QPoint(0,delta),QtCore.Qt.NoButton,mods,QtCore.Qt.NoScrollPhase,False)
    QtWidgets.QApplication.sendEvent(widget,event)


def test_visible_splitters_resize_graph_height_and_evidence_width(window):
    app,w,_=window
    before=w.workspace_split.sizes()
    handle=w.workspace_split.handle(1);p=handle.rect().center()
    drag(handle,p,p-QtCore.QPoint(0,110))
    after=w.workspace_split.sizes()
    assert after[1]>before[1]+30,(before,after)
    before=w.graph_split.sizes();handle=w.graph_split.handle(1);p=handle.rect().center()
    drag(handle,p,p+QtCore.QPoint(100,0))
    after=w.graph_split.sizes()
    assert after[0]>before[0]+30,(before,after)
    assert w.workspace_split.isCollapsible(0)
    assert w.workspace_split.handleWidth()>=10 and w.graph_split.handleWidth()>=10


def test_popup_can_resize_then_dock_without_resetting_data_or_camera(window):
    app,w,publisher=window;v=w.spatial_view
    w.select_object(OID);v.zoom=2.;v.yaw=1.2
    envelope=w._envelope
    QtTest.QTest.mouseClick(w.graph_controls['Pop out'],QtCore.Qt.LeftButton);app.processEvents()
    popup=w._graph_popup
    assert popup is not None and popup.isVisible()
    assert w.graph_panel.window() is popup and w.workspace_split.count()==1
    popup.setWindowState(QtCore.Qt.WindowNoState);popup.resize(800,600);app.processEvents()
    before=v.width();popup.resize(1200,800);app.processEvents()
    assert v.width()>before
    assert v.zoom==2. and v.yaw==1.2
    w.refresh();assert w._envelope is envelope and v.selected==OID
    QtTest.QTest.mouseClick(w.graph_controls['Pop out'],QtCore.Qt.LeftButton);app.processEvents()
    assert w._graph_popup is None and w.workspace_split.count()==2
    assert w.graph_panel.parent() is w.workspace_split
    assert v.zoom==2. and v.yaw==1.2 and v.selected==OID


def test_main_window_close_also_closes_floating_graph(window):
    app,w,_=window;w._toggle_graph_popup();app.processEvents()
    assert w._graph_popup is not None
    w.close();app.processEvents()
    assert w._graph_popup is None
    assert not any(x.isVisible() and x.windowTitle()=='NeuSymNav / Graph debug' for x in app.topLevelWidgets())


def test_spatial_drag_zoom_orbit_pan_and_wheel_survive_new_publication(window):
    app,w,p=window;v=w.spatial_view
    angle=(v.yaw,v.pitch)
    drag(v,QtCore.QPoint(60,100),QtCore.QPoint(60,50),mods=QtCore.Qt.ShiftModifier)
    assert v.zoom>1 and (v.yaw,v.pitch)==angle
    zoom=v.zoom
    wheel(v,-120);assert v.zoom<zoom
    drag(v,QtCore.QPoint(60,60),QtCore.QPoint(90,80),button=QtCore.Qt.RightButton)
    assert list(v.pan)==[30,20]
    drag(v,QtCore.QPoint(60,250),QtCore.QPoint(110,20))
    assert v.yaw>angle[0] and v.pitch<0
    state=(v.zoom,v.yaw,v.pitch,tuple(v.pan))
    v.set_envelope(p.read_latest());assert (v.zoom,v.yaw,v.pitch,tuple(v.pan))==state
    w.graph_controls['+'].click();assert v.zoom>state[0]
    w.graph_controls['Top'].click();assert v.yaw==0 and v.pitch==math.pi/2
    w.graph_controls['Fit'].click();assert v.zoom==1 and list(v.pan)==[0,0]


def test_expand_toggle_returns_to_all_panels(window):
    app,w,_=window
    w.graph_controls['Expand'].click();app.processEvents()
    assert w.focus_selector.currentText()=='SCENE GRAPH' and not w.sensor_row.isVisible()
    w.graph_controls['Expand'].click();app.processEvents()
    assert w.focus_selector.currentText()=='All panels' and w.sensor_row.isVisible()


def test_2d_layout_zoom_and_rotation_persist_across_refresh_and_selection(window):
    app,w,p=window;v=w.graph_view;w.scene_tabs.setCurrentWidget(v);app.processEvents()
    old=v.transform().m11();wheel(v.viewport(),120)
    assert v.transform().m11()>old
    wheel(v.viewport(),120,QtCore.Qt.ControlModifier)
    assert abs(v.transform().m12())>0
    transform=QtGui.QTransform(v.transform())
    v.set_envelope(p.read_latest());v.select_object(OID);app.processEvents()
    assert v.transform()==transform
    v.resize(v.width()+50,v.height()+20);app.processEvents()
    assert v.transform()==transform
    v.fit_view();assert abs(v.transform().m12())<1e-9 and not v._manual_view
