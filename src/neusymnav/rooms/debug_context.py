"""Build bounded requests from one exact native display source, off the Qt thread."""
from dataclasses import replace
from types import MappingProxyType
from ..backends.hydra.query import HydraSceneGraphQuery
from .requests import make_room_label_request
from .debug_types import RoomLabelDebugJob

MAX_DEBUG_ROOMS=32
MAX_SOURCE_NODES=10000
MAX_SOURCE_EDGES=30000
MAX_SNAPSHOT_NODES=256


def build_debug_jobs(graph,taxonomy,offered_ns):
    if graph.status!='available' or graph.stale or graph.replay_required:return ()
    if len(graph.nodes)>MAX_SOURCE_NODES or len(graph.edges)>MAX_SOURCE_EDGES:raise ValueError('debug source graph exceeds cap')
    if sum(n.layer_id==4 for n in graph.nodes)>MAX_DEBUG_ROOMS:raise ValueError('debug room cap exceeded')
    s=graph.native_metadata.get('room_label_input')
    if (not isinstance(s,dict) and not isinstance(s,MappingProxyType)) or s.get('schema_version')!=1:raise ValueError('explicit native room semantics unavailable')
    if s.get('graph_revision')!=graph.graph_revision or s.get('input_prefix_sha256')!=graph.input_prefix_sha256:raise ValueError('room semantics source mismatch')
    digest=s.get('snapshot_sha256')
    if not isinstance(digest,str) or len(digest)!=64 or any(c not in '0123456789abcdef' for c in digest):raise ValueError('native snapshot digest missing')
    transform=graph.native_metadata.get('last_transform') or {}
    q=HydraSceneGraphQuery(graph,taxonomy,labelspace_id=(graph.last_source or {}).get('labelspace_id'),
        labelspace_hash=(graph.last_source or {}).get('labelspace_hash'),semantic_labels=s.get('semantic_labels',{}),calibration_id=transform.get('calibration_id'))
    support={'episode_id':graph.episode_id,'run_id':graph.run_id,'geometry_revision':graph.graph_revision,
        'input_prefix_sha256':graph.input_prefix_sha256,'geometry_hash':digest,'status':'available',
        'source_hashes':{'native_display_snapshot_sha256':digest}}
    requests=make_room_label_request(q,None,support,world_epoch=graph.native_metadata.get('graph_world_epoch'))
    by_native={n.native_id:n for n in graph.nodes};by_id={n.node_id:n for n in graph.nodes}
    jobs=[]
    for request in requests:
        wanted={request.key.room_id}
        for obj in request.context.objects:
            n=by_native.get(obj.native_id);seen=set()
            while n is not None and n.node_id not in seen:
                wanted.add(n.node_id);seen.add(n.node_id);n=by_id.get(n.parent_id)
        if len(wanted)>MAX_SNAPSHOT_NODES:raise ValueError('snapshot graph cap exceeded')
        nodes=tuple(n for n in graph.nodes if n.node_id in wanted)
        edges=tuple(e for e in graph.edges if e.source in wanted and e.target in wanted)
        md=dict(graph.native_metadata);md['room_label_input']={**s,'semantic_labels':{n.native_id:s['semantic_labels'].get(n.native_id) for n in nodes if n.layer_id==2}};md['debug_subset']={'source_node_count':len(graph.nodes),'source_edge_count':len(graph.edges),'selected_room':request.key.room_id}
        subset=replace(graph,nodes=nodes,edges=edges,node_counts=MappingProxyType({str(i):sum(n.layer_id==i for n in nodes) for i in range(8)}),native_metadata=MappingProxyType(md))
        jobs.append(RoomLabelDebugJob(request,subset,offered_ns))
    return tuple(jobs)
