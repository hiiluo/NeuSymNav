"""Observed visited-place backbone ported from NewOH3DSG/scene_graph/places.

Explicit visit admission supplies robot XY. Every published route is independently
replanned through P03's measured floor/clearance and cylindrical footprint gate.
World anchors survive moving NavSnapshot windows; no cell index is reused across
origins. Source spacing/nearest reachable predecessor behavior is retained.
"""
from dataclasses import dataclass,replace
import math
from uuid import uuid5,NAMESPACE_URL
from ..contracts import NavSnapshot
from ..mapping.occupancy import RobotGeometry
from ..navigation.planner import Planner

@dataclass(frozen=True)
class PlaceNode:
    place_id:str
    xy:tuple[float,float]
    first_map_revision:int
    visited_count:int

@dataclass(frozen=True)
class PlaceEdge:
    source_id:str
    target_id:str
    path_cells:tuple[tuple[int,int],...]
    length_m:float
    map_revision:int

@dataclass(frozen=True)
class PlaceSnapshot:
    episode_id:str
    map_revision:int
    places:tuple[PlaceNode,...]
    edges:tuple[PlaceEdge,...]

class PlaceBuilder:
    MIN_SPACING_M=.75
    MAX_PLACES=1000
    def __init__(self,robot:RobotGeometry):
        self.robot=robot;self._planner=Planner(robot);self._places=[];self._edges=[];self._episode=None;self._last_visit_revision=-1

    @staticmethod
    def _cell(nav,xy):
        col,row=(math.floor((xy[i]-nav.origin_xy[i])/nav.resolution_m) for i in (0,1))
        return row,col

    def _route(self,nav,start,end):return self._planner.plan(nav,start,self._cell(nav,end))

    def snapshot_for(self,nav:NavSnapshot)->PlaceSnapshot:
        if self._episode is not None and nav.episode_id!=self._episode:raise ValueError('place episode mismatch')
        places=tuple(p for p in self._places if p.first_map_revision<=nav.revision and self._route(nav,p.xy,p.xy).success)
        by_id={p.place_id:p for p in places};edges=[]
        for source,target in self._edges:
            if source not in by_id or target not in by_id:continue
            route=self._route(nav,by_id[source].xy,by_id[target].xy)
            if route.success:edges.append(PlaceEdge(source,target,route.cells,route.cost_m,nav.revision))
        return PlaceSnapshot(nav.episode_id,nav.revision,places,tuple(edges))

    def update(self,nav:NavSnapshot,robot_xy:tuple[float,float],*,pose_source=None,capture_monotonic_ns=None,clock_domain=None,exception_tag=None)->PlaceSnapshot:
        if (pose_source!=nav.source or capture_monotonic_ns!=nav.capture_monotonic_ns or clock_domain!=nav.clock_domain):
            raise ValueError('place pose provenance must match source NavSnapshot')
        if len(robot_xy)!=2 or not all(math.isfinite(v) for v in robot_xy):raise ValueError('finite robot XY required')
        if exception_tag not in (None,'portal','turn'):raise ValueError('invalid place exception')
        if self._episode is not None and nav.episode_id!=self._episode:raise ValueError('place episode mismatch')
        if nav.revision<self._last_visit_revision:raise ValueError('place visit revision moved backward')
        self._episode=nav.episode_id;self._last_visit_revision=nav.revision
        current=self.snapshot_for(nav)
        # Route's raster center is the world anchor; observed pose is used only
        # for selection. This matches source cell-node semantics.
        row,col=self._cell(nav,robot_xy)
        xy=(nav.origin_xy[0]+(col+.5)*nav.resolution_m,nav.origin_xy[1]+(row+.5)*nav.resolution_m)
        if not self._route(nav,xy,xy).success:return current
        for i,p in enumerate(self._places):
            if math.dist(xy,p.xy)<1e-9:
                self._places[i]=replace(p,visited_count=p.visited_count+1);return self.snapshot_for(nav)
        if len(self._places)>=self.MAX_PLACES:return current
        if exception_tag is None and min((math.dist(xy,p.xy) for p in current.places),default=math.inf)<self.MIN_SPACING_M:return current
        options=[]
        for p in current.places:
            route=self._route(nav,p.xy,xy)
            if route.success:options.append((route.cost_m,p.place_id))
        if self._places and not options:return current
        key='place:'+str(uuid5(NAMESPACE_URL,repr((nav.episode_id,xy))))
        self._places.append(PlaceNode(key,xy,nav.revision,1))
        if options:self._edges.append((min(options)[1],key))
        return self.snapshot_for(nav)
