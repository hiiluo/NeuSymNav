"""CPU/offscreen checks of world-space navigation annotations on the pinned raster."""
from dataclasses import replace
import os
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import numpy as np
import pytest
from PyQt5 import QtGui, QtWidgets

from neusymnav.visualization.desktop import MapWidget
from neusymnav.visualization.navigation_overlay import NavigationOverlay
from test_display_snapshot import make_publisher


@pytest.fixture
def view():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = MapWidget()
    widget.resize(520, 520)
    widget._clock_domain = 'clock'
    widget._now_ns = 100_000_100
    yield widget, app
    widget.close()


def show(view, **changes):
    widget, app = view
    envelope = make_publisher()[0].read_latest()
    nav = replace(envelope.sources.nav, origin_xy=(-5., -5.), resolution_m=.5,
                  states=np.full((20, 20), -1, dtype=np.int8),
                  floor_support=np.zeros((20, 20), dtype=bool),
                  clearance=np.zeros((20, 20), dtype=float))
    values = dict(source=nav.source, capture_monotonic_ns=100, clock_domain='clock',
                  map_revision=nav.revision + 7, computed_monotonic_ns=150,
                  frontier_points=((-2.5, 1.5),), viewpoints=((2.5, 1.5),),
                  goal_id='frontier-1', goal_xy=(0., -.5), path=((-3., -2.), (0., -.5)),
                  status='moving', truncated=False)
    values.update(changes)
    overlay = NavigationOverlay(**values)
    sources = SimpleNamespace(robot=None, navigation=overlay)
    widget.set_snapshot(nav, SimpleNamespace(sources=sources, hierarchy=SimpleNamespace(nodes={})))
    widget.show()
    app.processEvents()
    return widget.grab().toImage(), overlay


def color_near(image, point, rgb, radius=5):
    return any(image.pixelColor(x, y).getRgb()[:3] == rgb
               for x in range(max(0, round(point.x()) - radius), min(image.width(), round(point.x()) + radius + 1))
               for y in range(max(0, round(point.y()) - radius), min(image.height(), round(point.y()) + radius + 1)))


def test_frontier_viewpoint_and_goal_use_display_map_world_transform(view):
    image, overlay = show(view)
    widget, _ = view
    assert widget._navigation is overlay
    assert color_near(image, widget._world_to_pixel((-2.5, 1.5)), (255, 218, 83))
    assert color_near(image, widget._world_to_pixel((2.5, 1.5)), (90, 220, 232))
    assert color_near(image, widget._world_to_pixel((0., -.5)), (255, 97, 214))
    assert widget._world_to_pixel((-2., 1.)).x() > widget._world_to_pixel((-3., 1.)).x()
    assert widget._world_to_pixel((-2., 1.)).y() < widget._world_to_pixel((-2., 0.)).y()
    assert f'Plan revision {overlay.map_revision}' in widget._navigation_caption()
    assert 'moving' in widget._navigation_caption()


def test_none_goal_clears_previous_active_goal(view):
    show(view)
    image, _ = show(view, goal_id=None, goal_xy=None, path=(), status='paused')
    widget, _ = view
    assert not color_near(image, widget._world_to_pixel((0., -.5)), (255, 97, 214))
    assert 'no active goal' in widget._navigation_caption()


def test_route_is_drawn_and_robot_stays_above_navigation(view):
    image, _ = show(view, frontier_points=((.5, .5),), viewpoints=(),
                    goal_xy=(.5, .5), path=((-3., -2.), (.5, .5)))
    widget, app = view
    point = widget._world_to_pixel((-1.25, -.75))
    # Thin antialiased route blends with the unknown-cell palette.
    colors = [image.pixelColor(x, y) for x in range(round(point.x())-8, round(point.x())+9)
              for y in range(round(point.y())-8, round(point.y())+9)]
    assert any(c.red() > 150 and c.blue() > 130 and c.green() < 110 for c in colors)
    from neusymnav.visualization.robot_overlay import RobotSample, RobotTrack
    nav = widget._nav
    widget._robot = RobotTrack((RobotSample(nav.source, 100, 'clock', 0, (.5, .5), 0.),))
    widget.update()
    app.processEvents()
    point = widget._world_to_pixel((.5, .5))
    assert widget.grab().toImage().pixelColor(round(point.x()), round(point.y())).getRgb()[:3] == (105, 186, 255)


@pytest.mark.parametrize('changes,now', [({}, 300_000_101), ({'clock_domain': 'other'}, 1000), ({}, 99)])
def test_stale_goal_is_gray_and_explicitly_last_goal(view, changes, now):
    view[0]._now_ns = now
    image, _ = show(view, **changes)
    widget, _ = view
    assert not color_near(image, widget._world_to_pixel((0., -.5)), (255, 97, 214))
    assert color_near(image, widget._world_to_pixel((0., -.5)), (164, 181, 202))
    assert 'STALE' in widget._navigation_caption()
    assert 'LAST GOAL' in widget._navigation_caption()


def test_annotations_outside_negative_origin_raster_are_clipped(view):
    image, _ = show(view, frontier_points=((-100., 100.), (100., -100.)),
                    viewpoints=((-100., -100.),), goal_xy=(100., 100.),
                    path=((-100., 0.), (100., 0.)))
    widget, _ = view
    # A route crossing the map must not paint the margin on either side.
    y = round(widget._world_to_pixel((0., 0.)).y())
    for x in (0, 3, image.width() - 1, image.width() - 4):
        assert image.pixelColor(x, y).getRgb()[:3] == (12, 20, 33)


def test_missing_optional_overlay_remains_compatible(view):
    widget, app = view
    envelope = make_publisher()[0].read_latest()
    widget.set_snapshot(envelope.sources.nav, SimpleNamespace(
        sources=SimpleNamespace(robot=None), hierarchy=SimpleNamespace(nodes={})))
    widget.show()
    app.processEvents()
    assert widget._navigation is None
    assert 'unavailable' in widget._navigation_caption()


def test_derived_camera_projection_is_identified_in_legend(view):
    from neusymnav.visualization.robot_overlay import RobotTrailBuffer
    from test_robot_map_overlay import pair, nav_for
    show(view)
    widget, _ = view
    buffer = RobotTrailBuffer()
    rgb, nav, pose = pair(0, 100)
    buffer.observe(rgb, nav, pose)
    _, nav, pose = pair(1, 200)
    buffer.observe(None, nav, pose)
    widget._robot = buffer.for_nav(nav_for(nav))

    class RecordingPainter(QtGui.QPainter):
        def drawText(self, *args):
            self.labels.append(args[-1])
            return super().drawText(*args)

    image = QtGui.QImage(520, 520, QtGui.QImage.Format_RGB32)
    painter = RecordingPainter(image)
    painter.labels = []
    widget._draw_robot(painter)
    painter.end()
    assert any('calibrated projection' in label for label in painter.labels)
