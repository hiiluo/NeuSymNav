"""Single-floor projection of immutable object/map/region publications.

Composition pins the accepted source map independently of latest navigation.
A region worker rejection retains geometry as stale and prevents membership.
"""
from __future__ import annotations
from ..contracts import (ObjectSnapshot,NavSnapshot,RegionSnapshot,HierarchySnapshot,
                         HierarchyNode,HierarchyEdge,age_ns)
from .membership import MembershipResolver,footprint_membership
from .places import PlaceBuilder
from ..regions.geometry import room_center

class HierarchyComposer:
    def __init__(self,*,robot=None):
        self.membership=MembershipResolver();self.places=None if robot is None else PlaceBuilder(robot)
        self._revision=0;self._episode=None;self._last_revisions=None

    def observe_place(self,nav,robot_xy,*,pose_source=None,capture_monotonic_ns=None,clock_domain=None,exception_tag=None):
        if self.places is None:raise ValueError('place admission requires explicit robot geometry')
        return self.places.update(nav,robot_xy,pose_source=pose_source,capture_monotonic_ns=capture_monotonic_ns,clock_domain=clock_domain,exception_tag=exception_tag)

    def compose(self,objects:ObjectSnapshot,nav:NavSnapshot,regions:RegionSnapshot,*,latest_nav_revision:int,now_ns:int,clock_domain:str)->HierarchySnapshot:
        if not isinstance(objects,ObjectSnapshot) or not isinstance(nav,NavSnapshot) or not isinstance(regions,RegionSnapshot):raise ValueError('typed input snapshots required')
        if objects.episode_id!=nav.episode_id or regions.episode_id!=nav.episode_id:raise ValueError('hierarchy episode mismatch')
        if self._episode is not None and nav.episode_id!=self._episode:raise ValueError('new episode requires a new composer')
        if nav.revision!=regions.source_map_revision:raise ValueError('nav must match accepted region source map')
        if type(latest_nav_revision) is not int or latest_nav_revision<nav.revision:raise ValueError('latest nav revision precedes pinned map')
        revisions=(objects.revision,nav.revision,regions.revision,latest_nav_revision)
        if self._last_revisions is not None and any(a<b for a,b in zip(revisions,self._last_revisions)):
            raise ValueError('hierarchy input revisions moved backward')
        if len(objects.objects)>1000 or len(regions.regions)>4096:
            raise ValueError('hierarchy object/region cap exceeded')
        age=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,clock_domain)
        building='building:'+nav.episode_id;floor='floor:'+regions.floor_id
        if set(regions.regions)&({building,floor}|set(objects.objects)):
            raise ValueError('hierarchy namespace collision')
        nodes={building:HierarchyNode(building,'building',{'scope':'single_floor','episode_id':nav.episode_id}),
               floor:HierarchyNode(floor,'floor',{'floor_id':regions.floor_id,'floor_z_m':nav.floor_z_m,'floor_datum_source':nav.floor_datum_source,'calibration_hash':nav.calibration_hash})}
        edges=[];statuses={}
        def edge(source,target,kind,**provenance):
            edges.append(HierarchyEdge(source,target,kind,'assigned',{'algorithm':'neusymnav_p06_v1',**provenance},objects.revision,nav.revision,regions.revision))
        edge(building,floor,'contains',scope='single_floor')
        for key,r in sorted(regions.regions.items()):
            nodes[key]=HierarchyNode(key,'region',{'floor_id':regions.floor_id,'polygon':r.polygon,'center_xy':room_center(r.polygon),'center_method':'area_centroid_or_interior_clearance_v1','predecessor_ids':r.predecessor_ids,'stale':regions.stale,'preprocessing_policy':'extended_unknown_boundary','geometry_only':True,'holes_supported':False})
            edge(floor,key,'contains',geometry_source_map_revision=regions.source_map_revision,stale=regions.stale)
        for key,r in sorted(regions.regions.items()):
            for target in sorted(r.adjacency):
                if key<target:edge(key,target,'region_adjacent_to',motion_certificate=False,structural_only=True,stale=regions.stale)
        memberships=self.membership.resolve(objects,regions)
        for m in memberships:
            obj=objects.objects[m.object_id]
            nodes[m.object_id]=HierarchyNode(m.object_id,'object',{'floor_id':obj.floor_id,'category':obj.category,'raw_label':obj.raw_label,'centroid':obj.centroid,'bounds':obj.bounds,'lifecycle':obj.lifecycle,'evidence_refs':obj.evidence_refs,'membership_status':m.status,'membership_candidates':m.candidates,'membership_reason':m.reason,'aliases':tuple(sorted(alias for alias in objects.aliases if objects.resolve_id(alias)==m.object_id))})
            statuses[m.object_id]=m.status
            if m.region_id is not None:edge(objects.resolve_id(m.object_id),m.region_id,'in_region',policy='geometry_footprint_xy',reason=m.reason,candidates=m.candidates)
        if self.places is not None:
            places=self.places.snapshot_for(nav)
            for p in places.places:
                nodes[p.place_id]=HierarchyNode(p.place_id,'place',{'xy':p.xy,'floor_id':regions.floor_id,'visited_count':p.visited_count,'footprint_validated':True,'map_revision':nav.revision,'robot_geometry_id':nav.robot_geometry_id})
                edge(floor,p.place_id,'contains',observed_visit=True,footprint_validated=True)
                if not regions.stale:
                    radius=self.places.robot.radius_m+self.places.robot.margin_m
                    x,y=p.xy
                    status,owner,candidates,reason=footprint_membership(((x-radius,y-radius),(x+radius,y-radius),(x+radius,y+radius),(x-radius,y+radius)),regions.regions)
                    if owner is not None:edge(owner,p.place_id,'region_contains_place',footprint_validated=True,policy='conservative_footprint_rectangle')
            for e in places.edges:edge(e.source_id,e.target_id,'place_connected_to',path_cells=e.path_cells,length_m=e.length_m,footprint_validated=True,robot_geometry_id=nav.robot_geometry_id,clearance_required_m=self.places.robot.height_m,radius_with_margin_m=self.places.robot.radius_m+self.places.robot.margin_m,motion_certificate=False)
        statuses['regions']='unavailable' if regions.stale else 'assigned'
        publication=HierarchySnapshot(nav.episode_id,self._revision+1,objects.revision,nav.revision,regions.revision,nodes,tuple(edges),statuses,latest_nav_revision,age)
        self._revision+=1;self._episode=nav.episode_id;self._last_revisions=revisions
        return publication
