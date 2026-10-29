"""Bounded, selectable scene graph drawn from the current display projection."""
from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from .hierarchy_view import hierarchy_rows


COLORS = {"building": "#90a4bc", "floor": "#6eafe8", "region": "#b687e1",
          "place": "#60beb1", "object": "#e1a65b"}


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
        self.setMinimumSize(240, 220)
        self.node_items = {}
        self.hidden_count = 0
        self._selecting = False
        self.scene().selectionChanged.connect(self._selection_changed)

    def set_envelope(self, envelope):
        self._selecting = True
        try:
            self.scene().clear()
            self.node_items = {}
            rank = {"building": 0, "floor": 1, "region": 2, "place": 3, "object": 4}
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
                if row.stale:
                    label += " · STALE"
                labels[row.node_id] = label
            # Leave room for the actual label including STALE, rather than
            # squeezing long region captions into a fixed 72-unit rank gap.
            column_step = max(110, max((metrics.horizontalAdvance(label)+40
                                       for label in labels.values()), default=0))
            positions = {}
            height = max(180, max((len(v) for v in columns.values()), default=1)*36)
            for col, entries in columns.items():
                for index, row in enumerate(entries):
                    positions[row.node_id] = QtCore.QPointF(25+col*column_step, (index+1)*height/(len(entries)+1))
            links = 0
            for row in rows:
                if row.parent_id in positions and links < 1200:
                    a, b = positions[row.parent_id], positions[row.node_id]
                    path = QtGui.QPainterPath(a)
                    mid = (a.x()+b.x())/2
                    path.cubicTo(mid, a.y(), mid, b.y(), b.x(), b.y())
                    edge = self.scene().addPath(path, QtGui.QPen(QtGui.QColor("#37516c"), 1.5))
                    edge.setZValue(-1)
                    links += 1
            for row in rows:
                pos = positions[row.node_id]
                color = QtGui.QColor("#db9630" if row.stale else COLORS.get(row.kind, "#90a4bc"))
                if row.kind == "region":
                    item = self.scene().addPolygon(QtGui.QPolygonF([
                        QtCore.QPointF(0, -9), QtCore.QPointF(9, 0),
                        QtCore.QPointF(0, 9), QtCore.QPointF(-9, 0)]))
                elif row.kind in {"floor", "place", "building"}:
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
                text.setPos(pos.x()+13, pos.y()-10) if row.kind == 'object' else text.setPos(pos.x()-10, pos.y()+12)
                self.node_items[row.node_id] = item
            if not rows:
                text = self.scene().addSimpleText("Waiting for scene graph")
                text.setBrush(QtGui.QColor("#93a3b5"))
            self.scene().setSceneRect(self.scene().itemsBoundingRect().adjusted(-24, -24, 24, 24))
            self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)
        finally:
            self._selecting = False

    def select_object(self, node_id):
        self._selecting = True
        try:
            self.scene().clearSelection()
            item = self.node_items.get(node_id)
            if item is not None and item.data(1) == "object":
                item.setSelected(True)
            self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)
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
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), QtCore.Qt.KeepAspectRatio)
