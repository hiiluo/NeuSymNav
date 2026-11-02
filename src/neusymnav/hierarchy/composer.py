"""Single-floor projection of immutable object/map/region publications.

Composition pins the accepted source map independently of latest navigation.
A region worker rejection retains geometry as stale and prevents membership.
"""
from __future__ import annotations
import hashlib
import json
from ..contracts import (ObjectSnapshot,NavSnapshot,RegionSnapshot,RoomPipelinePublication,
                         HierarchySnapshot,HierarchyNode,HierarchyEdge,age_ns)
from .membership import MembershipResolver,footprint_membership
from .places import PlaceBuilder
from ..regions.geometry import room_center
from ..rooms.owner import DoorEvidence,RoomOwner

class HierarchyComposer:
    def __init__(self,*,robot=None):
        self.membership=MembershipResolver();self.places=None if robot is None else PlaceBuilder(robot)
        self._revision=0;self._episode=None;self._last_revisions=None
        self.rooms=RoomOwner();self._room_signature=None;self._room_publication=None

    @staticmethod
    def _door_evidence(objects,nav,regions):
        """Turn committed, source-bound door object geometry into weak evidence."""
        evidence=[]
        for object_id,state in sorted(objects.objects.items()):
            labels={str(value).strip().casefold() for value in (state.category,state.raw_label) if value}
            if ('door' not in labels or not state.evidence_refs or state.footprint_xy is None
                    or state.source.episode_id!=nav.episode_id or state.floor_id!=regions.floor_id
                    or state.lifecycle in {'dormant','retired','merged'}
                    or state.clock_domain!=nav.clock_domain
                    or state.last_seen_ns>nav.capture_monotonic_ns):
                continue
            frame={'episode_id':state.source.episode_id,'sensor_id':state.source.sensor_id,
                   'frame_index':state.source.frame_index}
            refs=tuple(sorted(set(state.evidence_refs)))
            identity=json.dumps([object_id,frame,refs],sort_keys=True,separators=(',',':'))
            evidence_id='door-evidence:'+hashlib.sha256(identity.encode('utf-8')).hexdigest()
            source_age_ns=None
            if state.clock_domain==nav.clock_domain:
                source_age_ns=nav.capture_monotonic_ns-state.last_seen_ns
            provenance=json.dumps({
                'object_id':object_id,'object_revision':state.revision,
                'evidence_refs':list(refs),'source_frame':frame,
                'source_last_seen_ns':state.last_seen_ns,
                'source_clock_domain':state.clock_domain,
                'age_at_room_map_capture_ns':source_age_ns,
            },sort_keys=True,separators=(',',':'))
            evidence.append(DoorEvidence(evidence_id,objects.episode_id,state.source,
                tuple(tuple(float(v) for v in p) for p in state.footprint_xy),provenance))
            if len(evidence)>=256:
                break
        return tuple(evidence)

    def observe_place(self,nav,robot_xy,*,pose_source=None,capture_monotonic_ns=None,clock_domain=None,exception_tag=None):
        if self.places is None:raise ValueError('place admission requires explicit robot geometry')
        return self.places.update(nav,robot_xy,pose_source=pose_source,capture_monotonic_ns=capture_monotonic_ns,clock_domain=clock_domain,exception_tag=exception_tag)

    def compose(self,objects:ObjectSnapshot,nav:NavSnapshot,regions:RegionSnapshot,*,latest_nav_revision:int,now_ns:int,clock_domain:str,room_pipeline:RoomPipelinePublication|None=None)->HierarchySnapshot:
        if not isinstance(objects,ObjectSnapshot) or not isinstance(nav,NavSnapshot) or not isinstance(regions,RegionSnapshot):raise ValueError('typed input snapshots required')
        if room_pipeline is not None and not isinstance(room_pipeline,RoomPipelinePublication):raise ValueError('room_pipeline must be RoomPipelinePublication or None')
        if objects.episode_id!=nav.episode_id or regions.episode_id!=nav.episode_id:raise ValueError('hierarchy episode mismatch')
        if self._episode is not None and nav.episode_id!=self._episode:raise ValueError('new episode requires a new composer')
        if nav.revision!=regions.source_map_revision:raise ValueError('nav must match accepted region source map')
        if type(latest_nav_revision) is not int or latest_nav_revision<nav.revision:raise ValueError('latest nav revision precedes pinned map')
        revisions=(objects.revision,nav.revision,regions.revision,latest_nav_revision)
        if self._last_revisions is not None and any(a<b for a,b in zip(revisions,self._last_revisions)):
            raise ValueError('hierarchy input revisions moved backward')
        if len(objects.objects)>1000 or len(regions.regions)>4096:
            raise ValueError('hierarchy object/region cap exceeded')
        # Room evidence is updated only from the accepted, source-bound region
        # input. Re-composing the same immutable sources (for example, to
        # refresh latest-nav age) must not count as another observation.
        room_signature=(objects.episode_id,objects.revision,nav.revision,regions.revision,
                        regions.source_map_revision,regions.stale)
        if room_signature!=self._room_signature:
            door_evidence=self._door_evidence(objects,nav,regions)
            self._room_publication=self.rooms.update(nav,regions,door_evidence=door_evidence)
            self._room_signature=room_signature
        room_publication=self._room_publication
        rooms_by_region={}
        if (room_publication is not None and not room_publication.stale
                and room_publication.episode_id==nav.episode_id
                and room_publication.source_map_revision==nav.revision
                and not regions.stale):
            for room in room_publication.rooms:
                if room.status=='retired':
                    continue
                for region_id in room.region_ids:
                    rooms_by_region.setdefault(region_id,[]).append(room)
        age=age_ns(nav.capture_monotonic_ns,nav.clock_domain,now_ns,clock_domain)
        building='building:'+nav.episode_id;floor='floor:'+regions.floor_id
        if set(regions.regions)&({building,floor}|set(objects.objects)):
            raise ValueError('hierarchy namespace collision')
        nodes={building:HierarchyNode(building,'building',{'scope':'single_floor','episode_id':nav.episode_id}),
               floor:HierarchyNode(floor,'floor',{'floor_id':regions.floor_id,'floor_z_m':nav.floor_z_m,'floor_datum_source':nav.floor_datum_source,'calibration_hash':nav.calibration_hash,'room_debug':room_publication.to_debug() if room_publication is not None else {}})}
        edges=[];statuses={}
        def edge(source,target,kind,**provenance):
            edges.append(HierarchyEdge(source,target,kind,'assigned',{'algorithm':'neusymnav_p06_v1',**provenance},objects.revision,nav.revision,regions.revision))
        edge(building,floor,'contains',scope='single_floor')
        for key,r in sorted(regions.regions.items()):
            room_candidates=rooms_by_region.get(key,[])
            stable_room=room_candidates[0] if len(room_candidates)==1 else None
            if len(room_candidates)>1:
                room_status='ambiguous'
                room_reason='multiple_active_rooms_claim_region'
                room_candidate_ids=tuple(sorted({candidate.room_id for candidate in room_candidates})[:128])
            elif stable_room is not None:
                room_status=stable_room.status
                room_reason=stable_room.reason
                room_candidate_ids=(stable_room.room_id,)
            else:
                room_status='unavailable' if room_publication is None or room_publication.stale or regions.stale else 'unassigned'
                room_reason='room_source_stale' if room_status=='unavailable' else 'no_stable_room_assignment'
                room_candidate_ids=()
            room_attributes={
                'stable_room_id':stable_room.room_id if stable_room is not None else None,
                'stable_room_status':room_status,
                'stable_room_reason':room_reason,
                'stable_room_candidates':room_candidate_ids,
                'stable_room_support_count':stable_room.support_count if stable_room is not None else 0,
                'stable_room_source_map_revision':room_publication.source_map_revision if room_publication is not None else -1,
                'stable_room_stale':room_publication.stale if room_publication is not None else True,
            }
            nodes[key]=HierarchyNode(key,'region',{'floor_id':regions.floor_id,'polygon':r.polygon,'center_xy':room_center(r.polygon),'center_method':'area_centroid_or_interior_clearance_v1','predecessor_ids':r.predecessor_ids,'stale':regions.stale,'preprocessing_policy':'extended_unknown_boundary','geometry_only':True,'holes_supported':False,**room_attributes})
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
        source_region_nodes={}
        source_status='unavailable'
        if room_pipeline is not None and room_pipeline.episode_id==nav.episode_id:
            source_regions=room_pipeline.regions
            source_map=room_pipeline.accepted_map
            source_ready=(source_regions is not None and source_map is not None
                          and not room_pipeline.regions_stale and not room_pipeline.replay_required
                          and not source_regions.stale
                          and source_regions.source_map_revision==room_pipeline.accepted_map_revision
                          and source_map.revision==room_pipeline.accepted_map_revision)
            if source_regions is not None and source_map is not None:
                domain_tag=hashlib.sha256(room_pipeline.map_domain_id.encode()).hexdigest()[:16]
                source_region_nodes={key:f"source-region:{domain_tag}:{key}" for key in source_regions.regions}
                if any(node_id in nodes for node_id in source_region_nodes.values()):
                    raise ValueError('source region namespace collision')
                for key,region in sorted(source_regions.regions.items()):
                    node_id=source_region_nodes[key]
                    stale=not source_ready
                    nodes[node_id]=HierarchyNode(node_id,'source_region',{
                        'floor_id':source_regions.floor_id,'polygon':region.polygon,
                        'raw_region_id':key,'map_domain_id':room_pipeline.map_domain_id,
                        'source_map_revision':source_regions.source_map_revision,
                        'accepted_map_revision':room_pipeline.accepted_map_revision,
                        'm5_revision':room_pipeline.m5_revision,
                        'accepted_frame_id':source_map.source.frame_index,
                        'source_capture_monotonic_ns':source_map.capture_monotonic_ns,
                        'source_clock_domain':source_map.clock_domain,
                        'stale':stale,'geometry_only':True,
                        'motion_certificate':False,
                    })
                    edge_kind='contains_source_region'
                    edges.append(HierarchyEdge(floor,node_id,edge_kind,
                        'assigned' if source_regions.floor_id==regions.floor_id else 'unavailable',
                        {'algorithm':'rebuild_m5_source_v1','map_domain_id':room_pipeline.map_domain_id,
                         'source_map_revision':source_regions.source_map_revision,
                         'm5_revision':room_pipeline.m5_revision,'stale':stale,
                         'geometry_only':True,'motion_certificate':False},
                        objects.revision,source_regions.source_map_revision,source_regions.revision,
                        room_pipeline.map_domain_id))
                for key,region in sorted(source_regions.regions.items()):
                    for target in sorted(region.adjacency):
                        if key<target:
                            edges.append(HierarchyEdge(source_region_nodes[key],source_region_nodes[target],
                                'source_region_adjacent_to','assigned' if source_ready else 'unavailable',
                                {'algorithm':'rebuild_m5_source_v1','map_domain_id':room_pipeline.map_domain_id,
                                 'source_map_revision':source_regions.source_map_revision,
                                 'm5_revision':source_regions.revision,
                                 'structural_only':True,'motion_certificate':False,'stale':not source_ready},
                                objects.revision,source_regions.source_map_revision,source_regions.revision,
                                room_pipeline.map_domain_id))
                source_status=('assigned' if source_ready and source_regions.floor_id==regions.floor_id
                               else 'unavailable')
                for object_id,obj in objects.objects.items():
                    if (not source_ready or source_regions.floor_id!=regions.floor_id
                            or obj.floor_id!=source_regions.floor_id or not source_regions.regions):
                        membership=('unavailable',None,(),
                            'rebuild_source_stale_or_floor_mismatch' if not source_ready or source_regions.floor_id!=regions.floor_id or obj.floor_id!=source_regions.floor_id else 'no_source_regions')
                    else:
                        low,high=obj.bounds
                        footprint=obj.footprint_xy
                        if footprint is None:
                            footprint=((low[0],low[1]),(high[0],low[1]),(high[0],high[1]),(low[0],high[1]))
                        membership=footprint_membership(footprint,source_regions.regions)
                    status,owner,candidates,reason=membership
                    prior=nodes[object_id]
                    nodes[object_id]=HierarchyNode(object_id,'object',dict(prior.attributes,
                        rebuild_region_membership_status=status,
                        rebuild_region_membership_id=owner,
                        rebuild_region_membership_candidates=tuple(candidates),
                        rebuild_region_membership_reason=reason,
                        rebuild_region_map_domain_id=room_pipeline.map_domain_id,
                        rebuild_region_map_revision=room_pipeline.accepted_map_revision,
                        rebuild_region_m5_revision=room_pipeline.m5_revision,
                        rebuild_region_stale=not source_ready))
                    selected=([owner] if owner is not None else list(candidates) if status=='ambiguous' else [])
                    for region_key in selected:
                        if region_key not in source_region_nodes:continue
                        edges.append(HierarchyEdge(object_id,source_region_nodes[region_key],
                            'in_source_region','assigned' if status=='assigned' else 'ambiguous',
                            {'algorithm':'geometry_footprint_xy_rebuild_m5_v1','status':status,
                             'reason':reason,'candidates':tuple(candidates),
                             'map_domain_id':room_pipeline.map_domain_id,
                             'source_map_revision':source_regions.source_map_revision,
                             'm5_revision':source_regions.revision,'motion_certificate':False},
                            objects.revision,source_regions.source_map_revision,source_regions.revision,
                            room_pipeline.map_domain_id))
        statuses['rebuild_regions']=source_status
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
