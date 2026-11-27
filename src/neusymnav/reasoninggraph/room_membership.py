"""Offline, fail-closed room containment for revision-bound view positions.

Room polygons and floor identifiers must be supplied by an external geometry
owner; native place proximity and semantic labels are never containment proof.
"""
from dataclasses import dataclass
import math
from itertools import islice

from ..contracts.hydra_graph import NativeNodeRef
from ..contracts.reasoninggraph import GraphReadToken
from ..contracts.observations import FrameKey
from ..hierarchy.membership import _boundary
from ..regions._types import Polygon2D
from ..regions.geometry import point_in_polygon, valid_ring


@dataclass(frozen=True)
class CertifiedRoom:
    token: GraphReadToken
    room: NativeNodeRef
    floor_id: str
    polygon: tuple
    provenance: str

    def __post_init__(self):
        if (not isinstance(self.token, GraphReadToken) or not isinstance(self.room, NativeNodeRef)
                or self.room.layer_id != 4 or self.room.token != self.token.native):
            raise ValueError('room geometry requires the exact native room revision')
        if not isinstance(self.floor_id, str) or not self.floor_id.strip() or not isinstance(self.provenance, str) or not self.provenance.strip():
            raise ValueError('room geometry requires floor and certification provenance')
        try:
            polygon = tuple(tuple(float(v) for v in point) for point in self.polygon)
            valid = (3 <= len(polygon) <= 4096 and all(len(p) == 2 and all(math.isfinite(v) for v in p) for p in polygon)
                     and valid_ring(polygon))
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise ValueError('invalid certified room polygon')
        object.__setattr__(self, 'polygon', polygon)


@dataclass(frozen=True)
class RoomSample:
    token: GraphReadToken
    position: tuple | None
    floor_id: str | None
    source: FrameKey | None = None

    def __post_init__(self):
        if not isinstance(self.token, GraphReadToken):
            raise ValueError('sample requires a graph token')
        source = self.token.source if self.source is None else self.source
        if not isinstance(source, FrameKey) or source.episode_id != self.token.native.episode_id:
            raise ValueError('sample source must belong to the same episode')
        object.__setattr__(self, 'source', source)
        if self.floor_id is not None and (not isinstance(self.floor_id, str) or not self.floor_id.strip()):
            raise ValueError('invalid sample floor')
        if self.position is not None:
            try:
                position = tuple(float(v) for v in self.position)
                valid = len(position) == 3 and all(math.isfinite(v) for v in position)
            except (TypeError, ValueError, OverflowError):
                valid = False
            if not valid:
                raise ValueError('invalid sample position')
            object.__setattr__(self, 'position', position)


@dataclass(frozen=True)
class RoomMembership:
    source: object
    status: str
    room: NativeNodeRef | None
    candidates: tuple
    reason: str


def resolve_memberships(token, samples, rooms, *, geometry_complete=False, max_samples=512, max_rooms=256):
    """Resolve an explicitly bounded batch; missing/stale support stays pending."""
    if not isinstance(token, GraphReadToken) or type(geometry_complete) is not bool:
        raise ValueError('expected graph token and completeness flag')
    if any(type(x) is not int or not 1 <= x <= limit for x, limit in ((max_samples, 4096), (max_rooms, 1024))):
        raise ValueError('invalid membership budget')
    samples, rooms = tuple(islice(samples, max_samples + 1)), tuple(islice(rooms, max_rooms + 1))
    if len(samples) > max_samples or len(rooms) > max_rooms:
        raise ValueError('membership budget exceeded')
    if any(not isinstance(x, RoomSample) for x in samples) or any(not isinstance(x, CertifiedRoom) for x in rooms):
        raise ValueError('invalid membership input')
    if len({x.source for x in samples}) != len(samples) or len({x.room for x in rooms}) != len(rooms):
        raise ValueError('duplicate membership input')
    results = []
    for sample in samples:
        source = sample.source
        if sample.token != token or sample.position is None or sample.floor_id is None:
            results.append(RoomMembership(source, 'pending', None, (), 'missing_or_stale_pose'))
            continue
        if not geometry_complete or any(r.token != token for r in rooms):
            results.append(RoomMembership(source, 'pending', None, (), 'incomplete_or_stale_geometry'))
            continue
        eligible = sorted((r for r in rooms if r.token == token and r.floor_id == sample.floor_id), key=lambda r: r.room.native_id)
        if not eligible:
            results.append(RoomMembership(source, 'pending', None, (), 'missing_certified_floor_geometry'))
            continue
        point = sample.position[:2]
        candidates = tuple(r.room for r in eligible if _boundary(point, r.polygon) or point_in_polygon(point, Polygon2D(r.polygon)))
        boundary = any(_boundary(point, r.polygon) for r in eligible)
        if len(candidates) == 1 and not boundary:
            results.append(RoomMembership(source, 'assigned', candidates[0], candidates, 'inside_certified_room'))
        elif candidates:
            results.append(RoomMembership(source, 'ambiguous', None, candidates, 'boundary_or_competing_rooms'))
        else:
            results.append(RoomMembership(source, 'pending', None, (), 'outside_certified_geometry'))
    return tuple(results)
