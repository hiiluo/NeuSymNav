"""Conservative footprint membership, adapted from Fusion unified_scene_graph.

Uses actual supplied XY footprint; absent one, uses the object's XY AABB.
Boundary touch, partial outside support and multiple rooms abstain. No camera
position, semantic label or latest navigation raster participates in ownership.
"""
from dataclasses import dataclass
import math
import numpy as np
from ..contracts import ObjectSnapshot,RegionSnapshot
from ..regions._types import Polygon2D
from ..regions.geometry import point_in_polygon,intersection_area,valid_ring,_segments_intersect


def _boundary(point,ring,eps=1e-7):
    x,y=point
    for i,a in enumerate(ring):
        b=ring[(i+1)%len(ring)];dx,dy=b[0]-a[0],b[1]-a[1];den=dx*dx+dy*dy
        t=0. if den==0 else max(0.,min(1.,((x-a[0])*dx+(y-a[1])*dy)/den))
        if math.hypot(x-a[0]-t*dx,y-a[1]-t*dy)<=eps:return True
    return False



def footprint_membership(footprint,regions):
    """Return status/owner/candidates/reason for a validated simple XY polygon."""
    ring=tuple(map(tuple,footprint))
    if not valid_ring(ring):return 'unavailable',None,(),'invalid_footprint_geometry'
    footprint=Polygon2D(ring);area=footprint.net_area_m2
    possible=[];owners=[];touch=False
    for key,region in sorted(regions.items()):
        outer=tuple(map(tuple,region.polygon))
        low=np.min(region.polygon,axis=0);high=np.max(region.polygon,axis=0)
        f_low=np.min(footprint.outer,axis=0);f_high=np.max(footprint.outer,axis=0)
        if np.any(high<f_low-1e-9) or np.any(f_high<low-1e-9):continue
        if not valid_ring(outer):return 'unavailable',None,(),'invalid_region_geometry'
        poly=Polygon2D(outer)
        crossing=any(_segments_intersect(a,ring[(i+1)%len(ring)],b,outer[(j+1)%len(outer)]) for i,a in enumerate(ring) for j,b in enumerate(outer))
        overlap=intersection_area(footprint,poly)
        if overlap>1e-12 or crossing:
            possible.append(key)
            touch |= crossing or any(_boundary(p,outer) for p in ring)
            if not crossing and all(point_in_polygon(p,poly) and not _boundary(p,outer) for p in ring) and math.isclose(overlap,area,rel_tol=1e-8,abs_tol=1e-10):owners.append(key)
    candidates=tuple(possible)
    if len(possible)==1 and owners==possible and not touch:return 'assigned',possible[0],candidates,'footprint_inside_one_region'
    if possible:return 'ambiguous',None,candidates,'footprint_crosses_or_touches_boundary'
    return 'unassigned',None,(),'outside_region_geometry'


@dataclass(frozen=True)
class Membership:
    object_id: str
    region_id: str|None
    status: str
    candidates: tuple[str,...]
    object_revision: int
    source_map_revision: int
    region_revision: int
    reason: str

class MembershipResolver:
    def resolve(self,objects:ObjectSnapshot,regions:RegionSnapshot)->tuple[Membership,...]:
        if objects.episode_id!=regions.episode_id:raise ValueError('membership episode mismatch')
        result=[]
        for key,obj in sorted(objects.objects.items()):
            if regions.stale:status,owner,candidates,reason='unavailable',None,(),'stale_region_snapshot'
            elif obj.floor_id!=regions.floor_id:status,owner,candidates,reason='unavailable',None,(),'floor_mismatch'
            elif not regions.regions:status,owner,candidates,reason='unavailable',None,(),'no_region_geometry'
            else:
                low,high=obj.bounds
                footprint=obj.footprint_xy
                if footprint is None:footprint=np.array([[low[0],low[1]],[high[0],low[1]],[high[0],high[1]],[low[0],high[1]]])
                status,owner,candidates,reason=footprint_membership(footprint,regions.regions)
            result.append(Membership(objects.resolve_id(key),owner,status,candidates,objects.revision,regions.source_map_revision,regions.revision,reason))
        return tuple(result)
