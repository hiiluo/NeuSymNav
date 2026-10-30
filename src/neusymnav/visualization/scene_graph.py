"""Bounded, selectable scene graph drawn from the current display projection."""
from __future__ import annotations
import math

from PyQt5 import QtCore, QtGui, QtWidgets

from .hierarchy_view import hierarchy_rows, hierarchy_links


COLORS = {"floor": "#60beb1", "room": "#69baff", "object": "#e1a65b"}


class SceneGraphWidget(QtWidgets.QGraphicsView):
    object_selected = QtCore.pyqtSignal(str)
    MAX_NODES = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setRenderHint(QtGui.QPainter.Antialiasing)
        self.setBackgroundBrush(QtGui.QColor("#0c1421"))
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setDragMode(self.ScrollHandDrag)
        self.setMinimumSize(240, 120)
        self.setTransformationAnchor(self.AnchorUnderMouse)
        self._manual_view = False
        self._episode = None
        self.node_items = {}
        self.hidden_count = 0
        self._selecting = False
        self.scene().selectionChanged.connect(self._selection_changed)

    def set_envelope(self, envelope):
        if self._episode != envelope.hierarchy.episode_id:
            self._manual_view = False
            self._episode = envelope.hierarchy.episode_id
        center = self.mapToScene(self.viewport().rect().center())
        self._selecting = True
        try:
            self.scene().clear()
            self.node_items = {}
            rank = {"floor": 0, "room": 1, "object": 2}
            rows = sorted(hierarchy_rows(envelope), key=lambda r: (rank.get(r.kind, 5), r.node_id))
            self.hidden_count = max(0, len(rows)-self.MAX_NODES)
            rows = rows[:self.MAX_NODES]
            columns = {}
            for row in rows:
                columns.setdefault(rank.get(row.kind, 5), []).append(row)
            # Stable ID ordering, distinct ranks; never create an inferred edge
            # for an unassigned object just to make the graph look connected.
            labels = {}
            font = QtGui.QFont("Sans Serif", 9)
            metrics = QtGui.QFontMetrics(font)
            for row in rows:
                node = envelope.hierarchy.nodes[row.node_id]
                label = str(node.attributes.get("category") or row.kind.title())[:24]
                if row.kind == "object":
                    label += " · "+row.node_id[:6]
                    if row.status != 'assigned':
                        label += ' · '+row.status
                elif row.kind == "room":
                    label = 'Room · '+row.node_id[-8:]
                elif row.kind == "floor":
                    label = 'Floor · '+str(node.attributes.get('floor_id', row.node_id))
                if row.stale:
                    label += " · STALE"
                labels[row.node_id] = label
            # Top-down ranks mirror Floor > Room > Object in the spatial view.
            # Horizontal spacing includes the full captions, including STALE.
            column_step = max(110, max((metrics.horizontalAdvance(label)+40
                                       for label in labels.values()), default=0))
            positions = {}
            rank_step = max(110, metrics.height()+80)
            for rank_index, entries in columns.items():
                for index, row in enumerate(entries):
                    positions[row.node_id] = QtCore.QPointF(
                        (index-(len(entries)-1)/2)*column_step, 25+rank_index*rank_step)
            for row in rows:
                if row.kind == 'floor':
                    children = [positions[child.node_id].x() for child in rows if child.parent_id == row.node_id]
                    if children:
                        positions[row.node_id].setX(sum(children)/len(children))
            for source, target, kind in hierarchy_links(envelope, positions):
                a, b = positions[source], positions[target]
                adjacency = kind == 'region_adjacent_to'
                path = QtGui.QPainterPath(a)
                if adjacency:
                    # Bow above the room row so intermediate room nodes do
                    # not obscure same-level topology.
                    lift = min(75., max(30., abs(b.x()-a.x())*.15))
                    path.cubicTo(a.x(), a.y()-lift, b.x(), b.y()-lift, b.x(), b.y())
                else:
                    mid = (a.y()+b.y())/2
                    path.cubicTo(a.x(), mid, b.x(), mid, b.x(), b.y())
                pen = QtGui.QPen(QtGui.QColor('#5adce8' if adjacency else '#8aa4bb'),
                                1.8 if adjacency else 1.5,
                                QtCore.Qt.DashLine if adjacency else QtCore.Qt.SolidLine)
                edge = self.scene().addPath(path, pen)
                edge.setData(0, (source, target, kind))
                edge.setToolTip('Room connectivity · structural only; robot passage not certified'
                                if adjacency else 'Assigned membership')
                edge.setZValue(-1)
            for row in rows:
                pos = positions[row.node_id]
                color = QtGui.QColor("#db9630" if row.stale else COLORS.get(row.kind, "#90a4bc"))
                if row.kind == "room":
                    item = self.scene().addPolygon(QtGui.QPolygonF([
                        QtCore.QPointF(0, -9), QtCore.QPointF(9, 0),
                        QtCore.QPointF(0, 9), QtCore.QPointF(-9, 0)]))
                elif row.kind == "floor":
                    item = self.scene().addRect(-7, -7, 14, 14)
                else:
                    item = self.scene().addEllipse(-7, -7, 14, 14)
                item.setBrush(color)
                pen = QtGui.QPen(color.lighter(140), 1.5)
                if row.status in {"unassigned", "ambiguous", "unavailable"}:
                    pen.setStyle(QtCore.Qt.DashLine)
                item.setPen(pen)
                item.setPos(pos)
                item.setData(0, row.node_id)
                item.setData(1, row.kind)
                item.setToolTip(row.label+"\n"+row.node_id)
                item.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, row.kind == "object")
                text = self.scene().addSimpleText(labels[row.node_id], font)
                text.setBrush(QtGui.QColor("#dee7f1"))
                text.setPos(pos.x()-metrics.horizontalAdvance(labels[row.node_id])/2, pos.y()+12)
                self.node_items[row.node_id] = item
            if not rows:
                text = self.scene().addSimpleText("Waiting for scene graph")
                text.setBrush(QtGui.QColor("#93a3b5"))
            self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-24, -24, 24, 24))
            if self._manual_view:
                self.centerOn(center)
            else:
                self.fit_view()
        finally:
            self._selecting = False

    def select_object(self, node_id):
        self._selecting = True
        try:
            self.scene().clearSelection()
            item = self.node_items.get(node_id)
            if item is not None and item.data(1) == "object":
                item.setSelected(True)
        finally:
            self._selecting = False

    def _selection_changed(self):
        if not self._selecting:
            for item in self.scene().selectedItems():
                if item.data(1) == "object":
                    self.object_selected.emit(item.data(0))
                    break

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._manual_view and not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def fit_view(self):
        self._manual_view = False
        self.resetTransform()
        self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def zoom_by(self, factor):
        current = math.hypot(self.transform().m11(), self.transform().m12())
        target = min(20., max(.0001, current*factor))
        self._manual_view = True
        self.scale(target/max(current,1e-9), target/max(current,1e-9))

    def wheelEvent(self, event):
        delta = event.angleDelta().y() or event.pixelDelta().y()*6
        if event.modifiers() & QtCore.Qt.ControlModifier:
            self._manual_view = True
            self.rotate(delta/120.*10.)
        else:
            self.zoom_by(math.exp(min(2., max(-2., delta/120.*math.log(1.15)))))
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._manual_view = True
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.fit_view()
        event.accept()
