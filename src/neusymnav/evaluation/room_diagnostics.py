"""Offline summaries of native RoomFinder diagnostics; never a room-GT oracle."""
from __future__ import annotations
from copy import deepcopy
from html import escape
import math


def passes_strict_native_cutoff(value, threshold):
    for number in (value, threshold):
        if type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError('finite numeric cutoff required')
    return value > threshold


def diagnose_room_finder_result(value):
    if type(value) is not dict or type(value.get('room_finder')) is not dict:
        raise ValueError('native room_finder result required')
    rf = value['room_finder']; cfg = rf['config']
    minimum = cfg['min_component_size']
    if type(minimum) is not int or minimum < 1:
        raise ValueError('invalid native min_component_size')
    threshold = rf['selected_threshold_m']
    if threshold is not None: passes_strict_native_cutoff(0., threshold)
    raw = rf['raw_components']; seeds = rf['seeds_before_neighbors']; clusters = rf['post_neighbor_clusters']
    if not all(type(c) is list for c in (raw, seeds, clusters)):
        raise ValueError('bounded native component lists required')
    if any(len(c) > 100_000 for c in (raw, seeds, clusters)):
        raise ValueError('component count budget exceeded')
    for group in (raw, seeds, clusters):
        seen = set()
        for c in group:
            ids = c['place_ids']
            if (type(ids) is not list or any(type(i) is not str or not i or len(i)>128 for i in ids)
                    or len(set(ids)) != len(ids) or type(c['size']) is not int or c['size'] != len(ids)
                    or seen.intersection(ids)):
                raise ValueError('native component IDs/size/partition mismatch')
            seen.update(ids)
    for c in raw:
        if type(c['retained_as_seed']) is not bool or c['retained_as_seed'] != (c['size'] >= minimum):
            raise ValueError('native size filtering mismatch')
    retained = {tuple(sorted(c['place_ids'])) for c in raw if c['retained_as_seed']}
    if retained != {tuple(sorted(c['place_ids'])) for c in seeds}:
        raise ValueError('raw components do not match native seeds')
    count = rf['room_count']
    if type(count) is not int or count < 0 or count != sum(c['accepted_as_room'] is True for c in clusters):
        raise ValueError('native output room count mismatch')
    original_seed_ids = set(i for c in seeds for i in c['place_ids'])
    assigned = set(i for c in clusters if c['accepted_as_room'] for i in c['place_ids'])
    if not seeds: code = 'no_retained_seed'
    elif len(seeds) == 1 and any(not c['retained_as_seed'] for c in raw): code = 'one_seed_after_component_size_filter'
    elif len(seeds) == 1: code = 'one_retained_seed'
    elif count < len(seeds): code = 'post_cluster_room_filter_requires_inspection'
    else: code = 'multiple_seeds_survive'
    return {'diagnosis': {'code': code, 'selected_threshold_m': threshold,
        'raw_component_count': len(raw), 'retained_seed_count': len(seeds),
        'retained_seed_sizes': [c['size'] for c in seeds],
        'pruned_component_sizes': [c['size'] for c in raw if not c['retained_as_seed']],
        'post_cluster_sizes': [c['size'] for c in clusters], 'room_count': count,
        'neighbor_propagated_place_count': len(assigned-original_seed_ids),
        'physical_room_count_inferred': False,
        'limitation': 'A pruned graph component is not necessarily a physical room; independent spatial annotation is required.'},
        'quality_claim': {'status': 'unsupported', 'accuracy_claimed': False, 'metrics': {},
                          'reason': 'no_independent_spatial_room_annotation'},
        'native_result': deepcopy(value)}


def render_room_overlay_svg(value):
    diagnose_room_finder_result(value)
    places = value.get('places', []); edges = value.get('edges', [])
    if not places: raise ValueError('place geometry unavailable')
    if len(places)>100_000 or len(edges)>300_000:raise ValueError('render budget exceeded')
    by = {p['id']:p for p in places}
    if len(by)!=len(places):raise ValueError('duplicate place IDs')
    for p in places:
        if len(p['position_xyz'])!=3 or any(not math.isfinite(x) for x in p['position_xyz']):
            raise ValueError('invalid XYZ')
    seeds={i:str(c['seed_id']) for c in value['room_finder']['seeds_before_neighbors'] for i in c['place_ids']}
    rooms={i:c['room_id'] for c in value['room_finder']['post_neighbor_clusters'] if c['accepted_as_room'] for i in c['place_ids']}
    colors=['#51c8ba','#ffb454','#bb9af7','#79b8ff','#ff7a90','#9bd876']
    seed_colors={s:colors[j%len(colors)] for j,s in enumerate(sorted(set(seeds.values())))}
    room_colors={s:colors[j%len(colors)] for j,s in enumerate(sorted(set(rooms.values())))}
    xs=[p['position_xyz'][0] for p in places]; ys=[p['position_xyz'][1] for p in places]
    xmin,xmax,ymin,ymax=min(xs),max(xs),min(ys),max(ys)
    scale=min(390/max(.1,xmax-xmin),370/max(.1,ymax-ymin))
    threshold=value['room_finder']['selected_threshold_m']; caption='none' if threshold is None else f'{threshold:.6f} m'
    out=['<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="540" viewBox="0 0 1440 540">',
         '<rect width="1440" height="540" fill="#101823"/>',
         f'<text x="20" y="25" fill="white" font-family="sans-serif">Native offline reconstruction / threshold {caption} / diagnostic-only; XY projection of all heights</text>']
    def point(p,panel):return 45+panel*480+(p['position_xyz'][0]-xmin)*scale,75+(ymax-p['position_xyz'][1])*scale
    for panel,title in enumerate(('Clearance / edge weight','Seeds before NEIGHBORS','Membership after clustering')):
        out.append(f'<text x="{25+panel*480}" y="53" fill="white" font-family="sans-serif">{title}</text>')
        for e in edges:
            if e['source'] not in by or e['target'] not in by:raise ValueError('edge endpoint absent')
            w=e['weight_m'];passes=threshold is not None and passes_strict_native_cutoff(w,threshold)
            a,b=point(by[e['source']],panel),point(by[e['target']],panel)
            out.append(f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="{"#66849d" if passes else "#543c49"}" stroke-width="1" data-edge-weight-m="{w}"><title>{escape(str(e["source"]))} — {escape(str(e["target"]))}; weight={w:.6f}m; edge cut={not passes}</title></line>')
        for p in places:
            i=p['id'];x,y=point(p,panel);d=p['clearance_m'];seed=seeds.get(i,'');room=rooms.get(i,'unassigned')
            color=('#51c8ba' if threshold is not None and passes_strict_native_cutoff(d,threshold) else '#985765') if panel==0 else seed_colors.get(seed,'#394b60') if panel==1 else room_colors.get(room,'#394b60')
            out.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{color}" data-clearance-m="{d}" data-seed-id="{escape(seed)}" data-post-room="{escape(room)}"><title>{escape(i)}; clearance={d:.6f}m; Z={p["position_xyz"][2]:.3f}; seed={seed}; room={escape(room)}</title></circle>')
            label=i+(f' {d:.2f}' if panel==0 else '')
            out.append(f'<text x="{x+6}" y="{y-5}" fill="#dde8ef" font-size="9" font-family="sans-serif">{escape(label)}</text>')
    out.append('<text x="20" y="515" fill="#b6c4d1" font-family="sans-serif">Room/seed colors show algorithm output, not annotated physical rooms. Hover nodes/edges for numeric evidence. No config tuning.</text></svg>')
    return '\n'.join(out)
