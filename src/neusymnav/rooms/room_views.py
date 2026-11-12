"""Deterministic, room-scoped views from accepted Hydra RGB-D inputs.

The batch API reads and decodes the bounded journal tail once for all rooms.
Room assignment is a conservative nearest-place estimate, not room ground truth.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from itertools import combinations
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial import cKDTree

from ..contracts import HydraFrame, loads
from ..visualization.hydra_display import LOOKBACK_BYTES


@dataclass(frozen=True)
class RoomView:
    view_id: str
    jpeg: bytes
    frame_index: int
    graph_revision: int
    room_id: str
    provenance_json: str
    room_purity: float
    score: float

    def manifest(self):
        return dict(view_id=self.view_id, frame_index=self.frame_index,
                    graph_revision=self.graph_revision, room_id=self.room_id,
                    room_purity=self.room_purity, score=self.score,
                    **json.loads(self.provenance_json))


def _frames(journal, graph):
    source = graph.last_source
    if not source or graph.status != 'available' or graph.stale or graph.replay_required:
        return
    world_epoch = graph.native_metadata.get('graph_world_epoch')
    pending = None
    with Path(journal).open('rb') as stream:
        end = stream.seek(0, 2); start = max(0, end - LOOKBACK_BYTES)
        stream.seek(start)
        if start:
            stream.readline(end - start)
        while stream.tell() < end:
            row = stream.readline(end - stream.tell())
            if not row.endswith(b'\n'):
                break
            try:
                event = json.loads(row)
                if event.get('run_id') != graph.run_id:
                    continue
                if event.get('event') == 'started':
                    pending = event
                    continue
                if (event.get('event') != 'accepted' or event.get('accepted') is not True
                        or pending is None or event.get('source') != pending.get('source')):
                    continue
                started, pending = pending, None
                s, revision = event['source'], event['graph_revision']
                if (type(revision) is not int or revision > graph.graph_revision or revision < 0
                        or s.get('episode_id') != graph.episode_id
                        or any(s.get(k) != source.get(k) for k in
                               ('episode_id', 'sensor_id', 'clock_domain', 'labelspace_hash', 'vocabulary_id'))):
                    continue
                payload = started['selected_frame']
                if hashlib.sha256(payload.encode()).hexdigest() != started['payload_sha256']:
                    continue
                f = loads(payload)
                if not isinstance(f, HydraFrame):
                    continue
                if (any(getattr(f.source_key, k) != s.get(k) for k in ('episode_id', 'sensor_id', 'frame_index'))
                        or any(getattr(f, k) != s.get(k) for k in ('capture_monotonic_ns', 'clock_domain',
                                                                    'labelspace_hash', 'source_geometry_hash', 'vocabulary_id'))):
                    continue
                transform = graph.native_metadata.get('last_transform') or {}
                expected_cal = transform.get('calibration_hash') or source.get('calibration_hash')
                if ((expected_cal and f.calibration_hash != expected_cal)
                        or (transform.get('calibration_id') and f.calibration_id != transform['calibration_id'])
                        or (s.get('labelspace_id') and f.labelspace_id != s['labelspace_id'])
                        or (s.get('calibration_hash') and f.calibration_hash != s['calibration_hash'])
                        or (world_epoch is not None and s.get('world_epoch') != world_epoch)
                        or (source.get('world_epoch') is not None and s.get('world_epoch') != source['world_epoch'])):
                    continue
                yield f, revision
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                continue


def select_room_views_batch(journal: Path, graph, room_ids, *, method='kss', limit=2):
    """Select views for each room, sharing the bounded journal decode pass."""
    if method not in ('geometry', 'kss'):
        raise ValueError('method must be geometry or kss')
    if type(limit) is not int or not 0 <= limit <= 3:
        raise ValueError('limit must be an integer from 0 to 3')
    room_ids = tuple(dict.fromkeys(room_ids))
    output = {room: [] for room in room_ids}
    rooms = {n.node_id for n in graph.nodes if n.layer_id == 4}
    places = sorted((n for n in graph.nodes if n.layer_id == 3 and n.parent_id in rooms
                     and n.position is not None), key=lambda n: n.node_id)
    # Fail closed on unusually large graphs to keep each batch bounded.
    if not places or not limit or len(places) > 8192 or len(rooms) > 64:
        return {room: () for room in room_ids}
    trees = {room: cKDTree(np.asarray([p.position for p in places if p.parent_id == room]))
             for room in sorted({p.parent_id for p in places})}
    labels = graph.native_metadata.get('room_label_input', {}).get('semantic_labels', {})
    bounds = graph.native_metadata.get('object_bounds', {})
    nodes_by_id = {node.node_id: node for node in graph.nodes}

    def object_room(node):
        # Match HydraSceneGraphQuery: reject missing or cyclic ancestry.
        seen = {node.node_id}
        room = None
        while node.parent_id is not None:
            if node.parent_id in seen or node.parent_id not in nodes_by_id:
                return None
            seen.add(node.parent_id)
            node = nodes_by_id[node.parent_id]
            if node.layer_id == 4 and room is None:
                room = node.node_id
        return room

    objects = [(n, object_room(n)) for n in graph.nodes if n.layer_id == 2
               and n.native_id in labels and n.native_id in bounds]
    objects = [(node, room) for node, room in objects if room in output]
    for frame, revision in _frames(journal, graph):
        h, w = frame.depth_m.shape
        step = max(1, int(np.ceil(max(h, w) / 96)))
        yy, xx = np.mgrid[0:h:step, 0:w:step]
        yy, xx = yy.ravel(), xx.ravel()
        total_samples = len(xx)
        valid = frame.valid_depth[yy, xx]
        yy, xx = yy[valid], xx[valid]
        if len(xx) < 24:
            continue
        z = frame.depth_m[yy, xx]; k = frame.K
        camera = np.column_stack(((xx-k[0,2])*z/k[0,0], (yy-k[1,2])*z/k[1,1], z))
        pose = frame.world_T_body @ frame.body_T_camera
        points = camera @ pose[:3,:3].T + pose[:3,3]
        # Query each room's nearest place, so ties within one room are harmless.
        room_distances = {room: tree.query(points)[0] for room, tree in trees.items()}
        ordered = sorted(room_distances)
        distances = np.column_stack([room_distances[r] for r in ordered])
        nearest = np.argmin(distances, axis=1)
        best = distances[np.arange(len(points)), nearest]
        second = np.partition(distances, 1, axis=1)[:, 1] if len(ordered) > 1 else np.full(len(points), np.inf)
        assigned = (best <= 2.5) & (second - best >= .15)
        for room in room_ids:
            if room not in room_distances:
                continue
            own = assigned & (nearest == ordered.index(room))
            other = assigned & ~own
            support = int(own.sum())
            purity = support / len(points)
            if support < max(24, .5 * total_samples) or purity < .8:
                continue
            cells = frozenset(map(tuple, np.floor(points[own] / .5).astype(int)))
            visible = {}
            for obj, object_room_id in objects:
                if object_room_id != room:
                    continue
                box = np.asarray(bounds[obj.native_id])
                if box.shape != (2, 3):
                    continue
                inside = np.all((points >= box[0]-.03) & (points <= box[1]+.03), axis=1)
                for other_id, other_box in bounds.items():
                    if other_id == obj.native_id or labels.get(other_id) != labels[obj.native_id]:
                        continue
                    other_box = np.asarray(other_box)
                    if other_box.shape == (2, 3):
                        inside &= ~np.all((points >= other_box[0]-.03) &
                                          (points <= other_box[1]+.03), axis=1)
                visible_pixels = int((own & inside & (frame.labels[yy, xx] == labels[obj.native_id])).sum())
                if visible_pixels >= 3:
                    # Saturating support tiers reduce the influence of mask noise.
                    visible[obj.node_id] = 1 + int(visible_pixels >= 10) + int(visible_pixels >= 25)
            pairs = frozenset(combinations(sorted(visible), 2))
            # Mask only positively attributed neighboring samples; unknown retains context.
            image = Image.fromarray(frame.rgb.copy())
            if other.any():
                mask = np.zeros((h, w), np.uint8)
                for y, x in zip(yy[other], xx[other]):
                    mask[y:min(h,y+step), x:min(w,x+step)] = 255
                image.paste((96,96,96), mask=Image.fromarray(mask))
            image.thumbnail((448,448), Image.Resampling.LANCZOS)
            buf = io.BytesIO(); image.save(buf, format='JPEG', quality=85, optimize=False)
            jpeg = buf.getvalue(); digest = hashlib.sha256(jpeg).hexdigest()
            provenance = dict(source_key=dict(episode_id=frame.source_key.episode_id,
                              sensor_id=frame.source_key.sensor_id, frame_index=frame.source_key.frame_index),
                              capture_monotonic_ns=frame.capture_monotonic_ns, clock_domain=frame.clock_domain,
                              sim_time_s=frame.sim_time_s, calibration_id=frame.calibration_id,
                              calibration_version=frame.calibration_version, calibration_hash=frame.calibration_hash,
                              source_geometry_hash=frame.source_geometry_hash,
                              coordinate_convention=frame.coordinate_convention,
                              camera_convention=frame.camera_convention, depth_convention=frame.depth_convention,
                              pose_version=frame.pose_version, K=frame.K.tolist(),
                              world_T_body=frame.world_T_body.tolist(), body_T_camera=frame.body_T_camera.tolist(),
                              target_graph_revision=graph.graph_revision,
                              graph_input_prefix_sha256=graph.input_prefix_sha256,
                              world_epoch=graph.native_metadata.get('graph_world_epoch'),
                              selection_method=method, image_width=image.width, image_height=image.height,
                              room_support=support, sampled_depth_count=len(points),
                              total_image_samples=total_samples, visible_object_ids=sorted(visible),
                              object_support_tiers=visible, spatial_cell_count=len(cells))
            output[room].append((digest, jpeg, frame.source_key.frame_index, revision, purity,
                                 provenance, cells, visible, pairs))
    result = {}
    for room, candidates in output.items():
        selected = []; seen = set(); covered = set(); best_support = {}; seen_pairs = set()
        while candidates and len(selected) < limit:
            def score(c):
                spatial = len(c[6] - covered)
                if method == 'geometry' or not selected:
                    return spatial
                object_gain = sum(max(0, strength - best_support.get(obj, 0))
                                  for obj, strength in c[7].items())
                return spatial + 4*object_gain + 6*len(c[8]-seen_pairs)
            candidates.sort(key=lambda c: (-score(c), -c[4], c[2], c[0]))
            candidate = candidates.pop(0)
            if candidate[0] in seen:
                continue
            value = score(candidate)
            if selected and value <= 0:
                break
            digest, jpeg, index, revision, purity, provenance, cells, visible, pairs = candidate
            selected.append(RoomView(digest, jpeg, index, revision, room,
                                     json.dumps(provenance, sort_keys=True), purity, float(value)))
            seen.add(digest); covered.update(cells); seen_pairs.update(pairs)
            for obj, strength in visible.items():
                best_support[obj] = max(best_support.get(obj, 0), strength)
        result[room] = tuple(selected)
    return result


def select_room_views(journal: Path, graph, room_id: str, *, method='kss', limit=2):
    return select_room_views_batch(journal, graph, (room_id,), method=method, limit=limit)[room_id]
