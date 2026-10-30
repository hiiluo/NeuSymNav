"""Room/Floor anchors above measured objects and historical Z-up RGB-D."""
import math
import numpy as np
from PyQt5 import QtCore, QtGui, QtWidgets

from .hierarchy_view import hierarchy_rows, hierarchy_links


class SpatialSceneWidget(QtWidgets.QWidget):
    object_selected = QtCore.pyqtSignal(str)
    MAX_NODES = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 120)
        self.setMouseTracking(True)
        self.envelope = None
        self.cloud = None
        self.selected = None
        self.show_retired = False
        self.height_filter_enabled = True
        self.height_min_m, self.height_max_m = 0., 2.20
        self._filtered_cloud = None
        self._filtered_options = None
        self._filtered_arrays = None
        self.yaw, self.pitch, self.zoom = .55, .95, 1.
        self.pan = np.zeros(2)
        self.nodes = {}; self.edges = (); self.polygons = ()
        self.hidden_count = self.unassigned_count = 0
        self._episode = None
        self._domain = None
        self._center = None; self._span = 1.
        self._extent = np.ones(3)
        self._drag = self._press = None
        self._screen_nodes = {}
        self._raster_key = None; self._raster = None
        self.now_ns = 0
        self.cloud_error = None
        self.setToolTip('Left drag: orbit · Shift-left drag: zoom · right drag: pan · wheel: zoom · double-click: fit · click object: evidence')

    def set_envelope(self, envelope):
        if (self._episode,self._domain) != (envelope.hierarchy.episode_id,envelope.clock_domain):
            self.cloud = None; self.selected = None; self._center = None
            self.yaw, self.pitch, self.zoom = .55, .95, 1.
            self.pan[:] = 0
            self._episode = envelope.hierarchy.episode_id
            self._domain = envelope.clock_domain
        self.envelope = envelope
        self._build_nodes()
        self._invalidate()

    def _build_nodes(self):
        if self.envelope is None:
            return
        from ..regions.geometry import room_center, valid_ring
        envelope = self.envelope
        rows = hierarchy_rows(envelope)
        nodes = {}; polygons = []; floor_geometry = {}; hidden = unassigned = 0
        # Geometry anchors are rebuilt for every publication, independent of
        # persistent IDs. Display heights never mutate measured source geometry.
        for row in rows:
            attrs = envelope.hierarchy.nodes[row.node_id].attributes
            measured_position = measured_bounds = None
            if row.kind == 'object':
                if attrs.get('lifecycle') == 'retired' and not self.show_retired and row.node_id != self.selected:
                    hidden += 1
                    continue
                measured_position = np.asarray(attrs.get('centroid', ()), dtype=float)
                measured_bounds = np.asarray(attrs.get('bounds', ()), dtype=float)
                position = measured_position.copy()
                if row.status != 'assigned':
                    unassigned += 1
                label = str(attrs.get('category') or attrs.get('raw_label') or 'object')[:24] + ' · ' + row.node_id[:6]
            elif row.kind == 'room':
                try:
                    polygon = np.asarray(attrs.get('polygon', ()), dtype=float)
                except (ValueError, TypeError):
                    hidden += 1
                    continue
                if polygon.ndim != 2 or polygon.shape[1] != 2 or len(polygon) < 3 or not np.isfinite(polygon).all():
                    hidden += 1
                    continue
                if not valid_ring(tuple(map(tuple, polygon))):
                    hidden += 1
                    continue
                try:
                    center = attrs.get('center_xy')
                    xy = np.asarray(room_center(polygon) if center is None else center, dtype=float)
                except (ValueError, TypeError):
                    hidden += 1
                    continue
                if xy.shape != (2,) or not np.isfinite(xy).all():
                    hidden += 1
                    continue
                floor_node = envelope.hierarchy.nodes.get(row.parent_id)
                floor_z = float(floor_node.attributes.get('floor_z_m', 0.)) if floor_node is not None else 0.
                position = np.r_[xy, floor_z]
                polygons.append(np.column_stack((polygon, np.full(len(polygon), floor_z))))
                relative = polygon-polygon[0]
                nxt = np.roll(relative, -1, axis=0)
                area = abs(float(np.sum(relative[:,0]*nxt[:,1]-nxt[:,0]*relative[:,1])))/2
                if area > 0 and row.parent_id is not None:
                    floor_geometry.setdefault(row.parent_id, []).append((xy, area))
                label = 'Room · ' + row.node_id[-8:] + (' · STALE' if row.stale else '')
            else:
                # Floor XY is filled from its own source-assigned rooms below.
                position = np.array([0., 0., float(attrs.get('floor_z_m', 0.))])
                label = row.label
            if position.shape != (3,) or not np.isfinite(position).all():
                hidden += 1
                continue
            if len(nodes) >= self.MAX_NODES:
                hidden += 1
                continue
            nodes[row.node_id] = dict(position=position, row=row, label=label, attrs=attrs,
                                      measured_position=measured_position, measured_bounds=measured_bounds)
        for node in nodes.values():
            if node['row'].kind != 'floor':
                continue
            rooms = floor_geometry.get(node['row'].node_id, ())
            if rooms:
                # Area-weighted room anchors from this floor's source-assigned
                # geometry. Hidden rooms still contribute; objects never do.
                node['position'][:2] = np.average([xy for xy,_ in rooms], axis=0,
                                                weights=[area for _,area in rooms])
            else:
                node['label'] += ' · room geometry unavailable'
                nav = envelope.sources.nav
                if nav is not None:
                    node['position'][:2] = np.asarray(nav.origin_xy)+np.array(nav.states.shape[::-1])*nav.resolution_m/2
        if nodes:
            positions = np.array([n['position'] for n in nodes.values()])
            measured_tops = [float(n['measured_bounds'][1,2]) for n in nodes.values()
                             if n['measured_bounds'] is not None and n['measured_bounds'].shape == (2,3)
                             and np.isfinite(n['measured_bounds']).all()]
            measured_top = max(measured_tops, default=float(positions[:,2].max()))
            gap = max(.5, float(np.ptp(positions[:,:2], axis=0).max())*.12)
            base = max(measured_top, float(positions[:,2].max()))+gap
            heights = {'room': base, 'floor': base+gap}
            for node in nodes.values():
                if node['row'].kind in heights:
                    node['position'][2] = heights[node['row'].kind]
        edges = hierarchy_links(envelope, nodes)
        self.nodes, self.edges, self.polygons = nodes, tuple(edges), tuple(polygons)
        self.hidden_count, self.unassigned_count = hidden, unassigned
        # Fit again when geometry/layers change; user orbit/zoom remain intact.
        self._center = None

    def set_cloud(self, cloud):
        if (cloud is None or self.envelope is None or cloud.episode_id != self._episode
                or cloud.clock_domain != self.envelope.clock_domain): return
        if self.cloud is cloud: return
        first = self.cloud is None
        self.cloud = cloud
        if first: self._center = None
        self._invalidate()

    def select_object(self, node_id):
        if self.selected == node_id: return
        self.selected = node_id
        self._build_nodes()
        self.update()

    def reset_view(self):
        self._center = None; self.zoom = 1.; self.pan[:] = 0
        self._invalidate()

    def zoom_by(self, factor):
        self.zoom=float(np.clip(self.zoom*factor,.15,20))
        self._invalidate()

    def configure_height_filter(self, enabled, minimum=None, maximum=None):
        low = self.height_min_m if minimum is None else float(minimum)
        high = self.height_max_m if maximum is None else float(maximum)
        if not (math.isfinite(low) and math.isfinite(high) and 0 <= low < high <= 10):
            raise ValueError('display height range must satisfy 0 <= low < high <= 10 m')
        self.height_filter_enabled = bool(enabled)
        self.height_min_m, self.height_max_m = low, high
        self._center = None
        self._invalidate()

    def _floor_elevation(self):
        if self.envelope is None:
            return None
        if self.envelope.sources.nav is not None:
            return self.envelope.sources.nav.floor_z_m
        for node in self.envelope.hierarchy.nodes.values():
            if node.kind == 'floor':
                value = node.attributes.get('floor_z_m')
                if isinstance(value, (int,float)) and math.isfinite(value):
                    return float(value)
        return None

    def visible_cloud(self):
        if self.cloud is None:
            return np.empty((0,3),np.float32), np.empty((0,3),np.uint8)
        options = (self.height_filter_enabled,self._floor_elevation(),self.height_min_m,self.height_max_m)
        if self._filtered_cloud is self.cloud and self._filtered_options == options:
            return self._filtered_arrays
        points, colors = self.cloud.points, self.cloud.colors
        if options[0] and options[1] is not None:
            height = points[:,2]-options[1]
            keep = height < options[3]
            if options[2] > 0:
                keep &= height > options[2]
            points, colors = points[keep], colors[keep]
            points.setflags(write=False); colors.setflags(write=False)
        self._filtered_cloud, self._filtered_options = self.cloud, options
        self._filtered_arrays = points, colors
        return self._filtered_arrays

    def _invalidate(self):
        self._raster_key = None
        self.update()

    def _view(self):
        area = self.rect().adjusted(10, 28, -10, -30)
        geometry = [n['position'][None,:] for n in self.nodes.values()]
        cloud_points,_ = self.visible_cloud()
        if len(cloud_points): geometry.append(cloud_points)
        geometry.extend(self.polygons)
        if self._center is None and geometry:
            points = np.concatenate(geometry)
            # Fit the observed scene, rather than a long region boundary or a
            # few far-depth outliers. All points/nodes remain available to pan.
            if len(cloud_points)>100:
                low, high = np.quantile(cloud_points,[.01,.99],axis=0)
                anchors = np.array([n['position'] for n in self.nodes.values()])
                if len(anchors):
                    low = np.minimum(low, anchors.min(axis=0))
                    high = np.maximum(high, anchors.max(axis=0))
            else:
                low, high = points.min(axis=0), points.max(axis=0)
            self._center = (low+high)/2
            self._span = max(float(np.max(high-low)), 1.)
            self._extent = np.maximum(high-low,.5)
        center = np.zeros(3) if self._center is None else self._center
        corners = np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])*self._extent
        projected,_ = self._project(corners,area,np.zeros(3),1.)
        span = np.maximum(np.ptp(projected,axis=0),.5)
        scale = .88*min(max(1,area.width())/span[0],max(1,area.height())/span[1])*self.zoom
        return area, center, scale

    def _project(self, xyz, area, center, scale):
        xyz = np.asarray(xyz, dtype=float).reshape(-1,3)-center
        c,s = math.cos(self.yaw),math.sin(self.yaw)
        x = c*xyz[:,0]-s*xyz[:,1]
        y = s*xyz[:,0]+c*xyz[:,1]
        cp,sp = math.cos(self.pitch),math.sin(self.pitch)
        vertical = sp*y+cp*xyz[:,2]
        # Right-handed camera basis: screen-right cross screen-up points
        # toward the camera. Larger depth is nearer (eye above negative Y).
        depth = -cp*y+sp*xyz[:,2]
        return np.column_stack((area.center().x()+self.pan[0]+x*scale,
            area.center().y()+self.pan[1]-vertical*scale)), depth

    def _cloud_image(self, area, center, scale):
        key = (self.width(),self.height(),self.yaw,self.pitch,self.zoom,tuple(self.pan),
               tuple(center),self._span,None if self.cloud is None else self.cloud.revision,
               self.height_filter_enabled,self._floor_elevation(),self.height_min_m,self.height_max_m)
        if self._raster_key == key: return self._raster
        pixels = np.zeros((max(1,self.height()),max(1,self.width()),4),np.uint8)
        cloud_points,cloud_colors = self.visible_cloud()
        if len(cloud_points):
            xy, depth = self._project(cloud_points,area,center,scale)
            xy = np.rint(xy).astype(int)
            keep = ((xy[:,0]>=area.left()) & (xy[:,0]<=area.right()) & (xy[:,1]>=area.top()) & (xy[:,1]<=area.bottom()))
            ids = np.flatnonzero(keep)
            # Resolve all four splat offsets in one shared depth buffer. A far
            # point's later offset must never overwrite a nearer surface.
            expanded = np.tile(ids,4)
            offsets = np.repeat(np.array([[0,0],[1,0],[0,1],[1,1]]),len(ids),axis=0)
            target = xy[expanded]+offsets
            x = np.clip(target[:,0],0,self.width()-1)
            y = np.clip(target[:,1],0,self.height()-1)
            pixel = y*self.width()+x
            nearest = np.full(self.width()*self.height(),-np.inf)
            np.maximum.at(nearest,pixel,depth[expanded])
            visible = depth[expanded] == nearest[pixel]
            pixels[y[visible],x[visible],:3] = cloud_colors[expanded[visible]]
            pixels[y[visible],x[visible],3] = 210
        image = QtGui.QImage(pixels.data,pixels.shape[1],pixels.shape[0],pixels.strides[0],QtGui.QImage.Format_RGBA8888).copy()
        self._raster_key, self._raster = key, image
        return image

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(),QtGui.QColor('#0c1421'))
        area, center, scale = self._view()
        painter.drawImage(0,0,self._cloud_image(area,center,scale))
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.save(); painter.setClipRect(area)
        def project(points): return self._project(points,area,center,scale)[0]
        for polygon in self.polygons:
            painter.setPen(QtGui.QPen(QtGui.QColor('#3c7397'),1,QtCore.Qt.DashLine))
            points = project(polygon)
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(*p) for p in np.vstack((points,points[0]))]))
        self._screen_nodes = {k:QtCore.QPointF(*project(n['position'])[0]) for k,n in self.nodes.items()}
        for source,target,kind in self.edges:
            adjacency = kind == 'region_adjacent_to'
            pen = QtGui.QPen(QtGui.QColor('#5adce8' if adjacency else '#8aa4bb'),
                            1.8 if adjacency else 1.3,
                            QtCore.Qt.DashLine if adjacency else QtCore.Qt.SolidLine)
            painter.setPen(pen)
            painter.drawLine(self._screen_nodes[source],self._screen_nodes[target])
        label_rects=[]
        painter.setFont(QtGui.QFont('DejaVu Sans',9))
        ordered = sorted(self.nodes, key=lambda k:({'floor':0,'room':1,'object':2}[self.nodes[k]['row'].kind], k != self.selected,k))
        for key in ordered:
            node=self.nodes[key];row=node['row'];pos=self._screen_nodes[key]
            color = '#69baff' if row.kind == 'room' else '#60beb1' if row.kind == 'floor' else '#efb451'
            if node['attrs'].get('lifecycle') == 'retired': color='#768294'
            pen=QtGui.QPen(QtGui.QColor('#ffffff' if key==self.selected else '#152437'),2 if key==self.selected else 1)
            if row.kind=='object' and row.status!='assigned': pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(pen);painter.setBrush(QtGui.QColor(color))
            radius=7 if row.kind in {'room', 'floor'} or key==self.selected else 5
            painter.drawEllipse(pos,radius,radius)
            if key==self.selected:
                bounds=np.asarray(node['attrs'].get('bounds',()),dtype=float)
                if bounds.shape==(2,3):
                    corners=np.array([[bounds[i,0],bounds[j,1],bounds[k,2]] for i in (0,1) for j in (0,1) for k in (0,1)])
                    screen=project(corners);painter.setPen(QtGui.QPen(QtGui.QColor(color),1))
                    for a in range(8):
                        for bit in (1,2,4):
                            b=a^bit
                            if a<b:painter.drawLine(QtCore.QPointF(*screen[a]),QtCore.QPointF(*screen[b]))
            label=node['label']+(' · '+row.status if row.kind=='object' and row.status!='assigned' else '')
            metrics=painter.fontMetrics();width=min(245,metrics.horizontalAdvance(label)+8)
            height=metrics.height()+4
            candidates = [QtCore.QRectF(x,y,width,height) for x,y in (
                (pos.x()+10,pos.y()-height), (pos.x()-width-10,pos.y()-height),
                (pos.x()+10,pos.y()+4), (pos.x()-width-10,pos.y()+4))]
            rect = next((r for r in candidates if area.contains(r.toRect())
                         and not any(r.intersects(old) for old in label_rects)), None)
            if rect is None:
                if key != self.selected:
                    continue
                rect = candidates[0]
            if row.kind == 'object' and key != self.selected and len(label_rects)>=24:
                continue
            painter.fillRect(rect,QtGui.QColor(12,20,33,200));painter.setPen(QtGui.QColor('#e3edf7'))
            painter.drawText(rect.adjusted(3,0,-3,0),QtCore.Qt.AlignVCenter,metrics.elidedText(label,QtCore.Qt.ElideRight,int(width)-6))
            label_rects.append(rect)
        painter.restore()
        painter.setFont(QtGui.QFont('DejaVu Sans',9));painter.setPen(QtGui.QColor('#a6ccec'))
        graph = 'Waiting for spatial graph' if self.envelope is None else f'Graph object r{self.envelope.hierarchy.object_revision} / map r{self.envelope.hierarchy.map_revision} · measured Objects / Room + Floor anchors'
        painter.drawText(10,19,graph)
        if self.cloud is None:
            cloud='RGB-D cloud unavailable · waiting for committed source assets'
        else:
            age=max(0,self.now_ns-self.cloud.last_capture_ns)/1e9
            visible_count=len(self.visible_cloud()[0])
            cut = ''
            if self.height_filter_enabled:
                cut = (f' · cutaway {self.height_min_m:.2f}–{self.height_max_m:.2f}m above floor'
                       if self._floor_elevation() is not None else ' · cutaway unavailable: no floor datum')
            cloud=f'{visible_count:,}/{len(self.cloud.points):,} visible points{cut} · historical RGB-D · latest input {self.cloud.last_source.sensor_id}:{self.cloud.last_source.frame_index} · input age {age:.1f}s (displayed points may be older)'
        if self.cloud_error: cloud+=' · cloud read unavailable'
        details=f'{cloud} · {self.unassigned_count} not assigned · {self.hidden_count} hidden/retired · left orbit / Shift-drag zoom / right pan / wheel zoom / double-click fit'
        painter.setPen(QtGui.QColor('#93a3b5'))
        painter.drawText(10,self.height()-9,painter.fontMetrics().elidedText(details,QtCore.Qt.ElideRight,self.width()-20))
        self.setToolTip(details+'\n'+self.tool_instructions())

    @staticmethod
    def tool_instructions():
        return 'Teal: Floor; blue: Room geometry center; gold: Object. Objects and selected bounds retain measured XYZ in RGB-D. Room/Floor Z is a hierarchy display layout, not physical height. Solid lines: assigned membership. Cyan dashed lines: structural Room–Room connectivity, not a robot passage certificate. Unknown membership stays disconnected.'

    def mousePressEvent(self,event):
        self._drag=self._press=event.pos()

    def mouseMoveEvent(self,event):
        if self._drag is not None and event.buttons():
            delta=event.pos()-self._drag
            if event.buttons() & QtCore.Qt.LeftButton and event.modifiers() & QtCore.Qt.ShiftModifier:
                self.zoom_by(2.**float(np.clip(-delta.y()/100.,-4.,4.)))
            elif event.buttons() & (QtCore.Qt.RightButton|QtCore.Qt.MiddleButton): self.pan+=np.array([delta.x(),delta.y()])
            else:
                self.yaw+=delta.x()*.008
                self.pitch=float(np.clip(self.pitch+delta.y()*.008,-1.55,1.55))
            self._drag=event.pos();self._invalidate()
        else:
            close=[(math.hypot(event.x()-p.x(),event.y()-p.y()),k) for k,p in self._screen_nodes.items()]
            if close and min(close)[0]<12:
                key=min(close)[1];self.setToolTip(self.nodes[key]['row'].label+'\n'+key+'\n'+self.tool_instructions())

    def mouseReleaseEvent(self,event):
        if event.button()==QtCore.Qt.LeftButton and not event.modifiers() & QtCore.Qt.ShiftModifier and self._press is not None and (event.pos()-self._press).manhattanLength()<4:
            close=[(math.hypot(event.x()-p.x(),event.y()-p.y()),k) for k,p in self._screen_nodes.items() if self.nodes[k]['row'].kind=='object']
            if close and min(close)[0]<12:
                key=min(close)[1];self.select_object(key);self.object_selected.emit(key)
        self._drag=self._press=None

    def mouseDoubleClickEvent(self,event): self.reset_view()

    def wheelEvent(self,event):
        delta=event.angleDelta().y() or event.pixelDelta().y()*6
        self.zoom_by(math.exp(float(np.clip(delta/120.*math.log(1.15),-2.,2.))))
        event.accept()
