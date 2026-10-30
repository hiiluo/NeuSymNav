"""Read-only PyQt5 desktop viewer, intended to run as a separate UI process.

The module's publisher and contracts are Qt-free. A future runtime launcher
can connect ``publication_reader`` and ``UiControlClient`` through its IPC
adapter without importing Qt in the control process.
"""
from __future__ import annotations

import argparse
import math
import sys
from collections.abc import Callable
from time import monotonic_ns
from typing import Sequence

import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from ..contracts import NavSnapshot
from .hierarchy_view import hierarchy_rows, resolve_object_selection, resolve_verification
from .scene_graph import SceneGraphWidget
from .spatial_scene import SpatialSceneWidget
from .publisher import DisplayEnvelope, DisplayPublisher, UiCommandStatus, UiControlClient


def _qimage_rgb(pixels: np.ndarray) -> QtGui.QImage:
    height, width = pixels.shape[:2]
    return QtGui.QImage(pixels.data, width, height, int(pixels.strides[0]), QtGui.QImage.Format_RGB888).copy()


class MapWidget(QtWidgets.QWidget):
    """Render current display occupancy with separately pinned room outlines."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(240, 220)
        self._nav: NavSnapshot | None = None
        self._overview = None
        self._raster_source = None
        self._map_image: QtGui.QImage | None = None
        self._map_revision: int | None = None
        self._regions: tuple[np.ndarray, ...] = ()
        self._stale = False
        self._robot = None
        self._navigation = None
        self._now_ns = 0
        self._clock_domain = None
        self._draw_rect = QtCore.QRectF()
        self._map_context = None
        self._view_center = None  # manual world XY; independent of map origin
        self._view_scale = None   # manual pixels/metre; None means auto-fit
        self._drag_pos = None
        self.setToolTip('Wheel: zoom at cursor · Drag: pan · Double-click: fit entire accumulated map')
        self.status_text = "Map unavailable · no NavSnapshot"

    def set_snapshot(self, nav: NavSnapshot | None, envelope: DisplayEnvelope) -> None:
        if nav is not None and (nav.episode_id, nav.clock_domain) != self._map_context:
            self._map_context = (nav.episode_id, nav.clock_domain)
            self.fit_view()
        self._nav = nav
        self._overview = getattr(envelope.sources, 'overview', None) if nav is not None else None
        raster = self._overview if self._overview is not None else nav
        if raster is not self._raster_source:
            self._raster_source = raster
            self._map_revision = None if nav is None else nav.revision
            self._map_image = None if raster is None else self._raster_image(raster)
        self.status_text = "Map unavailable · no NavSnapshot" if nav is None else f"Map available · nav revision {nav.revision}"
        regions = []
        pinned = envelope.sources.nav
        stale = nav is not None and (nav.revision != envelope.hierarchy.map_revision
                    or (pinned is not None and (nav.source, nav.capture_monotonic_ns, nav.clock_domain)
                        != (pinned.source, pinned.capture_monotonic_ns, pinned.clock_domain)))
        self._room_map_revision = envelope.hierarchy.map_revision
        for node in envelope.hierarchy.nodes.values():
            if node.kind == "region":
                stale = stale or bool(node.attributes.get("stale", False))
                polygon = node.attributes.get("polygon")
                if isinstance(polygon, np.ndarray):
                    regions.append(polygon)
        robot = envelope.sources.robot
        if robot is not None and nav is not None:
            last = robot.samples[-1]
            if (last.source, last.capture_monotonic_ns, last.clock_domain) != (
                    nav.source, nav.capture_monotonic_ns, nav.clock_domain):
                robot = None
        self._robot = robot if nav is not None else None
        self._navigation = getattr(envelope.sources, "navigation", None)
        self._regions = tuple(regions)
        self._stale = stale
        self._layout_map()
        self.update()

    def _viewport_rect(self):
        return QtCore.QRectF(self.rect().adjusted(8, 8, -8, -8))

    def _fit_scale(self):
        nav = self._raster_source
        target = self._viewport_rect()
        return min(target.width()/nav.states.shape[1], target.height()/nav.states.shape[0])/nav.resolution_m

    def _layout_map(self):
        if self._nav is None:
            self._draw_rect = QtCore.QRectF()
            return
        nav = self._raster_source
        width, height = np.array(nav.states.shape[::-1])*nav.resolution_m
        center = (QtCore.QPointF(nav.origin_xy[0]+width/2, nav.origin_xy[1]+height/2)
                  if self._view_center is None else self._view_center)
        scale = self._fit_scale() if self._view_scale is None else self._view_scale
        screen = self._viewport_rect().center()
        self._draw_rect = QtCore.QRectF(screen.x()+(nav.origin_xy[0]-center.x())*scale,
            screen.y()-(nav.origin_xy[1]+height-center.y())*scale, width*scale, height*scale)

    def fit_view(self):
        self._view_center = self._view_scale = self._drag_pos = None
        self.unsetCursor()
        if hasattr(self, '_nav'):
            self._layout_map()
        self.update()

    def _manual_camera(self):
        if self._view_scale is None:
            nav = self._raster_source
            self._view_scale = self._fit_scale()
            self._view_center = QtCore.QPointF(
                nav.origin_xy[0]+nav.states.shape[1]*nav.resolution_m/2,
                nav.origin_xy[1]+nav.states.shape[0]*nav.resolution_m/2)

    def focus_robot(self):
        """Center once on robot; later publications do not steal the view."""
        nav = self._nav
        if nav is None:return
        xy = (self._robot.samples[-1].xy if self._robot is not None else
              (nav.origin_xy[0]+nav.states.shape[1]*nav.resolution_m/2,
               nav.origin_xy[1]+nav.states.shape[0]*nav.resolution_m/2))
        self._view_center = QtCore.QPointF(*xy)
        rect = self._viewport_rect()
        self._view_scale = min(rect.width()/nav.states.shape[1],rect.height()/nav.states.shape[0])/nav.resolution_m
        self._layout_map();self.update()

    def wheelEvent(self, event):
        if self._nav is None:
            return super().wheelEvent(event)
        delta = event.angleDelta().y() or event.pixelDelta().y()*6
        if not delta:
            return super().wheelEvent(event)
        self._manual_camera()
        point = event.position() if hasattr(event, 'position') else event.posF()
        offset = point-self._viewport_rect().center()
        factor = math.exp(max(-2., min(2., delta/120.*math.log(1.15))))
        old = self._view_scale
        viewport = self._viewport_rect()
        local_fit = min(viewport.width()/self._nav.states.shape[1],
                        viewport.height()/self._nav.states.shape[0])/self._nav.resolution_m
        upper = max(self._fit_scale()*64., local_fit*64., old)
        lower = min(self._fit_scale()*.25, old)
        new = max(lower, min(upper, old*factor))
        self._view_center += QtCore.QPointF(offset.x()*(1/old-1/new), -offset.y()*(1/old-1/new))
        self._view_scale = new
        self._layout_map(); self.update(); event.accept()

    def mousePressEvent(self, event):
        if self._nav is not None and event.button() in (QtCore.Qt.LeftButton, QtCore.Qt.MiddleButton, QtCore.Qt.RightButton):
            self._manual_camera()
            self._drag_pos = event.pos()
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            delta = event.pos()-self._drag_pos
            self._view_center += QtCore.QPointF(-delta.x()/self._view_scale, delta.y()/self._view_scale)
            self._drag_pos = event.pos()
            self._layout_map(); self.update(); event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.fit_view()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_nav'):
            self._layout_map()

    @staticmethod
    def _raster_image(nav: NavSnapshot) -> QtGui.QImage:
        states = nav.states
        rgb = np.empty((*states.shape, 3), dtype=np.uint8)
        rgb[states == -1] = (68, 82, 101)  # unknown remains visibly distinct
        rgb[states == 0] = (58, 145, 111)
        rgb[states == 100] = (245, 91, 79)
        return _qimage_rgb(np.ascontiguousarray(rgb[::-1]))

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#0c1421"))
        if self._nav is None or self._map_image is None:
            painter.setPen(QtGui.QColor("#e7edf3"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, self.status_text)
            return
        self._layout_map()
        draw_rect = self._draw_rect
        source = self._map_image.rect()
        painter.save()
        painter.setClipRect(self._viewport_rect())
        painter.drawImage(draw_rect, self._map_image)
        sx = draw_rect.width() / source.width()
        sy = draw_rect.height() / source.height()
        painter.setPen(QtGui.QPen(QtGui.QColor("#f4b942"), 2))
        for polygon in self._regions:
            points = [QtCore.QPointF(
                draw_rect.left() + ((float(x) - self._raster_source.origin_xy[0]) / self._raster_source.resolution_m) * sx,
                draw_rect.bottom() - ((float(y) - self._raster_source.origin_xy[1]) / self._raster_source.resolution_m) * sy,
            ) for x, y in polygon]
            if len(points) >= 3:
                painter.drawPolygon(QtGui.QPolygonF(points))
        self._draw_rect = draw_rect
        painter.restore()
        self._draw_navigation(painter)
        self._draw_robot(painter)
        label = self._map_caption()
        painter.setPen(QtGui.QColor("#e7edf3"))
        painter.drawText(self.rect().adjusted(8, 2, -8, -2), QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap, label)

    def _map_caption(self):
        nav = self._nav
        if nav is None:
            return self.status_text
        if self._overview is not None:
            overview = self._overview
            source = overview.source_nav
            age = (f'{(self._now_ns-source.capture_monotonic_ns)/1e6:.0f} ms'
                   if source.clock_domain == self._clock_domain and self._now_ns >= source.capture_monotonic_ns else 'unavailable')
            return (f'Accumulated map r{source.revision} · latest update {age} · historical cells'
                    f' · {overview.resolution_m:.3g} m/cell · local r{nav.revision}'
                    + (' · INCOMPLETE overview' if not overview.complete else '')
                    + f' · room outlines r{self._room_map_revision}' + (' · STALE' if self._stale else ''))
        age = (f"{(self._now_ns-nav.capture_monotonic_ns)/1e6:.0f} ms old"
               if nav.clock_domain == self._clock_domain and self._now_ns >= nav.capture_monotonic_ns else "age unavailable")
        return (f"Map r{nav.revision} · {nav.source.sensor_id}:{nav.source.frame_index} · {age}"
                f" · room outlines map r{self._room_map_revision}" + (" · STALE" if self._stale else ""))

    def _world_to_pixel(self, xy):
        nav, rect = self._raster_source, self._draw_rect
        return QtCore.QPointF(rect.left()+(xy[0]-nav.origin_xy[0])/nav.resolution_m*rect.width()/nav.states.shape[1],
                             rect.bottom()-(xy[1]-nav.origin_xy[1])/nav.resolution_m*rect.height()/nav.states.shape[0])

    def _navigation_stale(self) -> bool:
        overlay = self._navigation
        return overlay is not None and (
            (self._nav is not None and overlay.map_revision != self._nav.revision)
            or overlay.clock_domain != self._clock_domain
            or self._now_ns < overlay.capture_monotonic_ns
            or self._now_ns - overlay.capture_monotonic_ns > 300_000_000
        )

    def _navigation_caption(self) -> str:
        overlay = self._navigation
        if overlay is None:
            return "Navigation plan unavailable"
        stale = self._navigation_stale()
        age = max(0, self._now_ns - overlay.capture_monotonic_ns) / 1_000_000
        goal = ("LAST GOAL" if stale else "HELD GOAL" if not overlay.path else "GOAL") if overlay.goal_xy is not None else "no active goal"
        return (f"Plan revision {overlay.map_revision} · {overlay.status} · "
                f"{'STALE · ' if stale else ''}{age:.0f} ms · {goal}"
                + (" · truncated" if overlay.truncated else ""))

    def _draw_navigation(self, painter: QtGui.QPainter) -> None:
        overlay = self._navigation
        painter.save()
        if overlay is not None:
            stale = self._navigation_stale()
            goal_color = QtGui.QColor("#a4b5ca" if stale else "#ff61d6")
            painter.setClipRect(self._draw_rect.intersected(self._viewport_rect()))
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            if overlay.goal_xy is not None and overlay.path:
                route = QtGui.QPainterPath(self._world_to_pixel(overlay.path[0]))
                for xy in overlay.path[1:2048]:
                    route.lineTo(self._world_to_pixel(xy))
                painter.setPen(QtGui.QPen(goal_color, 1.2, QtCore.Qt.DashLine))
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawPath(route)
            # Actual boundary cell centres and candidate robot viewpoints are separate layers.
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#ffda53"))
            for xy in overlay.frontier_points[:8192]:
                painter.drawEllipse(self._world_to_pixel(xy), 2.2, 2.2)
            painter.setBrush(QtGui.QColor("#5adce8"))
            for xy in overlay.viewpoints[:64]:
                painter.drawEllipse(self._world_to_pixel(xy), 3, 3)
            if overlay.goal_xy is not None:
                point = self._world_to_pixel(overlay.goal_xy)
                star = QtGui.QPolygonF([
                    point + QtCore.QPointF(math.cos(-math.pi/2+i*math.pi/5)*radius,
                                          math.sin(-math.pi/2+i*math.pi/5)*radius)
                    for i, radius in enumerate([10, 4.5]*5)
                ])
                painter.setPen(QtGui.QPen(QtGui.QColor("#101c2a"), 1.2))
                painter.setBrush(goal_color)
                painter.drawPolygon(star)
                painter.setPen(goal_color)
                painter.drawText(point+QtCore.QPointF(13, -10), "LAST GOAL · STALE" if stale else "GOAL")
            painter.setClipping(False)
        painter.setPen(QtGui.QColor("#a4b5ca" if self._navigation_stale() else "#e7edf3"))
        caption = self._navigation_caption()
        if overlay is not None:
            goal_legend = "gray last goal" if self._navigation_stale() else "magenta goal"
            caption += f"\nYellow frontier · cyan viewpoint · {goal_legend} · dashed route"
        painter.drawText(self.rect().adjusted(10, 48, -10, -42),
                         QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap, caption)
        painter.restore()

    def _draw_robot(self, painter):
        painter.save()
        if self._robot is None:
            painter.setPen(QtGui.QColor("#a4b5ca"))
            painter.drawText(self.rect().adjusted(10, 24, -10, -10),
                             QtCore.Qt.AlignBottom | QtCore.Qt.AlignLeft, "Robot pose unavailable")
            painter.restore()
            return
        samples = self._robot.samples
        last = samples[-1]
        stale = (last.clock_domain != self._clock_domain or self._now_ns < last.capture_monotonic_ns
                 or self._now_ns-last.capture_monotonic_ns > 300_000_000)
        color = QtGui.QColor("#a4b5ca" if stale else "#69baff")
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setClipRect(self._draw_rect.intersected(self._viewport_rect()))
        path = QtGui.QPainterPath()
        path.moveTo(self._world_to_pixel(samples[0].xy))
        for previous, sample in zip(samples, samples[1:]):
            point = self._world_to_pixel(sample.xy)
            if (sample.source.frame_index != previous.source.frame_index+1
                    or sample.capture_monotonic_ns-previous.capture_monotonic_ns > 1_000_000_000):
                path.moveTo(point)  # no invented continuous movement across missing samples
            else:
                path.lineTo(point)
        painter.setPen(QtGui.QPen(color, 1.3))
        painter.drawPath(path)
        camera = self._robot.camera
        if camera is not None:
            camera_point = self._world_to_pixel(camera.xy)
            ends = [self._world_to_pixel((camera.xy[0]+math.cos(a), camera.xy[1]+math.sin(a))) for a in camera.edge_yaws]
            fill = QtGui.QColor(color);fill.setAlpha(28)
            painter.setBrush(fill)
            pen = QtGui.QPen(color, 1.1, QtCore.Qt.DashLine if stale else QtCore.Qt.SolidLine)
            painter.setPen(pen)
            painter.drawPolygon(QtGui.QPolygonF([camera_point,*ends]))
        point = self._world_to_pixel(last.xy)
        painter.setBrush(QtGui.QColor("#101c2a"))
        painter.setPen(QtGui.QPen(QtGui.QColor("#eef7ff"), 2))
        painter.drawEllipse(point, 8, 8)
        painter.setBrush(color);painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(point, 5, 5)
        # Constant-screen-size heading marker, not a physical footprint or a route command.
        dx, dy = math.cos(last.yaw_rad), -math.sin(last.yaw_rad)
        tip = point+QtCore.QPointF(27*dx, 27*dy)
        painter.setPen(QtGui.QPen(color, 2))
        painter.drawLine(point, tip)
        painter.setBrush(color)
        painter.drawPolygon(QtGui.QPolygonF([tip,tip+QtCore.QPointF(-8*dx-4*dy,-8*dy+4*dx),
                                               tip+QtCore.QPointF(-8*dx+4*dy,-8*dy-4*dx)]))
        painter.setPen(color)
        if self._draw_rect.intersected(self._viewport_rect()).contains(point):
            painter.drawText(point+QtCore.QPointF(12,-13), "ROBOT" + (" · STALE" if stale else ""))
        painter.setClipping(False)
        text = "Pose STALE" if stale else "Measured robot pose"
        text += " · sampled trail" + (" (last 1024)" if self._robot.truncated else "")
        if camera is not None:
            derived = getattr(camera, "policy", None) is not None
            text += "\nCamera FOV · calibrated projection (1 m schematic)" if derived else "\nCamera FOV (1 m schematic)"
        else:text += "\nCamera FOV unavailable"
        painter.drawText(self.rect().adjusted(10, 24, -10, -10), QtCore.Qt.AlignBottom | QtCore.Qt.AlignLeft,
                         "\n".join(painter.fontMetrics().elidedText(line,QtCore.Qt.ElideRight,self.width()-20)
                                   for line in text.splitlines()))
        painter.restore()


class DashboardWindow(QtWidgets.QMainWindow):
    """Read-only dashboard over one immutable envelope per refresh."""

    def __init__(
        self,
        publication_reader: Callable[[], DisplayEnvelope | None] | DisplayPublisher | None = None,
        control_client: UiControlClient | None = None,
        *,
        clock_domain: str | None = None,
        now_ns: Callable[[], int] = monotonic_ns,
        parent=None,
        best_view_provider=None,
        cloud_reader=None,
    ) -> None:
        super().__init__(parent)
        if isinstance(publication_reader, DisplayPublisher):
            self._read_latest = publication_reader.read_latest
        elif callable(publication_reader):
            self._read_latest = publication_reader
        elif publication_reader is None:
            self._read_latest = lambda: None
        else:
            raise ValueError("publication_reader must be a publisher, callable or None")
        self._control = control_client
        self._best_view_provider = best_view_provider
        self._cloud_reader = cloud_reader
        self._last_cloud_request_ns = None
        self._graph_popup = None
        self._graph_docked_sizes = None
        self._clock_domain = clock_domain
        self._now_ns = now_ns
        self._envelope: DisplayEnvelope | None = None
        self._selected_object_id: str | None = None
        self._selection_was_alias = False
        self._last_sequence: int | None = None
        self.setWindowTitle("NeuSymNav · live hierarchy")
        self.preferred_size = QtCore.QSize(2160, 1350)
        self._observation_pixels = None
        self._build_ui()
        available = self.screen().availableGeometry()
        self.resize(self.preferred_size.boundedTo(available.size()))
        if available.width() < 2160 or available.height() < 1350:
            self.setWindowState(self.windowState() | QtCore.Qt.WindowMaximized)
        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setInterval(100)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    def _build_ui(self) -> None:
        self.setWindowTitle("NeuSymNav / Live Scene Explorer")
        self.setMinimumSize(640, 480)
        self.setStyleSheet("""
            QMainWindow, QWidget#dashboard { background: #0a101b; color: #dee7f1; }
            QWidget { font-family: 'DejaVu Sans'; font-size: 15px; color: #dee7f1; }
            QFrame#panel, QFrame#header { background: #131d2d; border: 1px solid #29394d; border-radius: 10px; }
            QLabel { background: transparent; border: none; }
            QLabel#brand { color: #eef5ff; font-size: 28px; font-weight: 600; }
            QLabel#eyebrow, QLabel#panelTitle { color: #93a3b5; font-size: 13px; font-weight: 600; }
            QLabel#subtitle, QLabel#rgbCaption, QLabel#bestViewCaption, QLabel#commandStatus { color: #93a3b5; font-size: 14px; }
            QLabel#statusBadge { background: #233549; color: #a6ccec; border-radius: 5px; padding: 7px 12px; font-weight: 600; }
            QLabel#rgbView, QLabel#bestView { background: #0c1421; color: #93a3b5; border-radius: 7px; }
            QLabel#objectDetails { color: #b7c7d9; font-size: 14px; padding: 8px; background: #0c1421; border-radius: 6px; }
            QPushButton, QToolButton { background: #1c2d43; border: 1px solid #354b65; border-radius: 5px; padding: 7px 14px; }
            QPushButton:hover, QToolButton:hover { background: #2b4260; border-color: #6eafe8; }
            QPushButton:disabled { color: #64778d; border-color: #29394d; }
            QPushButton#stopButton { background: #482a32; border-color: #75414b; color: #f2b5b5; }
            QComboBox { background: #1c2d43; border: 1px solid #354b65; border-radius: 5px; padding: 5px 12px; color: #dee7f1; }
            QComboBox QAbstractItemView { background: #131d2d; color: #dee7f1; selection-background-color: #254365; }
            QCheckBox::indicator { width: 16px; height: 16px; background: #0c1421; border: 1px solid #6eafe8; border-radius: 3px; }
            QCheckBox::indicator:checked { background: #6eafe8; border: 2px solid #c8e3ff; }
            QLineEdit { background: #0c1421; border: 1px solid #29394d; border-radius: 5px; padding: 7px; selection-background-color: #375779; }
            QTreeWidget { background: #0c1421; border: none; outline: none; border-radius: 5px; }
            QTreeWidget::item { padding: 7px 2px; }
            QTreeWidget::item:selected { background: #254365; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: #131d2d; color: #93a3b5; padding: 8px 12px; border-bottom: 2px solid transparent; }
            QTabBar::tab:selected { color: #c8e3ff; border-bottom: 2px solid #6eafe8; }
            QScrollArea { background: transparent; border: none; }
            QSplitter::handle { background: #29435e; margin: 2px; }
            QSplitter::handle:hover { background: #6eafe8; }
            QScrollBar:vertical { background: #0c1421; width: 8px; }
            QScrollBar::handle:vertical { background: #354b65; min-height: 20px; border-radius: 4px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)
        central = QtWidgets.QWidget(self)
        central.setObjectName("dashboard")
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(12)
        header = QtWidgets.QFrame()
        header.setObjectName("header")
        header_layout = QtWidgets.QHBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)
        brand = QtWidgets.QVBoxLayout()
        eyebrow = QtWidgets.QLabel("SPATIAL INTELLIGENCE / LIVE SNAPSHOT")
        eyebrow.setObjectName("eyebrow")
        title = QtWidgets.QLabel("NeuSymNav")
        title.setObjectName("brand")
        self.subtitle = QtWidgets.QLabel("Waiting for sensor and graph publication")
        self.subtitle.setObjectName("subtitle")
        brand.addWidget(eyebrow)
        brand.addWidget(title)
        brand.addWidget(self.subtitle)
        header_layout.addLayout(brand, 1)
        self.status_badge = QtWidgets.QLabel("WAITING")
        self.status_badge.setObjectName("statusBadge")
        header_layout.addWidget(self.status_badge)
        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.setObjectName("pauseButton")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setObjectName("stopButton")
        for button, action in [(self.pause_button, "pause"), (self.stop_button, "stop")]:
            button.setEnabled(self._control is not None)
            button.clicked.connect(lambda checked=False, a=action: self._send_command(a))
            header_layout.addWidget(button)
        layout.addWidget(header)

        self.overview = QtWidgets.QLabel("RGB —     MAP —     OBJECTS —     REGIONS —")
        self.overview.setObjectName("overview")
        self.overview.setStyleSheet("color:#a6ccec; padding:2px 4px; font-size:12px")
        layout.addWidget(self.overview)
        view_row = QtWidgets.QHBoxLayout()
        view_row.addWidget(QtWidgets.QLabel("Focus view"))
        self.focus_selector = QtWidgets.QComboBox()
        self.focus_selector.addItems(["All panels", "RGB FRAME", "OCCUPANCY MAP", "SCENE GRAPH"])
        self.focus_selector.currentTextChanged.connect(self.focus_panel)
        view_row.addWidget(self.focus_selector)
        view_row.addStretch(1)
        self.boxes_toggle = QtWidgets.QCheckBox("Bounding boxes + labels")
        self.masks_toggle = QtWidgets.QCheckBox("Segmentation masks")
        for toggle in (self.boxes_toggle, self.masks_toggle):
            toggle.setChecked(True)
            toggle.toggled.connect(self._render_observation)
            view_row.addWidget(toggle)
        layout.addLayout(view_row)
        self.workspace_split = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.workspace_split.setHandleWidth(12)
        self.workspace_split.setOpaqueResize(True)
        self.sensor_row = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.workspace_split.addWidget(self.sensor_row)
        split = self.sensor_row
        def panel(title, subtitle):
            frame = QtWidgets.QFrame()
            frame.setObjectName("panel")
            body = QtWidgets.QVBoxLayout(frame)
            body.setContentsMargins(12, 12, 12, 12)
            body.setSpacing(9)
            label = QtWidgets.QLabel(title)
            label.setObjectName("panelTitle")
            body.addWidget(label)
            hint = QtWidgets.QLabel(subtitle)
            hint.setObjectName("subtitle")
            body.addWidget(hint)
            return frame, body
        left, left_layout = panel("RGB FRAME", "Source-matched detector observations / live camera")
        self.sensor_panel = left
        self.sensor_row.addWidget(left)
        self.image_tabs = QtWidgets.QTabWidget()
        self.observation_page = QtWidgets.QWidget()
        observation_layout = QtWidgets.QVBoxLayout(self.observation_page)
        observation_layout.setContentsMargins(0, 0, 0, 0)
        self.observation_view = QtWidgets.QLabel("Detector observation unavailable")
        self.observation_view.setAlignment(QtCore.Qt.AlignCenter)
        self.observation_view.setObjectName("rgbView")
        self.observation_view.setMinimumSize(200, 130)
        self.observation_view.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        observation_layout.addWidget(self.observation_view, 1)
        self.observation_caption = QtWidgets.QLabel("Detector observation unavailable")
        self.observation_caption.setWordWrap(True)
        self.observation_caption.setTextFormat(QtCore.Qt.PlainText)
        observation_layout.addWidget(self.observation_caption)
        self.image_tabs.addTab(self.observation_page, "Detector observation")
        live_page = QtWidgets.QWidget()
        live_layout = QtWidgets.QVBoxLayout(live_page)
        live_layout.setContentsMargins(0, 0, 0, 0)
        self.image_tabs.addTab(live_page, "Live RGB")
        self.image_tabs.currentChanged.connect(self._resize_images)
        left_layout.addWidget(self.image_tabs, 1)
        self.rgb_view = QtWidgets.QLabel("RGB unavailable · no source image")
        self.rgb_view.setObjectName("rgbView")
        self.rgb_view.setAlignment(QtCore.Qt.AlignCenter)
        self.rgb_view.setWordWrap(True)
        self.rgb_view.setMinimumSize(240, 180)
        self.rgb_view.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        live_layout.addWidget(self.rgb_view, 1)
        self.rgb_caption = QtWidgets.QLabel("RGB unavailable · no source image")
        self.rgb_caption.setObjectName("rgbCaption")
        self.rgb_caption.setWordWrap(True)
        live_layout.addWidget(self.rgb_caption)
        middle, middle_layout = panel("OCCUPANCY MAP", "Accumulated map · Wheel: zoom · Drag: pan · Double-click: fit")
        self.map_panel = middle
        self.sensor_row.addWidget(middle)
        self.map_view = MapWidget(middle)
        self.map_view.setMinimumHeight(100)
        self.map_view.setObjectName("mapView")
        middle_layout.addWidget(self.map_view, 1)
        map_controls = QtWidgets.QHBoxLayout()
        self.map_fit_button = QtWidgets.QPushButton('Toàn bộ map')
        self.map_fit_button.clicked.connect(self.map_view.fit_view)
        self.map_robot_button = QtWidgets.QPushButton('Về robot')
        self.map_robot_button.clicked.connect(self.map_view.focus_robot)
        map_controls.addWidget(self.map_fit_button);map_controls.addWidget(self.map_robot_button)
        legend = QtWidgets.QLabel("● Free    <font color='#f55b4f'>● Obstacle</font>    <font color='#445265'>● Unknown</font>")
        legend.setStyleSheet("color:#3a916f; font-size:11px")
        legend.setWordWrap(True)
        middle_layout.addWidget(legend)
        trail_legend = QtWidgets.QLabel("<font color='#69baff'>● Robot  ─ Sampled trail  ◁ Camera FOV</font>")
        trail_legend.setStyleSheet("font-size:11px")
        trail_legend.setWordWrap(True)
        map_controls.insertWidget(0, trail_legend, 1)
        middle_layout.addLayout(map_controls)

        right, right_layout = panel("3D SCENE / SCENE GRAPH", "Measured RGB-D · Measured Objects · Room / Floor hierarchy anchors · select an object for evidence")
        self.graph_panel = right
        self.workspace_split.addWidget(right)
        self.graph_split = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.graph_split.setHandleWidth(12)
        self.graph_split.setChildrenCollapsible(False)
        self.graph_split.splitterMoved.connect(lambda *_: QtCore.QTimer.singleShot(0, self._resize_images))
        right_layout.addWidget(self.graph_split, 1)
        graph_container = QtWidgets.QWidget()
        graph_content = QtWidgets.QVBoxLayout(graph_container)
        graph_content.setContentsMargins(0, 0, 0, 0)
        self.graph_split.addWidget(graph_container)
        evidence_frame = QtWidgets.QWidget()
        evidence_layout = QtWidgets.QVBoxLayout(evidence_frame)
        evidence_layout.setContentsMargins(10, 0, 0, 0)
        evidence_scroll = QtWidgets.QScrollArea()
        evidence_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        evidence_scroll.setWidgetResizable(True)
        evidence_scroll.setMinimumSize(180, 100)
        evidence_scroll.setWidget(evidence_frame)
        self.graph_split.addWidget(evidence_scroll)
        self.graph_split.setStretchFactor(0, 4)
        self.graph_split.setStretchFactor(1, 1)
        self.graph_split.setSizes([1200, 300])
        self.graph_split.handle(1).setToolTip("Drag left/right to resize graph and object evidence")
        label = QtWidgets.QLabel("OBJECT EVIDENCE")
        label.setObjectName("panelTitle")
        evidence_layout.addWidget(label)
        self.best_view = QtWidgets.QLabel("Best view unavailable · no evidence image")
        self.best_view.setObjectName("bestView")
        self.best_view.setAlignment(QtCore.Qt.AlignCenter)
        self.best_view.setWordWrap(True)
        self.best_view.setMinimumSize(200, 100)
        self.best_view.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        evidence_layout.addWidget(self.best_view, 1)
        self.best_view_caption = QtWidgets.QLabel("Best view unavailable · no evidence image")
        self.best_view_caption.setObjectName("bestViewCaption")
        self.best_view_caption.setWordWrap(True)
        evidence_layout.addWidget(self.best_view_caption)


        tabs = QtWidgets.QTabWidget()
        self.scene_tabs = tabs
        self.spatial_view = SpatialSceneWidget()
        self.spatial_view.object_selected.connect(self.select_object)
        tabs.addTab(self.spatial_view, "3D Scene")
        self.graph_view = SceneGraphWidget()
        self.graph_view.setObjectName("sceneGraph")
        self.graph_view.object_selected.connect(self.select_object)
        tabs.addTab(self.graph_view, "Graph layout")
        self.hierarchy = QtWidgets.QTreeWidget()
        self.hierarchy.setObjectName("hierarchyTree")
        self.hierarchy.setHeaderHidden(True)
        self.hierarchy.itemSelectionChanged.connect(self._tree_selection_changed)
        tabs.addTab(self.hierarchy, "Hierarchy")
        controls = QtWidgets.QHBoxLayout()
        self.graph_controls = {}
        for label, tip, callback in (
            ("−", "Zoom out", lambda: self._zoom_graph(1/1.25)),
            ("+", "Zoom in", lambda: self._zoom_graph(1.25)),
            ("Fit", "Fit the current graph in view", self._fit_graph),
            ("Top", "View the spatial scene from above", self._top_graph),
            ("Expand", "Expand graph in the main window / restore all panels", self._expand_graph),
            ("Pop out", "Open a separate graph window; drag its borders to resize", self._toggle_graph_popup),
        ):
            button = QtWidgets.QToolButton()
            button.setText(label); button.setToolTip(tip)
            button.clicked.connect(callback)
            controls.addWidget(button); self.graph_controls[label] = button
        self.cloud_menu_button = QtWidgets.QToolButton()
        self.cloud_menu_button.setText("Cloud")
        self.cloud_menu_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        cloud_menu = QtWidgets.QMenu(self.cloud_menu_button)
        self.cloud_cutaway_action = cloud_menu.addAction("Filter cloud height")
        self.cloud_cutaway_action.setCheckable(True)
        self.cloud_cutaway_action.setChecked(True)
        height_widget = QtWidgets.QWidget()
        height_form = QtWidgets.QFormLayout(height_widget)
        self.cloud_lower_spin = QtWidgets.QDoubleSpinBox()
        self.cloud_lower_spin.setRange(0, .5)
        self.cloud_lower_spin.setValue(self.spatial_view.height_min_m)
        self.cloud_lower_spin.setSpecialValueText("Keep floor")
        self.cloud_upper_spin = QtWidgets.QDoubleSpinBox()
        self.cloud_upper_spin.setRange(.6, 10.)
        self.cloud_upper_spin.setValue(self.spatial_view.height_max_m)
        for spin in (self.cloud_lower_spin,self.cloud_upper_spin):
            spin.setDecimals(2); spin.setSingleStep(.05); spin.setSuffix(" m")
        height_form.addRow("Above floor",self.cloud_lower_spin)
        height_form.addRow("Below height",self.cloud_upper_spin)
        height_action = QtWidgets.QWidgetAction(cloud_menu)
        height_action.setDefaultWidget(height_widget)
        cloud_menu.addAction(height_action)
        self.cloud_menu_button.setMenu(cloud_menu)
        self.cloud_menu_button.setToolTip("Display-only height cutaway above the calibrated floor; upper walls are clipped too. Nodes and stored geometry stay complete.")
        def apply_cloud_filter(*_):
            self.spatial_view.configure_height_filter(self.cloud_cutaway_action.isChecked(),
                self.cloud_lower_spin.value(),self.cloud_upper_spin.value())
        self.cloud_cutaway_action.toggled.connect(apply_cloud_filter)
        self.cloud_lower_spin.valueChanged.connect(apply_cloud_filter)
        self.cloud_upper_spin.valueChanged.connect(apply_cloud_filter)
        controls.addWidget(self.cloud_menu_button)
        controls.addStretch(1)
        graph_content.addLayout(controls)
        graph_content.addWidget(tabs, 1)
        legend = QtWidgets.QLabel("● Teal: Floor   ● Blue: Room   ● Gold: Object · Solid: membership · Cyan dashes: Room links (structural) · Room/Floor Z is layout; RGB-D stays measured")
        legend.setWordWrap(True)
        legend.setObjectName("subtitle")
        graph_content.addWidget(legend)
        select_row = QtWidgets.QHBoxLayout()
        self.object_id_input = QtWidgets.QLineEdit()
        self.object_id_input.setPlaceholderText("Object ID or alias…")
        self.object_id_input.setObjectName("objectIdInput")
        select_button = QtWidgets.QPushButton("Select")
        select_button.clicked.connect(self._select_from_input)
        select_row.addWidget(self.object_id_input, 1)
        select_row.addWidget(select_button)
        evidence_layout.addLayout(select_row)
        self.object_details = QtWidgets.QLabel("No selected object")
        self.object_details.setObjectName("objectDetails")
        self.object_details.setWordWrap(True)
        self.object_details.setTextFormat(QtCore.Qt.PlainText)
        detail_scroll = QtWidgets.QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setMinimumHeight(60)
        detail_scroll.setMaximumHeight(190)
        detail_scroll.setWidget(self.object_details)
        evidence_layout.addWidget(detail_scroll)
        self.sensor_row.setSizes([1100, 1000])
        self.workspace_split.setSizes([430, 650])
        self.workspace_split.setChildrenCollapsible(False)
        self.workspace_split.setCollapsible(0, True)
        self.workspace_split.handle(1).setToolTip("Drag up/down to resize the graph; drag fully up to hide camera/map")
        self.rgb_view.setMinimumHeight(80)
        self.observation_view.setMinimumHeight(80)
        self.sensor_row.setChildrenCollapsible(False)
        layout.addWidget(self.workspace_split, 1)

        self.command_status = QtWidgets.QLabel("Control unavailable" if self._control is None else "No command sent")
        self.command_status.setObjectName("commandStatus")
        layout.addWidget(self.command_status)
        details = QtWidgets.QToolButton()
        details.setText("Source & revision details")
        details.setCheckable(True)
        details.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        details.setArrowType(QtCore.Qt.RightArrow)
        layout.addWidget(details)
        self.telemetry = QtWidgets.QLabel("Waiting for display publication")
        self.telemetry.setObjectName("telemetry")
        self.telemetry.setWordWrap(True)
        self.telemetry.setTextFormat(QtCore.Qt.PlainText)
        self.telemetry.setStyleSheet("color:#93a3b5; font-size:10px; padding:6px")
        self.telemetry.setVisible(False)
        details.toggled.connect(self.telemetry.setVisible)
        details.toggled.connect(lambda opened: details.setArrowType(QtCore.Qt.DownArrow if opened else QtCore.Qt.RightArrow))
        layout.addWidget(self.telemetry)
        self.setCentralWidget(central)

    def refresh(self) -> None:
        """Read one envelope, render all panels from it, then refresh ACK state."""
        envelope = self._read_latest()
        if envelope is not None and envelope.publication_sequence != self._last_sequence:
            self._envelope = envelope
            self._last_sequence = envelope.publication_sequence
            self._render_envelope(envelope)
        elif envelope is None and self._envelope is None:
            self.telemetry.setText("Waiting for display publication · RGB/map/graph unavailable")
        self.map_view._now_ns = self._now_ns()
        self.map_view._clock_domain = self._clock_domain or (None if self._envelope is None else self._envelope.clock_domain)
        self.map_view.update()
        self.spatial_view.now_ns = self._now_ns()
        if self._cloud_reader is not None and self._envelope is not None:
            now = self._now_ns()
            if self._last_cloud_request_ns is None or now-self._last_cloud_request_ns >= 500_000_000:
                self._cloud_reader.offer(self._envelope)
                self._last_cloud_request_ns = now
            self.spatial_view.set_cloud(self._cloud_reader.latest)
            self.spatial_view.cloud_error = self._cloud_reader.error
        self.spatial_view.update()
        self._refresh_observation_age()
        self._refresh_rgb_age()
        self._refresh_telemetry()
        self._refresh_command_status()

    def _render_envelope(self, envelope: DisplayEnvelope) -> None:
        self.map_view.set_snapshot(getattr(envelope.sources, "live_nav", None) or envelope.sources.nav, envelope)
        if envelope.sources.rgb is None:
            self.rgb_view.setPixmap(QtGui.QPixmap())
            self.rgb_view.setText("RGB unavailable · no source image")
            self.rgb_caption.setText("RGB source unavailable")
        else:
            frame = envelope.sources.rgb
            self.rgb_view.setPixmap(QtGui.QPixmap.fromImage(_qimage_rgb(frame.pixels)).scaled(
                self.rgb_view.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
            ))
            self.rgb_view.setToolTip(f"RGB source · {frame.source.sensor_id}:{frame.source.frame_index}")
            age = envelope.metrics.source_age_ns.get("rgb")
            age_label = "age unavailable" if age is None else f"source age {age / 1e6:.1f} ms"
            self.rgb_caption.setText(f"RGB · {frame.source.sensor_id}:{frame.source.frame_index} · {age_label}")
        self._render_observation()
        self.graph_view.set_envelope(envelope)
        self.spatial_view.set_envelope(envelope)
        self._render_hierarchy(envelope)
        if self._selected_object_id is None:
            first = next((node_id for node_id, node in envelope.hierarchy.nodes.items() if node.kind == "object"), None)
            if first is not None:
                self._selected_object_id = first
        self._render_selected_object()
        self._refresh_telemetry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._envelope is not None:
            QtCore.QTimer.singleShot(0, self._resize_images)

    def _resize_images(self) -> None:
        if self._envelope is None:
            return
        rgb = self._envelope.sources.rgb
        if rgb is not None:
            self.rgb_view.setPixmap(QtGui.QPixmap.fromImage(_qimage_rgb(rgb.pixels)).scaled(
                self.rgb_view.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        self._scale_observation()
        self._render_selected_object()

    def focus_panel(self, title: str) -> None:
        """Focus is a view-only operation; runtime publication remains untouched."""
        all_panels = title == "All panels"
        self.sensor_row.setVisible(all_panels or title != "SCENE GRAPH")
        self.sensor_panel.setVisible(all_panels or title == "RGB FRAME")
        self.map_panel.setVisible(all_panels or title == "OCCUPANCY MAP")
        self.graph_panel.setVisible(all_panels or title == "SCENE GRAPH" or self._graph_popup is not None)
        QtCore.QTimer.singleShot(0, self._resize_images)

    def _zoom_graph(self, factor) -> None:
        view = self.scene_tabs.currentWidget()
        if view in (self.spatial_view, self.graph_view):
            view.zoom_by(factor)

    def _fit_graph(self) -> None:
        view = self.scene_tabs.currentWidget()
        if view is self.spatial_view:
            view.reset_view()
        elif view is self.graph_view:
            view.fit_view()

    def _top_graph(self) -> None:
        self.scene_tabs.setCurrentWidget(self.spatial_view)
        self.spatial_view.yaw = 0.
        self.spatial_view.pitch = math.pi/2
        self.spatial_view.reset_view()

    def _expand_graph(self) -> None:
        if self._graph_popup is not None:
            self._graph_popup.showMaximized()
        else:
            self.focus_selector.setCurrentText(
                "All panels" if self.focus_selector.currentText() == "SCENE GRAPH" else "SCENE GRAPH")

    def _toggle_graph_popup(self) -> None:
        if self._graph_popup is not None:
            self._graph_popup.close()
            return
        self._graph_docked_sizes = self.workspace_split.sizes()
        popup = QtWidgets.QDialog(self, QtCore.Qt.Window)
        self._graph_popup = popup
        popup.setWindowTitle("NeuSymNav / Graph debug")
        popup.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        popup.setSizeGripEnabled(True)
        popup.setMinimumSize(500, 360)
        body = QtWidgets.QVBoxLayout(popup)
        body.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.graph_panel)
        available = self.screen().availableGeometry()
        popup.resize(min(1500, available.width()-40), min(950, available.height()-40))
        popup.finished.connect(self._restore_graph_panel)
        self.graph_controls["Pop out"].setText("Dock back")
        self.graph_panel.show()
        popup.show()

    def _restore_graph_panel(self, _result=None) -> None:
        if self._graph_popup is None:
            return
        self._graph_popup = None
        self.workspace_split.addWidget(self.graph_panel)
        if self._graph_docked_sizes is not None:
            self.workspace_split.setSizes(self._graph_docked_sizes)
        self.graph_controls["Pop out"].setText("Pop out")
        self.focus_panel(self.focus_selector.currentText())

    def closeEvent(self, event) -> None:
        if self._graph_popup is not None:
            self._graph_popup.close()
        super().closeEvent(event)

    def _render_observation(self, _checked=None) -> None:
        observation = None if self._envelope is None else self._envelope.sources.observation
        had_observation = self._observation_pixels is not None
        self.image_tabs.setTabEnabled(0, observation is not None)
        self.boxes_toggle.setEnabled(observation is not None)
        self.masks_toggle.setEnabled(observation is not None)
        if observation is None:
            self._observation_pixels = None
            self.observation_view.clear()
            self.observation_view.setText("Detector observation unavailable")
            self.observation_caption.setText("Detector observation unavailable · no source-matched result")
            self.image_tabs.setCurrentIndex(1)
            return
        from .perception_overlay import render_observation
        self._observation_pixels = render_observation(
            observation, boxes=self.boxes_toggle.isChecked(), masks=self.masks_toggle.isChecked())
        frame = observation.image
        now = self._now_ns()
        domain = self._clock_domain or self._envelope.clock_domain
        age = (f"source age {(now-frame.capture_monotonic_ns)/1e6:.1f} ms"
               if domain == frame.clock_domain and now >= frame.capture_monotonic_ns else "source age unavailable")
        cap = " · CAP REACHED" if observation.cap_reached else ""
        self.observation_caption.setText(
            f"Detector observation · {frame.source.sensor_id}:{frame.source.frame_index} · {age} · historical\n"
            f"{len(observation.instances)}/{observation.total_detections} detections displayed · {observation.completion}{cap}")
        if not had_observation:
            self.image_tabs.setCurrentIndex(0)
        self._scale_observation()

    def _refresh_observation_age(self) -> None:
        if self._envelope is None or self._envelope.sources.observation is None:
            return
        frame = self._envelope.sources.observation.image
        now = self._now_ns()
        domain = self._clock_domain or self._envelope.clock_domain
        age = (f"source age {(now-frame.capture_monotonic_ns)/1e6:.1f} ms"
               if domain == frame.clock_domain and now >= frame.capture_monotonic_ns else "source age unavailable")
        lines = self.observation_caption.text().split("\n")
        lines[0] = f"Detector observation · {frame.source.sensor_id}:{frame.source.frame_index} · {age} · capture {frame.capture_monotonic_ns} ns · historical"
        self.observation_caption.setText("\n".join(lines))

    def _refresh_rgb_age(self):
        if self._envelope is None or self._envelope.sources.rgb is None:
            return
        frame = self._envelope.sources.rgb
        now = self._now_ns()
        domain = self._clock_domain or self._envelope.clock_domain
        age = (f"source age {(now-frame.capture_monotonic_ns)/1e6:.1f} ms"
               if domain == frame.clock_domain and now >= frame.capture_monotonic_ns else "source age unavailable")
        self.rgb_caption.setText(f"RGB · {frame.source.sensor_id}:{frame.source.frame_index} · {age} · capture {frame.capture_monotonic_ns} ns")

    def _scale_observation(self) -> None:
        if self._observation_pixels is not None:
            self.observation_view.setPixmap(QtGui.QPixmap.fromImage(_qimage_rgb(self._observation_pixels)).scaled(
                self.observation_view.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _render_hierarchy(self, envelope: DisplayEnvelope) -> None:
        self.hierarchy.clear()
        items: dict[str, QtWidgets.QTreeWidgetItem] = {}
        rank = {"floor": 0, "room": 1, "object": 2}
        rows = sorted(hierarchy_rows(envelope), key=lambda row: (rank.get(row.kind, 9), row.node_id))
        for row in rows[:SceneGraphWidget.MAX_NODES]:
            item = QtWidgets.QTreeWidgetItem([row.label])
            item.setData(0, QtCore.Qt.UserRole, row.node_id)
            if row.stale:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor("#e89d32")))
                item.setToolTip(0, "Room geometry is stale; no current membership is certified.")
            elif row.status in {"unassigned", "ambiguous", "unavailable"}:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor("#d58a78")))
                item.setToolTip(0, f"Parent/membership status: {row.status}")
            if row.verification_reason is not None:
                item.setToolTip(0, f"Verification unavailable: {row.verification_reason}")
            if row.parent_id in items:
                items[row.parent_id].addChild(item)
            else:
                self.hierarchy.addTopLevelItem(item)
            items[row.node_id] = item
        if self._selected_object_id in items:
            self.hierarchy.setCurrentItem(items[self._selected_object_id])
        self.hierarchy.expandAll()

    def select_object(self, object_id: str) -> str:
        """Select by canonical ID or alias and return the canonical ID."""
        if self._envelope is None:
            raise RuntimeError("no hierarchy publication is available")
        canonical, was_alias = resolve_object_selection(self._envelope, object_id)
        self._selection_was_alias = was_alias
        self._selected_object_id = canonical
        self._render_selected_object()
        for index in range(self.hierarchy.topLevelItemCount()):
            selected = self._find_item(self.hierarchy.topLevelItem(index), canonical)
            if selected is not None:
                self.hierarchy.setCurrentItem(selected)
                break
        return canonical

    @staticmethod
    def _find_item(item: QtWidgets.QTreeWidgetItem, node_id: str) -> QtWidgets.QTreeWidgetItem | None:
        if item.data(0, QtCore.Qt.UserRole) == node_id:
            return item
        for index in range(item.childCount()):
            result = DashboardWindow._find_item(item.child(index), node_id)
            if result is not None:
                return result
        return None

    def _select_from_input(self) -> None:
        if self._envelope is None:
            self.object_details.setText("Selection unavailable · no hierarchy publication")
            return
        value = self.object_id_input.text().strip()
        try:
            canonical = self.select_object(value)
            self.object_details.setText(self._object_detail(canonical, alias=(canonical != value)))
        except (ValueError, KeyError) as exc:
            self.object_details.setText(f"Selection unavailable · {exc}")

    def _tree_selection_changed(self) -> None:
        selected = self.hierarchy.selectedItems()
        if not selected:
            return
        node_id = selected[0].data(0, QtCore.Qt.UserRole)
        node = None if self._envelope is None else self._envelope.hierarchy.nodes.get(node_id)
        if node is None or node.kind != "object":
            return
        if node_id != self._selected_object_id:
            self._selection_was_alias = False
        self._selected_object_id = node_id
        self._render_selected_object()

    def _object_detail(self, canonical: str, alias: bool = False) -> str:
        assert self._envelope is not None
        node = self._envelope.hierarchy.nodes[canonical]
        attrs = node.attributes
        row = next(row for row in hierarchy_rows(self._envelope) if row.node_id == canonical)
        parent, membership = row.parent_id, row.status
        lifecycle = attrs.get("lifecycle", "unknown")
        aliases = tuple(attrs.get("aliases", ()))
        verification, reason, record = resolve_verification(self._envelope, canonical)
        lines = [f"Object {canonical}", f"Lifecycle: {lifecycle}", f"Verification: {verification}",
                 f"Membership: {membership}",
                 f"Parent room: {parent if parent is not None else 'unknown / unassigned'}"]
        if record is not None:
            lines.append(f"Verification source events: {len(record.evidence)}")
            if record.evidence:
                sources = ", ".join(
                    f"{item.source.sensor_id}:{item.source.frame_index} ({item.clock_domain})"
                    for item in record.evidence
                )
                lines.append(f"Verification provenance: {sources}")
        elif reason is not None:
            lines.append(f"Verification unavailable: {reason}")
        if alias:
            lines.append("Selected alias resolves to this canonical ID")
        if aliases:
            lines.append("Aliases: " + ", ".join(aliases))
        return "\n".join(lines)

    def _render_selected_object(self) -> None:
        if self._envelope is None or self._selected_object_id is None:
            self.best_view.setPixmap(QtGui.QPixmap())
            self.best_view.setText("Best view unavailable · select an object")
            self.best_view_caption.setText("Best view unavailable · select an object")
            self.object_details.setText("No selected object")
            return
        # Selection may outlive a merge/removal publication. Resolve only with
        # the current canonical owner snapshot before looking up hierarchy data.
        try:
            objects = self._envelope.sources.objects
            if objects is None:
                raise KeyError("pinned object snapshot unavailable")
            canonical = objects.resolve_id(self._selected_object_id)
            node = self._envelope.hierarchy.nodes.get(canonical)
            if node is None or node.kind != "object":
                raise KeyError("selected object absent from pinned hierarchy")
        except (KeyError, ValueError) as exc:
            self.best_view.setPixmap(QtGui.QPixmap())
            self.best_view.setText("Best view unavailable · selected object unavailable")
            self.best_view_caption.setText("Best view unavailable · selected object unavailable")
            self.object_details.setText(f"Selection unavailable · {exc}")
            return
        self._selection_was_alias = self._selection_was_alias or canonical != self._selected_object_id
        self._selected_object_id = canonical
        self.graph_view.select_object(canonical)
        self.spatial_view.select_object(canonical)
        self.object_details.setText(self._object_detail(canonical, alias=self._selection_was_alias))
        view = next((item for item in self._envelope.sources.best_views
                     if self._envelope.sources.objects is not None and
                     self._envelope.sources.objects.resolve_id(item.object_id) == canonical), None)
        if view is None and self._best_view_provider is not None:
            try:view = self._best_view_provider(self._envelope, canonical)
            except (OSError, ValueError):view = None
        if view is None:
            self.best_view.setPixmap(QtGui.QPixmap())
            self.best_view.setText(f"Best view unavailable · no evidence image for {canonical[:8]}")
            self.best_view_caption.setText(f"Best view unavailable · no evidence image for {canonical[:8]}")
        else:
            self.best_view.setPixmap(QtGui.QPixmap.fromImage(_qimage_rgb(view.pixels)).scaled(
                self.best_view.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation,
            ))
            caption = f"Best view · frame {view.source.sensor_id}:{view.source.frame_index} · object r{view.object_revision} · evidence {view.evidence_ref[:12]}"
            self.best_view.setToolTip(caption)
            self.best_view_caption.setText(caption)

    def _refresh_telemetry(self) -> None:
        envelope = self._envelope
        if envelope is None:
            return
        metrics = envelope.metrics
        output_age = envelope.publication_age_ns(self._now_ns(), self._clock_domain or envelope.clock_domain)
        self.subtitle.setText(f"{envelope.hierarchy.episode_id}  /  publication {envelope.publication_sequence}")
        count = lambda kind: sum(n.kind == kind for n in envelope.hierarchy.nodes.values())
        now = self._now_ns()
        rgb = envelope.sources.rgb
        rgb_age = (now-rgb.capture_monotonic_ns if rgb is not None
                   and rgb.clock_domain == (self._clock_domain or envelope.clock_domain)
                   and now >= rgb.capture_monotonic_ns else None)
        rgb_label = "—" if rgb_age is None else f"{rgb_age / 1e6:.0f} ms"
        hidden = self.graph_view.hidden_count
        nav = self.map_view._nav
        map_label = "unavailable" if nav is None else f"r{nav.revision} · {nav.source.sensor_id}:{nav.source.frame_index}"
        self.overview.setText(f"RGB  {rgb_label}     /     MAP  {map_label}     /     "
                              f"OBJECTS  {count('object')}     /     ROOMS  {count('region')}     /     "
                              f"DROPS  {metrics.dropped_count}     /     GRAPH HIDDEN  {hidden}")
        stale_region = any(n.kind == "region" and n.attributes.get("stale") for n in envelope.hierarchy.nodes.values())
        badge = "STALE PUBLICATION" if output_age > 300_000_000 else "ROOMS STALE" if stale_region else "SNAPSHOT RECEIVED"
        self.status_badge.setText(badge)
        self.status_badge.setStyleSheet("color:#db9630" if "STALE" in badge else "color:#60beb1")
        def frame(key):
            return "unavailable" if key is None else f"{key.sensor_id}:{key.frame_index}"
        ages = ", ".join(f"{name}={('unavailable' if age is None else f'{age / 1e6:.1f} ms')}"
                          for name, age in sorted(metrics.source_age_ns.items())) or "none"
        stale = "stale rooms" if any(node.kind == "region" and node.attributes.get("stale")
                                       for node in envelope.hierarchy.nodes.values()) else "rooms current"
        nav = self.map_view._nav
        def origin(value):
            if value is None:
                return "unavailable"
            return f"{frame(value.source)} · capture {value.capture_monotonic_ns} ns · {value.clock_domain}"
        observation = envelope.sources.observation
        origins = (f"Display map: {origin(nav)} · RGB: {origin(envelope.sources.rgb)} · "
                   f"detector: {origin(None if observation is None else observation.image)}")
        self.telemetry.setText(
            f"Episode {envelope.hierarchy.episode_id} · hierarchy r{envelope.hierarchy.revision} · "
            f"object/map/region r{envelope.hierarchy.object_revision}/{envelope.hierarchy.map_revision}/{envelope.hierarchy.region_revision} · {stale}\n"
            f"Captured {frame(metrics.captured_frame_id)} · processed {frame(metrics.processed_frame_id)} · "
            f"published {frame(metrics.published_frame_id)} · drops {metrics.dropped_count} · replaced {metrics.replaced_count} · "
            f"profile {metrics.actual_profile or 'unavailable'}\n"
            f"Source ages: {ages} · hierarchy map age {envelope.hierarchy.source_map_age_ns / 1e6:.1f} ms · "
            f"display publication age {output_age / 1e6:.1f} ms\n{origins}"
        )

    def _send_command(self, action: str) -> None:
        if self._control is None:
            self.command_status.setText("Control unavailable")
            return
        status = self._control.request(action)
        self._show_command_status(status)

    def _refresh_command_status(self) -> None:
        if self._control is None:
            return
        statuses = self._control.latest_statuses()
        if statuses:
            self._show_command_status(statuses[-1])

    def _show_command_status(self, status: UiCommandStatus) -> None:
        reason = f" · {status.reason}" if status.reason else ""
        self.command_status.setText(f"{status.action.title()} request {status.request_uuid[:8]} · {status.state}{reason}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-exit-ms", type=int, default=None,
                        help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.smoke_exit_ms is not None and args.smoke_exit_ms < 1:
        raise SystemExit("--smoke-exit-ms must be positive")
    return run_desktop(smoke_exit_ms=args.smoke_exit_ms)


def run_desktop(
    publication_reader: Callable[[], DisplayEnvelope | None] | DisplayPublisher | None = None,
    control_client: UiControlClient | None = None,
    *,
    clock_domain: str | None = None,
    smoke_exit_ms: int | None = None,
    best_view_provider=None,
    cloud_reader=None,
) -> int:
    """Application entrypoint for a P09-owned external-process adapter."""
    if smoke_exit_ms is not None and (type(smoke_exit_ms) is not int or smoke_exit_ms < 1):
        raise ValueError("smoke_exit_ms must be a positive integer or None")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    window = DashboardWindow(publication_reader, control_client, clock_domain=clock_domain, best_view_provider=best_view_provider, cloud_reader=cloud_reader)
    if cloud_reader is not None:
        app.aboutToQuit.connect(cloud_reader.close)
    window.show()
    print("NEUSYMNAV_UI_READY", flush=True)
    if smoke_exit_ms is not None:
        QtCore.QTimer.singleShot(smoke_exit_ms, app.quit)
    return app.exec_()


if __name__ == "__main__":  # ``python -m neusymnav.visualization.desktop``
    raise SystemExit(main())


__all__ = ["DashboardWindow", "MapWidget", "main", "run_desktop"]
