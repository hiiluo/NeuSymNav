"""Read-only display geometry and source-backed image crops for Hydra."""
import hashlib
import json
import math

import numpy as np

from ..contracts import GridState, HydraFrame, loads
from ..mapping.occupancy import capsule_cells

LOOKBACK_BYTES = 64 * 1024**2
MAX_JOURNAL_LINE_BYTES = 64 * 1024**2


def _cross_room_links(graph):
    rooms = {node.node_id for node in graph.nodes if node.layer_id == 4}
    places = {node.node_id: node for node in graph.nodes
              if node.layer_id == 3 and node.parent_id in rooms and node.position is not None}
    seen = set()
    for edge in graph.edges:
        a, b = places.get(edge.source), places.get(edge.target)
        if edge.kind != 'intralayer' or a is None or b is None or a.parent_id == b.parent_id:
            continue
        key = tuple(sorted((a.node_id, b.node_id)))
        if key in seen:
            continue
        seen.add(key)
        yield a, b


def room_outlines(graph, raster):
    """Project room-assigned places onto connected measured free cells for display."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra

    states = raster.states
    if states.size > 1_000_000:
        return ()
    rooms = {node.node_id: index for index, node in enumerate(graph.nodes) if node.layer_id == 4}
    origin = np.asarray(raster.origin_xy)
    step = raster.resolution_m
    seed_rooms = {}
    for node in graph.nodes:
        if node.layer_id != 3 or node.position is None or node.parent_id not in rooms:
            continue
        col, row = np.floor((np.asarray(node.position[:2]) - origin) / step).astype(int)
        if 0 <= row < states.shape[0] and 0 <= col < states.shape[1] and states[row, col] == GridState.FREE:
            cell = int(row * states.shape[1] + col)
            seed_rooms.setdefault(cell, set()).add(rooms[node.parent_id])
    seeds = sorted(cell for cell, owners in seed_rooms.items() if len(owners) == 1)
    if not seeds:
        return ()

    free = states == GridState.FREE
    indices = np.arange(states.size).reshape(states.shape)
    horizontal = free[:, :-1] & free[:, 1:]
    vertical = free[:-1, :] & free[1:, :]
    diagonal = horizontal[:-1, :] & horizontal[1:, :]
    straight_start = np.concatenate((indices[:, :-1][horizontal], indices[:-1, :][vertical]))
    straight_end = np.concatenate((indices[:, 1:][horizontal], indices[1:, :][vertical]))
    starts = np.concatenate((straight_start, indices[:-1, :-1][diagonal], indices[:-1, 1:][diagonal]))
    ends = np.concatenate((straight_end, indices[1:, 1:][diagonal], indices[1:, :-1][diagonal]))
    costs = np.concatenate((np.full(len(straight_start), step),
                            np.full(len(starts) - len(straight_start), step * math.sqrt(2))))
    network = coo_matrix((costs, (starts, ends)),
                         shape=(states.size, states.size)).tocsr()
    # Propagate only along measured free space, and leave unsupported areas unlabeled.
    _, _, nearest = dijkstra(network, directed=False, indices=seeds,
                             min_only=True, return_predecessors=True, limit=2.5)
    owners = np.full(states.size, -1, dtype=np.int32)
    owners[seeds] = [next(iter(seed_rooms[cell])) for cell in seeds]
    labels = np.full(states.size, -1, dtype=np.int32)
    reached = nearest >= 0
    labels[reached] = owners[nearest[reached]]
    padded = np.pad(labels.reshape(states.shape), 1, constant_values=-1)
    horizontal = padded[:-1, 1:-1] != padded[1:, 1:-1]
    vertical = padded[1:-1, :-1] != padded[1:-1, 1:]
    segments = []
    for horizontal_edge, mask in ((True, horizontal), (False, vertical.T)):
        transitions = np.diff(np.pad(mask, ((0, 0), (1, 1))), axis=1)
        rows, starts = np.nonzero(transitions & np.pad(mask, ((0, 0), (0, 1))))
        _, ends = np.nonzero(transitions & np.pad(mask, ((0, 0), (1, 0))))
        for row, start, end in zip(rows, starts, ends):
            a, b = ((start, row), (end, row)) if horizontal_edge else ((row, start), (row, end))
            segments.append((tuple(origin + step * np.asarray(a)), tuple(origin + step * np.asarray(b))))
    return tuple(segments) if len(segments) <= 16_384 else ()


def room_passages(graph, nav):
    """Find direct room transitions with observed clearance for this footprint."""
    if (nav is None or graph is None or graph.status != 'available' or not graph.last_source
            or (graph.episode_id, graph.last_source.get('clock_domain'))
            != (nav.episode_id, nav.clock_domain)):
        return ()
    robot = graph.native_metadata.get('display_robot')
    if not robot or robot['geometry_id'] != nav.robot_geometry_id:
        return ()
    radius = robot['radius_m'] + robot['margin_m']
    height = robot['height_m']
    free = (nav.states == GridState.FREE) & nav.floor_support & (nav.clearance >= height)
    rows, cols = free.shape
    result = set()
    for index, (a, b) in enumerate(_cross_room_links(graph)):
        if index == 512:
            break
        rooms = tuple(sorted((a.parent_id, b.parent_id)))
        start, end = a.position[:2], b.position[:2]
        if rooms in result or not .05 <= math.dist(start, end) <= 2.:
            continue
        if any(not (0 <= (x-nav.origin_xy[0])/nav.resolution_m < cols
                    and 0 <= (y-nav.origin_xy[1])/nav.resolution_m < rows)
               for x, y in (start, end)):
            continue
        if all(0 <= row < rows and 0 <= col < cols and free[row, col]
               for row, col in capsule_cells(nav.origin_xy, nav.resolution_m, start, end, radius)):
            result.add(rooms)
    return tuple(sorted(result))


def node_label(graph, node, room_labels):
    if node.layer_id == 4:
        name = room_labels.get(node.node_id, 'Room').split(' (or ', 1)[0]
    elif node.layer_id == 2:
        name = graph.native_metadata.get('object_categories', {}).get(node.native_id)
        if not name:
            name = node.name if node.name and not node.name.isdecimal() else 'Unknown object'
    else:
        name = node.name or {3: 'Place', 5: 'Building'}.get(node.layer_id, 'Node')
    return f'{name} · {node.native_id}'


def object_crop(frame, label, bounds, other_bounds):
    """Score a crop by visible, unambiguous depth support inside the native box."""
    y, x = np.nonzero(frame.valid_depth & (frame.labels == label))
    if len(x) < 24:
        return None
    z = frame.depth_m[y, x]
    K = frame.K
    camera = np.stack(((x - K[0, 2]) * z / K[0, 0],
                       (y - K[1, 2]) * z / K[1, 1], z), axis=1)
    pose = frame.world_T_body @ frame.body_T_camera
    points = camera @ pose[:3, :3].T + pose[:3, 3]

    def inside(box):
        return np.all((points >= np.asarray(box[0]) - .03)
                      & (points <= np.asarray(box[1]) + .03), axis=1)

    keep = inside(bounds)
    for box in other_bounds:
        keep &= ~inside(box)
    y, x = y[keep], x[keep]
    if len(x) < 24:
        return None
    x0, x1, y0, y1 = x.min(), x.max() + 1, y.min(), y.max() + 1
    area = (x1 - x0) * (y1 - y0)
    if min(x1 - x0, y1 - y0) < 5 or len(x) / area < .2:
        return None
    # Reward large visible support and penalize crops spanning disconnected pixels.
    score = len(x) * len(x) / area
    return score, frame.rgb[y0:y1, x0:x1].copy()


def read_best_view(journal, graph, native_id):
    """Search recent accepted RGB-D first, then stream the earlier archive."""
    source = graph.last_source
    metadata = graph.native_metadata
    labels = metadata.get('room_label_input', {}).get('semantic_labels', {})
    boxes = metadata.get('object_bounds', {})
    label, bounds = labels.get(native_id), boxes.get(native_id)
    if (not source or label is None or bounds is None or graph.status != 'available'
            or graph.stale or graph.replay_required):
        return None
    other_bounds = tuple(box for key, box in boxes.items()
                         if key != native_id and labels.get(key) == label
                         and np.all(np.asarray(box[0]) <= np.asarray(bounds[1]) + .06)
                         and np.all(np.asarray(box[1]) >= np.asarray(bounds[0]) - .06))
    with journal.open('rb') as stream:
        end = stream.seek(0, 2)
        start = max(0, end - LOOKBACK_BYTES)
        if start:
            stream.seek(start - 1)
            if stream.read(1) != b'\n':
                stream.readline(min(end - start, MAX_JOURNAL_LINE_BYTES))
            start = stream.tell()
        best = _search_object_views(stream, start, end, end, graph, label, bounds, other_bounds)
        if best is None and start:
            # Include the acceptance record for a frame whose start precedes the
            # cutoff, even if its acceptance falls inside the recent window.
            best = _search_object_views(stream, 0, end, start, graph, label, bounds, other_bounds)
    return best


def _search_object_views(stream, start, end, latest_start, graph, label, bounds, other_bounds):
    best = None
    pending = None
    source = graph.last_source
    expected_calibration = ((graph.native_metadata.get('last_transform') or {}).get('calibration_hash')
                            or source.get('calibration_hash'))
    world_epoch = graph.native_metadata.get('graph_world_epoch')
    stream.seek(start)
    while (offset := stream.tell()) < end:
        row = stream.readline(min(end - offset, MAX_JOURNAL_LINE_BYTES))
        if not row.endswith(b'\n'):
            break
        try:
            event = json.loads(row)
            if event.get('run_id') != graph.run_id:
                continue
            if event.get('event') == 'started':
                if offset >= latest_start:
                    break
                pending = event
                continue
            if (event.get('event') != 'accepted' or event.get('accepted') is not True
                    or pending is None or event.get('source') != pending.get('source')):
                continue
            accepted_source = event['source']
            revision = event['graph_revision']
            started, pending = pending, None
            if (type(revision) is not int or not 0 <= revision <= graph.graph_revision
                    or (world_epoch is not None and accepted_source.get('world_epoch') != world_epoch)
                    or any(accepted_source.get(field) != source.get(field)
                           for field in ('episode_id', 'sensor_id', 'clock_domain', 'labelspace_hash', 'vocabulary_id'))):
                continue
            payload = started['selected_frame']
            if hashlib.sha256(payload.encode()).hexdigest() != started['payload_sha256']:
                continue
            frame = loads(payload)
            if (not isinstance(frame, HydraFrame)
                    or any(getattr(frame.source_key, field) != accepted_source[field]
                           for field in ('episode_id', 'sensor_id', 'frame_index'))
                    or frame.capture_monotonic_ns != accepted_source['capture_monotonic_ns']
                    or frame.clock_domain != accepted_source['clock_domain']
                    or frame.labelspace_hash != accepted_source['labelspace_hash']
                    or frame.source_geometry_hash != accepted_source['source_geometry_hash']
                    or (expected_calibration is not None and frame.calibration_hash != expected_calibration)
                    or (accepted_source.get('calibration_hash') is not None
                        and frame.calibration_hash != accepted_source['calibration_hash'])):
                continue
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        match = object_crop(frame, label, bounds, other_bounds)
        if match is not None and (best is None or match[0] >= best[0]):
            best = (*match, frame.source_key.frame_index, revision)
    return best
