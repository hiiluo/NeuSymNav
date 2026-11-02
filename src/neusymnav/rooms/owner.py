"""Deterministic room stability policy over measured occupancy and region proposals.

DuDe regions are proposals. Confidence advances only when previously unseen,
measured world cells or deduplicated door observations add evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import copy
from itertools import islice
from typing import Iterable, Mapping

import numpy as np

from ..contracts import GridState, NavSnapshot, RegionSnapshot
from ..contracts.observations import FrameKey

_MAX_CELLS = 250_000
_MAX_ROOMS = 128
_MAX_PORTALS = 256
_MAX_EVENTS = 256
_MAX_DOOR_IDS = 4096
_MAX_CANDIDATE_CELLS = 250_000
_MAX_REGION_INPUTS = 128
_MAX_POLYGON_VERTICES = 8192
_MIN_NEW_CELLS = 4
_MIN_AREA_M2 = 0.75
_MIN_WALL_SUPPORT = 0.45
_MAX_UNKNOWN_BOUNDARY_FRACTION = 0.30
_IOU_MATCH = 0.30


class _EvidenceLimitExceeded(Exception):
    pass


@dataclass(frozen=True)
class DoorEvidence:
    """A source-bound door observation; never a certificate of traversability."""
    evidence_id: str
    episode_id: str
    source_frame: FrameKey
    footprint_xy: tuple[tuple[float, float], ...]
    provenance: str
    score: float | None = None

    def __post_init__(self) -> None:
        if not self.evidence_id or not self.episode_id or not self.provenance:
            raise ValueError("door evidence requires evidence, episode and provenance IDs")
        if not isinstance(self.source_frame, FrameKey) or self.source_frame.episode_id != self.episode_id:
            raise ValueError("door evidence frame must belong to its episode")
        pts = tuple(tuple(float(v) for v in p) for p in self.footprint_xy)
        if len(pts) < 3 or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in pts):
            raise ValueError("door footprint must be a finite XY polygon")
        if self.score is not None and (not math.isfinite(self.score) or not 0.0 <= self.score <= 1.0):
            raise ValueError("door score must be None or lie in [0, 1]")
        object.__setattr__(self, "footprint_xy", pts)


@dataclass(frozen=True)
class RoomRecord:
    room_id: str
    status: str
    polygons: tuple[tuple[tuple[float, float], ...], ...]
    region_ids: tuple[str, ...]
    reason: str
    support_count: int
    predecessors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortalRecord:
    portal_id: str
    endpoints: tuple[tuple[float, float], tuple[float, float]]
    status: str
    reason: str


@dataclass(frozen=True)
class RoomEvent:
    kind: str
    room_ids: tuple[str, ...]
    reason: str
    source_map_revision: int


@dataclass(frozen=True)
class RoomPublication:
    episode_id: str
    source_map_revision: int
    stale: bool
    rooms: tuple[RoomRecord, ...]
    portals: tuple[PortalRecord, ...]
    events: tuple[RoomEvent, ...]

    def to_debug(self) -> dict[str, object]:
        """Return a compact JSON-safe projection for the UI."""
        return {
            "episode_id": self.episode_id,
            "source_map_revision": self.source_map_revision,
            "stale": self.stale,
            "rooms": [
                {"room_id": r.room_id, "status": r.status, "polygons": [[list(p) for p in poly] for poly in r.polygons],
                 "region_ids": list(r.region_ids), "reason": r.reason, "support_count": r.support_count,
                 "predecessors": list(r.predecessors)} for r in self.rooms
            ],
            "portals": [
                {"portal_id": p.portal_id, "endpoints": [list(p.endpoints[0]), list(p.endpoints[1])],
                 "status": p.status, "reason": p.reason} for p in self.portals
            ],
            "events": [{"kind": e.kind, "room_ids": list(e.room_ids), "reason": e.reason,
                        "source_map_revision": e.source_map_revision} for e in self.events],
        }


@dataclass
class _Candidate:
    region_id: str
    polygon: tuple[tuple[float, float], ...]
    cells: frozenset[tuple[int, int]]
    enclosed: bool
    wall_fraction: float
    unknown_fraction: float
    area_m2: float
    door_support: bool


def _point_in_polygon(x: np.ndarray, y: np.ndarray, polygon: tuple[tuple[float, float], ...]) -> np.ndarray:
    inside = np.zeros(x.shape, dtype=np.bool_)
    px, py = zip(*polygon)
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi, xj, yj = px[i], py[i], px[j], py[j]
        crossing = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi)
        inside ^= crossing
        j = i
    return inside


class RoomOwner:
    """Bounded hysteresis over occupancy-supported room proposals.

    The owner retains only cell evidence up to ``max_cells`` and at most 128
    tracks. A region source revision must equal the navigation revision it
    describes. No output is intended as a motion or clearance certificate.
    """
    def __init__(self, *, max_cells: int = _MAX_CELLS) -> None:
        if isinstance(max_cells, bool) or not isinstance(max_cells, int) or not 1 <= max_cells <= _MAX_CELLS:
            raise ValueError("max_cells must be from 1 through 250000")
        self._max_cells = max_cells
        self._episode: str | None = None
        self._header: tuple[object, ...] | None = None
        self._observed: dict[tuple[int, int], int] = {}
        self._tracks: dict[str, dict[str, object]] = {}
        self._next_id = 1
        self._door_ids: set[str] = set()
        self._last_revision = -1
        self._last_capture_ns = -1
        self._last_frame_index = -1
        self._events: list[RoomEvent] = []
        self._pending: dict[tuple, int] = {}
        self._origin = None
        self._publication = RoomPublication("", -1, True, (), (), ())

    @property
    def publication(self) -> RoomPublication:
        return self._publication

    def _stale(self, reason: str = "input rejected or unavailable", *, episode_id: str | None = None) -> RoomPublication:
        old = self._publication
        if episode_id is not None and episode_id != old.episode_id:
            event = RoomEvent("stale", (), reason, -1)
            self._publication = RoomPublication(episode_id, -1, True, (), (), (event,))
            return self._publication
        event = RoomEvent("stale", (), reason, old.source_map_revision)
        events = old.events if old.events and old.events[-1] == event else (old.events + (event,))[-_MAX_EVENTS:]
        self._publication = RoomPublication(old.episode_id, old.source_map_revision, True, old.rooms, old.portals, events)
        return self._publication

    def update(self, nav: NavSnapshot, regions: RegionSnapshot, *, door_evidence: Iterable[DoorEvidence] = ()) -> RoomPublication:
        staged = copy.deepcopy(self)
        result = staged._update(nav, regions, door_evidence=door_evidence)
        if result.stale:
            return self._stale(result.events[-1].reason if result.events else "input rejected", episode_id=nav.episode_id if isinstance(nav, NavSnapshot) else None)
        self.__dict__.update(staged.__dict__)
        return result

    def _update(self, nav: NavSnapshot, regions: RegionSnapshot, *, door_evidence: Iterable[DoorEvidence] = ()) -> RoomPublication:
        if not isinstance(nav, NavSnapshot) or not isinstance(regions, RegionSnapshot):
            raise TypeError("RoomOwner requires NavSnapshot and RegionSnapshot")
        if self._episode is not None and nav.episode_id != self._episode:
            self._episode = nav.episode_id
            self._header = None
            self._observed.clear(); self._tracks.clear(); self._door_ids.clear(); self._events.clear(); self._pending.clear(); self._origin = None; self._next_id = 1
            self._last_revision = -1; self._last_capture_ns = -1; self._last_frame_index = -1
            self._publication = RoomPublication(nav.episode_id, -1, True, (), (), ())
        if (regions.episode_id != nav.episode_id or regions.source_map_revision != nav.revision
                or regions.stale or nav.source.episode_id != nav.episode_id):
            return self._stale("episode/source-map mismatch or stale region input", episode_id=nav.episode_id)
        header = (nav.resolution_m, nav.robot_geometry_id, nav.floor_z_m, nav.floor_datum_source,
                  nav.calibration_hash, nav.source.sensor_id, nav.clock_domain, regions.floor_id)
        if self._episode != nav.episode_id:
            self._episode = nav.episode_id
            self._header = header
            self._observed.clear(); self._tracks.clear(); self._door_ids.clear(); self._events.clear(); self._pending.clear(); self._origin = None; self._next_id = 1
            self._last_revision = -1; self._last_capture_ns = -1; self._last_frame_index = -1
        elif self._header != header:
            return self._stale("source calibration/frame/robot header changed within episode")
        if (nav.states.size > self._max_cells or nav.revision < self._last_revision
                or nav.capture_monotonic_ns < self._last_capture_ns
                or nav.source.frame_index < self._last_frame_index):
            return self._stale("map extent exceeds cap or source revision/time/frame moved backwards")

        origin_x, origin_y = nav.origin_xy
        res = nav.resolution_m
        if self._origin is None:
            self._origin = nav.origin_xy
        offsets = tuple((a-b)/res for a,b in zip(nav.origin_xy, self._origin))
        if any(abs(v-round(v)) > 1e-6 for v in offsets):
            return self._stale("map origin is not aligned to the episode grid")
        base_x, base_y = (round(v) for v in offsets)
        measured = nav.states != GridState.UNKNOWN
        rows, cols = np.nonzero(measured)
        new_cells: set[tuple[int, int]] = set()
        new_walls: set[tuple[int, int]] = set()
        cleared_walls: set[tuple[int, int]] = set()
        for row, col in zip(rows.tolist(), cols.tolist()):
            # The integer key names the world cell whose lower edge is at
            # floor(origin/res)+index. Do not round cell centers: half-cell
            # ties can collapse adjacent cells.
            key = (base_x + col, base_y + row)
            state = int(nav.states[row, col])
            bit = 1 << state
            history = self._observed.get(key)
            if history is None:
                if len(self._observed) >= self._max_cells:
                    return self._stale("measured history cell budget exceeded")
                self._observed[key] = bit
                new_cells.add(key)
                if state == GridState.OCCUPIED: new_walls.add(key)
            elif not (history & bit):
                self._observed[key] = history | bit
                new_cells.add(key)
                if state == GridState.OCCUPIED: new_walls.add(key)
                if state == GridState.FREE and history & (1 << int(GridState.OCCUPIED)):
                    cleared_walls.add(key)
        initial_publication = self._last_revision < 0
        self._last_revision = nav.revision
        self._last_capture_ns = nav.capture_monotonic_ns
        self._last_frame_index = nav.source.frame_index
        fresh_support = len(new_cells) >= _MIN_NEW_CELLS

        doors: list[DoorEvidence] = []
        for door in islice(iter(door_evidence), 256):
            if not isinstance(door, DoorEvidence) or door.episode_id != nav.episode_id or door.evidence_id in self._door_ids:
                continue
            if len(self._door_ids) >= _MAX_DOOR_IDS:
                break
            # The immutable frame key and provenance are retained; do not infer
            # that the observed door is open or traversable.
            doors.append(door)
            self._door_ids.add(door.evidence_id)
        try:
            candidates = self._candidates(nav, regions, doors)
        except _EvidenceLimitExceeded:
            return self._stale("region proposal count, polygon vertices, or candidate cell budget exceeded")
        old_tracks = self._tracks
        new_tracks = {}
        events = []
        links = {i: {rid for rid, t in old_tracks.items()
                     if len(c.cells & t["cells"]) / max(1, min(len(c.cells), len(t["cells"]))) >= .25}
                 for i, c in enumerate(candidates)}
        remaining = set(range(len(candidates)))
        matched = set()
        pending = {}

        def create(c, predecessors=()):
            rid = f"room-{self._next_id:06d}"
            self._next_id += 1
            new_tracks[rid] = {"cells": c.cells, "polygons": (c.polygon,), "support": 1,
                               "status": "tentative", "reason": "awaiting distinct measured support",
                               "region_ids": (c.region_id,), "predecessors": predecessors}
            return rid

        while remaining:
            group = {min(remaining)}
            parents = set()
            while True:
                ps = parents | set().union(*(links[i] for i in group))
                gs = group | {i for i in remaining if links[i] & ps}
                if gs == group and ps == parents:
                    break
                group, parents = gs, ps
            remaining -= group
            matched |= parents
            cs = [candidates[i] for i in sorted(group)]
            if not parents:
                for c in cs:
                    if initial_publication or len(_near_candidate_cells(c.cells, new_cells)) >= _MIN_NEW_CELLS:
                        create(c)
                continue
            if len(parents) == len(cs) == 1:
                rid = next(iter(parents)); old = old_tracks[rid]; c = cs[0]
                relevant = len(_near_candidate_cells(c.cells | old["cells"], new_cells)) >= _MIN_NEW_CELLS
                support = int(old["support"]) + int(relevant)
                status, reason = old["status"], old["reason"]
                if relevant and not (c.enclosed or _door_wall_supported(c)) and status == "confirmed":
                    status, reason = "disputed", "new measured geometry weakens enclosure support"
                elif relevant and support >= 2 and (c.enclosed or _door_wall_supported(c)):
                    status, reason = "confirmed", "enclosure with distinct measured support"
                if status != old["status"]:
                    events.append(RoomEvent(status, (rid,), reason, nav.revision))
                new_tracks[rid] = {**old, "cells": c.cells if relevant else old["cells"],
                                   "polygons": (c.polygon,) if relevant else old["polygons"],
                                   "region_ids": (c.region_id,), "support": support,
                                   "status": status, "reason": reason}
                continue
            polygons = ([c.polygon for c in cs] if len(cs) > 1 else
                        [p for rid in sorted(parents) for p in old_tracks[rid]["polygons"]])
            structural = new_walls if len(cs) > len(parents) else cleared_walls if len(cs) < len(parents) else set()
            if len(structural) * sum(len(poly) for poly in polygons) > 2_000_000:
                return self._stale("partition evidence computation budget exceeded")
            relevant = {p for p in structural if _near_partition(p, polygons, self._origin, res)}
            signature = (tuple(sorted(parents)), tuple(sorted(_polygon_key(c.polygon) for c in cs)))
            old_count, old_evidence = self._pending.get(signature, (0, frozenset()))
            count = old_count + int(len(relevant) >= _MIN_NEW_CELLS)
            evidence = old_evidence | relevant
            pending[signature] = (count, evidence)
            # Retain only currently measured support: flipped-back cells cannot
            # contribute to a structural correction.
            expected = GridState.OCCUPIED if len(cs) > len(parents) else GridState.FREE
            active = {p for p in evidence if 0 <= p[0]-base_x < nav.states.shape[1]
                      and 0 <= p[1]-base_y < nav.states.shape[0]
                      and nav.states[p[1]-base_y, p[0]-base_x] == expected}
            # Sample the shared edge in the current map. Connectivity through
            # one gap is not evidence that the divider has disappeared.
            ys, xs = np.indices(nav.states.shape).reshape(2, -1)
            if len(xs) * sum(len(poly) for poly in polygons) > 2_000_000:
                return self._stale("shared edge computation budget exceeded")
            edge = [(int(x), int(y)) for y, x in zip(ys, xs)
                    if _near_partition((base_x+int(x), base_y+int(y)), polygons, self._origin, res, .75)]
            matching = sum(nav.states[y, x] == expected for x, y in edge)
            structural_fraction = matching / max(1, len(edge))
            if (count >= 2 and len(active) >= max(_MIN_NEW_CELLS, math.ceil(.6 / res))
                    and structural_fraction >= .80):
                preds = tuple(sorted(parents))
                ids = tuple(create(c, preds) for c in cs)
                kind = "split" if len(cs) > len(parents) else "merge" if len(cs) < len(parents) else "repartition"
                events.append(RoomEvent(kind, ids + preds, "persistent partition with distinct local measured evidence", nav.revision))
            else:
                for rid in sorted(parents):
                    old = old_tracks[rid]
                    new_tracks[rid] = {**old, "region_ids": tuple(c.region_id for c in cs),
                                       "reason": "structural proposal awaiting distinct boundary evidence"}
        for rid, track in old_tracks.items():
            if rid not in matched:
                local = len(_near_candidate_cells(track["cells"], new_cells)) >= _MIN_NEW_CELLS
                status = "disputed" if local and track["status"] == "confirmed" else track["status"]
                if status != track["status"]:
                    events.append(RoomEvent("disputed", (rid,), "proposal absent; retaining prior geometry", nav.revision))
                new_tracks[rid] = {**track, "status": status, "region_ids": (), "reason": "proposal absent; retaining prior geometry"}
        if len(new_tracks) > _MAX_ROOMS or sum(len(t["cells"]) for t in new_tracks.values()) > self._max_cells:
            return self._stale("room count or retained geometry cell budget exceeded")
        self._tracks = new_tracks
        if sum(len(v[1]) for v in pending.values()) > self._max_cells:
            return self._stale("pending structural evidence budget exceeded")
        self._pending = pending
        self._events = (self._events + events)[-_MAX_EVENTS:]
        room_records = tuple(RoomRecord(rid, str(t["status"]), tuple(t["polygons"]),
                                        tuple(t["region_ids"]), str(t["reason"]), int(t["support"]),
                                        tuple(t["predecessors"])) for rid, t in sorted(new_tracks.items()))
        portals = self._portals(nav, room_records)
        self._publication = RoomPublication(nav.episode_id, nav.revision, False, room_records, portals, tuple(self._events))
        return self._publication

    def _candidates(self, nav: NavSnapshot, regions: RegionSnapshot, doors: list[DoorEvidence]) -> list[_Candidate]:
        if len(regions.regions) > _MAX_REGION_INPUTS or sum(len(region.polygon) for region in regions.regions.values()) > _MAX_POLYGON_VERTICES:
            raise _EvidenceLimitExceeded
        free = (nav.states == GridState.FREE) & nav.floor_support & (nav.clearance > 0)
        rows, cols = np.nonzero(free)
        if not len(rows):
            return []
        ox, oy = nav.origin_xy; r = nav.resolution_m
        wx = ox + (cols + 0.5) * r; wy = oy + (rows + 0.5) * r
        proposed: list[_Candidate] = []
        considered_cells = 0
        for rid, region in sorted(regions.regions.items()):
            poly_arr = np.asarray(region.polygon, dtype=np.float64)
            if len(poly_arr) < 3:
                continue
            bbox = (wx >= poly_arr[:, 0].min()) & (wx <= poly_arr[:, 0].max()) & (wy >= poly_arr[:, 1].min()) & (wy <= poly_arr[:, 1].max())
            inds = np.flatnonzero(bbox)
            if not len(inds):
                continue
            inside = _point_in_polygon(wx[inds], wy[inds], tuple(map(tuple, poly_arr.tolist())))
            selected = inds[inside]
            if len(selected) < 4:
                continue
            considered_cells += len(selected)
            if considered_cells > min(_MAX_CANDIDATE_CELLS, self._max_cells):
                raise _EvidenceLimitExceeded
            base_x, base_y = (round((a-b)/r) for a,b in zip(nav.origin_xy, self._origin))
            cells = frozenset((base_x + int(cols[i]), base_y + int(rows[i])) for i in selected[:_MAX_CELLS])
            if not cells:
                continue
            # Boundary support is counted only from measured occupancy. Unknown
            # remains unknown and lowers enclosure confidence.
            boundary = occupied = unknown = 0
            for cx, cy in cells:
                for nx, ny in ((cx+1,cy),(cx-1,cy),(cx,cy+1),(cx,cy-1)):
                    if (nx, ny) in cells:
                        continue
                    boundary += 1
                    gx = nx - base_x; gy = ny - base_y
                    if 0 <= gy < nav.states.shape[0] and 0 <= gx < nav.states.shape[1]:
                        state = int(nav.states[gy, gx])
                        if state == GridState.OCCUPIED: occupied += 1
                        elif state == GridState.UNKNOWN: unknown += 1
                        # Free beyond the DuDe polygon is an opening, never wall.
                    else:
                        unknown += 1
            wall_fraction = occupied / max(1, boundary)
            unknown_fraction = unknown / max(1, boundary)
            area = len(cells) * r * r
            door_support = any((d.score is None or d.score >= 0.55)
                               and _polygon_near(d.footprint_xy, region.polygon, max(0.25, 2*r)) for d in doors)
            enclosed = (area >= _MIN_AREA_M2 and wall_fraction >= _MIN_WALL_SUPPORT
                        and unknown_fraction <= _MAX_UNKNOWN_BOUNDARY_FRACTION)
            proposed.append(_Candidate(rid, tuple(map(tuple, poly_arr.tolist())), cells,
                                       enclosed, wall_fraction, unknown_fraction, area, door_support))
        if len(proposed) > _MAX_ROOMS:
            raise _EvidenceLimitExceeded
        return proposed

    def _portals(self, nav: NavSnapshot, rooms: tuple[RoomRecord, ...]) -> tuple[PortalRecord, ...]:
        # Detect a measured-free throat between occupied wall flanks directly
        # from occupancy. This proposal is independent of DuDe's current cuts.
        output: list[PortalRecord] = []
        s = nav.states
        if min(s.shape) < 5:
            return ()
        free = (s == GridState.FREE) & nav.floor_support & (nav.clearance > 0)
        occ = s == GridState.OCCUPIED
        # A doorway candidate is a 0.6–1.5 m measured-free gap through an
        # occupied wall line, with free continuation on both sides. It is
        # independent of DuDe cuts and intentionally conservative.
        min_width = max(2, math.ceil(0.60 / nav.resolution_m))
        max_width = max(min_width, math.floor(1.50 / nav.resolution_m))
        for orient, center_axis, along_axis in (("x", 1, 0), ("y", 0, 1)):
            length = s.shape[along_axis]
            breadth = s.shape[center_axis]
            for center in range(2, breadth - 2):
                if orient == "x":
                    lane = free[:, center]
                    line = s[:, center]
                else:
                    lane = free[center, :]
                    line = s[center, :]
                starts = np.flatnonzero(lane & np.r_[True, ~lane[:-1]])
                ends = np.flatnonzero(lane & np.r_[~lane[1:], True])
                for start, end in zip(starts.tolist(), ends.tolist()):
                    width_cells = end - start + 1
                    if width_cells < min_width or width_cells > max_width or start == 0 or end >= length - 1:
                        continue
                    if line[start - 1] != GridState.OCCUPIED or line[end + 1] != GridState.OCCUPIED:
                        continue
                    mid = (start + end) // 2
                    if orient == "x":
                        through = free[mid, center-2:center+3]
                        a, b = (center-2, mid), (center+2, mid)
                    else:
                        through = free[center-2:center+3, mid]
                        a, b = (mid, center-2), (mid, center+2)
                    if len(through) != 5 or not bool(np.all(through)):
                        continue
                    scale = nav.resolution_m
                    p1 = (nav.origin_xy[0] + (a[0]+0.5)*scale, nav.origin_xy[1] + (a[1]+0.5)*scale)
                    p2 = (nav.origin_xy[0] + (b[0]+0.5)*scale, nav.origin_xy[1] + (b[1]+0.5)*scale)
                    # Identify the center raster cell in the episode grid.
                    # The scan axes swap for the horizontal orientation.
                    col, row = (center, mid) if orient == "x" else (mid, center)
                    base_x, base_y = (round((a-b)/scale) for a,b in zip(nav.origin_xy, self._origin))
                    pid = f"portal:{orient}:{base_x+col}:{base_y+row}"
                    output.append(PortalRecord(pid, (p1, p2), "candidate",
                                               f"{width_cells*scale:.2f} m measured-free wall gap; passage unverified"))
                    if len(output) >= _MAX_PORTALS:
                        return tuple(output)
        return tuple(output)


def _polygon_near(a: tuple[tuple[float,float],...], b: tuple[tuple[float,float],...], radius: float) -> bool:
    ax=np.asarray(a); bx=np.asarray(b)
    if not len(ax) or not len(bx): return False
    # Conservative vertex distance prefilter; this is an evidence association,
    # not geometry overlap or passage validation.
    return bool(np.min(np.sum((ax[:,None,:]-bx[None,:,:])**2,axis=2)) <= radius*radius)


def _candidate_signature(cells: frozenset[tuple[int, int]]) -> str:
    """Stable bounded signature for a pending partition proposal."""
    # A deterministic compact checksum; the cell set itself is retained beside
    # the key, so collisions are disambiguated by IoU before matching.
    import hashlib
    digest = hashlib.blake2b(digest_size=12)
    for x, y in sorted(cells):
        digest.update(int(x).to_bytes(8, "little", signed=True))
        digest.update(int(y).to_bytes(8, "little", signed=True))
    return digest.hexdigest()


def _near_candidate_cells(cells: frozenset[tuple[int, int]], evidence: set[tuple[int, int]]) -> set[tuple[int, int]]:
    """Measured changes inside or directly at the candidate's perimeter."""
    return {p for p in evidence if p in cells or (p[0]+1,p[1]) in cells or (p[0]-1,p[1]) in cells
            or (p[0],p[1]+1) in cells or (p[0],p[1]-1) in cells}


def _door_wall_supported(candidate: _Candidate) -> bool:
    return (candidate.door_support and candidate.area_m2 >= _MIN_AREA_M2
            and candidate.wall_fraction >= 0.30
            and candidate.unknown_fraction <= _MAX_UNKNOWN_BOUNDARY_FRACTION)


def _polygon_key(poly):
    pts = tuple((round(x, 6), round(y, 6)) for x, y in poly)
    rev = tuple(reversed(pts))
    return min([pts[i:]+pts[:i] for i in range(len(pts))] + [rev[i:]+rev[:i] for i in range(len(rev))])


def _near_partition(cell, polygons, origin, res, tolerance=2.5):
    x, y = origin[0]+(cell[0]+.5)*res, origin[1]+(cell[1]+.5)*res
    near = 0
    for poly in polygons:
        distance = float("inf")
        for a,b in zip(poly, poly[1:]+poly[:1]):
            dx,dy = b[0]-a[0],b[1]-a[1]
            t = max(0., min(1., ((x-a[0])*dx+(y-a[1])*dy)/max(dx*dx+dy*dy, 1e-30)))
            if .05 < t < .95:
                distance = min(distance, math.hypot(x-a[0]-t*dx, y-a[1]-t*dy))
        near += distance <= tolerance*res
    return near >= 2
