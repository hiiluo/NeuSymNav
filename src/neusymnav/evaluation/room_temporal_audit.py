"""Offline native-room temporal audit on observed place support; no room GT inferred."""
from collections import Counter,defaultdict
import math


def _partition_pairs(a,b):
    choose2=lambda n:n*(n-1)//2
    ca=Counter(v for v in a.values() if v is not None)
    cb=Counter(v for v in b.values() if v is not None)
    both=Counter((a[i],b[i]) for i in a if a[i] is not None and b[i] is not None)
    disagreement=sum(choose2(n) for n in ca.values())+sum(choose2(n) for n in cb.values())-2*sum(choose2(n) for n in both.values())
    count=choose2(len(a))
    return {'pair_count':count,'pair_disagreement_count':disagreement,
            'pair_disagreement_fraction':disagreement/count if count else None}


def _places(snapshot):
    nodes=snapshot['summary']['nodes']
    rooms={n['native_id'] for n in nodes if n['layer_id']==4}
    result={}
    for n in nodes:
        if n['layer_id']!=3:continue
        pid=n['native_id'];point=n['position'];parent=n['parent_native_id']
        if pid in result:raise ValueError('duplicate place ID')
        if len(point)!=3 or not all(type(x) in (int,float) and math.isfinite(x) for x in point):raise ValueError('invalid place coordinate')
        if parent is not None and parent not in rooms:raise ValueError('place parent is not an exported room')
        result[pid]={'xyz':point,'room':parent}
    return result


def audit_revisions(snapshots,*,stable_displacement_m=.25,minimum_overlap_points=2,minimum_overlap_fraction=.2):
    if not snapshots:raise ValueError('revision snapshots required')
    if not math.isfinite(stable_displacement_m) or stable_displacement_m<0:raise ValueError('invalid displacement threshold')
    if minimum_overlap_points<1 or not 0<minimum_overlap_fraction<=1:raise ValueError('invalid overlap policy')
    episode=snapshots[0]['episode_id'];previous=None;series=[];transitions=[]
    for snapshot in snapshots:
        if snapshot['episode_id']!=episode:raise ValueError('cross-episode audit is invalid')
        if previous is not None and snapshot['graph_revision']!=previous['snapshot']['graph_revision']+1:raise ValueError('revisions must be contiguous')
        if previous is not None:
            for key in ['config_sha256','clock_domain','calibration_hash']:
                if key in snapshot and key in previous['snapshot'] and snapshot[key]!=previous['snapshot'][key]:raise ValueError('revision provenance changed')
        points=_places(snapshot);labels={i:p['room'] for i,p in points.items()}
        roi={i:p for i,p in points.items() if -.9<=p['xyz'][0]<=.4 and -2.8<=p['xyz'][1]<=-.8}
        room_counts=Counter(v for v in labels.values() if v is not None)
        boundary=[]
        for edge in snapshot.get('place_edges',[]):
            a,b=edge['source'],edge['target']
            if a not in points or b not in points:raise ValueError('boundary edge references absent place')
            if labels[a] is not None and labels[b] is not None and labels[a]!=labels[b]:
                boundary.append({'source':a,'target':b,'midpoint_xyz':[(x+y)/2 for x,y in zip(points[a]['xyz'],points[b]['xyz'])],'weight_m':edge['weight_m']})
        series.append({'graph_revision':snapshot['graph_revision'],'place_count':len(points),'room_count':len(room_counts),'room_sizes':dict(room_counts),'unassigned_count':sum(v is None for v in labels.values()),'qualitative_roi_place_count':len(roi),'roi_room_ids':sorted({p['room'] for p in roi.values() if p['room'] is not None}),'boundary_edges':boundary,'boundary_scope':'observed_graph_cross_room_edges_not_physical_wall_boundary','input_prefix_sha256':snapshot['input_prefix_sha256']})
        if previous is not None:
            old=previous['points'];common=set(old)&set(points)
            stable={i for i in common if math.dist(old[i]['xyz'],points[i]['xyz'])<=stable_displacement_m}
            a={i:old[i]['room'] for i in stable};b={i:points[i]['room'] for i in stable}
            overlap=Counter((a[i],b[i]) for i in stable if a[i] is not None and b[i] is not None)
            old_counts=Counter(v for v in a.values() if v is not None);new_counts=Counter(v for v in b.values() if v is not None)
            children=defaultdict(list);parents=defaultdict(list)
            for (left,right),count in overlap.items():
                if count>=minimum_overlap_points and count/old_counts[left]>=minimum_overlap_fraction:children[left].append({'room_id':right,'overlap':count})
                if count>=minimum_overlap_points and count/new_counts[right]>=minimum_overlap_fraction:parents[right].append({'room_id':left,'overlap':count})
            transitions.append({'from_revision':previous['snapshot']['graph_revision'],'to_revision':snapshot['graph_revision'],
                'common_place_count':len(common),'stable_common_place_count':len(stable),'moved_common_place_count':len(common-stable),'new_place_count':len(set(points)-set(old)),'removed_place_count':len(set(old)-set(points)),
                'raw_room_id_change_count':sum(a[i] is not None and b[i] is not None and a[i]!=b[i] for i in stable),
                'became_assigned_count':sum(a[i] is None and b[i] is not None for i in stable),'became_unassigned_count':sum(a[i] is not None and b[i] is None for i in stable),
                'split_events':[{'previous_room_id':room,'children':sorted(parts,key=lambda p:p['room_id'])} for room,parts in sorted(children.items()) if len(parts)>1],
                'merge_events':[{'current_room_id':room,'parents':sorted(parts,key=lambda p:p['room_id'])} for room,parts in sorted(parents.items()) if len(parts)>1],
                'both_assigned_comparison':_partition_pairs({i:a[i] for i in stable if a[i] is not None and b[i] is not None},{i:b[i] for i in stable if a[i] is not None and b[i] is not None}),
                **_partition_pairs(a,b)})
        previous={'points':points,'snapshot':snapshot}
    return {'schema_version':1,'scope':'offline_actual_native_membership_on_persistent_stationary_place_ids','episode_id':episode,
            'policy':{'stable_displacement_m':stable_displacement_m,'minimum_overlap_points':minimum_overlap_points,'minimum_overlap_fraction':minimum_overlap_fraction},
            'quality_claim':{'accuracy_claimed':False,'reason':'independent_annotation_required'},
            'lineage_scope':'overlap_events_on_observed_place_ids_not_confirmed_physical_room_split_merge',
            'revisions':series,'transitions':transitions}
