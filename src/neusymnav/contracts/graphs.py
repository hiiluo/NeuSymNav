"""Owned immutable map/object/region/hierarchy publications for schema v1."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Mapping, Protocol
from uuid import UUID
import numpy as np
from ._base import (Contract, array, boolean, choice, coordinates, digest, finite,
                    freeze, integer, string_tuple, text, typed_mapping, typed_tuple)
from .observations import AppearanceFeature, DetectionBatch, FrameKey, ObjectObservation, Observation, _key
from ..geometry.frames import transform_covariance


class GridState(IntEnum):
    UNKNOWN = -1
    FREE = 0
    OCCUPIED = 100


def _episode_source(episode_id, source):
    text(episode_id, 'episode_id')
    _key(source)
    if source.episode_id != episode_id:
        raise ValueError('source belongs to a different episode')


def _raster(value, name):
    result = array(value, name, dtype=np.int8, ndim=2)
    if 0 in result.shape or not np.isin(result, [-1, 0, 100]).all():
        raise ValueError(f'{name} must be nonempty int8 unknown=-1/free=0/occupied=100 raster')
    return result


@dataclass(frozen=True)
class NavSnapshot(Contract):
    episode_id: str
    revision: int
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    resolution_m: float
    origin_xy: tuple[float, float]
    states: np.ndarray
    floor_support: np.ndarray
    clearance: np.ndarray
    robot_geometry_id: str
    floor_z_m: float
    floor_datum_source: str
    calibration_hash: str

    def __post_init__(self):
        _episode_source(self.episode_id, self.source)
        integer(self.revision, 'revision')
        integer(self.capture_monotonic_ns, 'capture_monotonic_ns')
        text(self.clock_domain, 'clock_domain')
        if finite(self.resolution_m, 'resolution_m') <= 0:
            raise ValueError('resolution_m must be positive')
        object.__setattr__(self, 'origin_xy', coordinates(self.origin_xy, 2, 'origin_xy'))
        states = _raster(self.states, 'states')
        object.__setattr__(self, 'states', states)
        support = array(self.floor_support, 'floor_support', dtype=np.bool_, shape=states.shape)
        clearance = array(self.clearance, 'clearance', shape=states.shape)
        if clearance.dtype.kind != 'f' or np.any(clearance < 0):
            raise ValueError('clearance must be nonnegative measured floating-point metres; zero means unavailable')
        object.__setattr__(self, 'floor_support', support)
        object.__setattr__(self, 'clearance', clearance)
        text(self.robot_geometry_id, 'robot_geometry_id')
        finite(self.floor_z_m, 'floor_z_m')
        text(self.floor_datum_source, 'floor_datum_source')
        digest(self.calibration_hash, 'calibration_hash')


@dataclass(frozen=True)
class ObjectState(Contract):
    object_id: str
    floor_id: str
    centroid: np.ndarray
    bounds: np.ndarray
    lifecycle: str
    evidence_refs: tuple[str, ...]
    revision: int
    source: FrameKey
    first_seen_ns: int
    last_seen_ns: int
    clock_domain: str
    raw_label: str | None = None
    category: str | None = None
    covariance: np.ndarray | None = None
    points_world: np.ndarray | None = None
    footprint_xy: np.ndarray | None = None
    appearance: AppearanceFeature | None = None

    def __post_init__(self):
        text(self.object_id, 'object_id')
        try:
            UUID(self.object_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError('canonical object_id must be a UUID') from exc
        text(self.floor_id, 'floor_id')
        centroid = array(self.centroid, 'centroid', shape=(3,))
        bounds = array(self.bounds, 'bounds', shape=(2, 3))
        if centroid.dtype.kind != 'f' or bounds.dtype.kind != 'f' or np.any(bounds[0] > bounds[1]):
            raise ValueError('object geometry must be ordered floating-point bounds and centroid')
        if np.any(centroid < bounds[0] - 1e-8) or np.any(centroid > bounds[1] + 1e-8):
            raise ValueError('centroid must lie within bounds')
        object.__setattr__(self, 'centroid', centroid)
        object.__setattr__(self, 'bounds', bounds)
        choice(self.lifecycle, {'candidate', 'active', 'verified', 'dormant', 'retired', 'merged'}, 'lifecycle')
        object.__setattr__(self, 'evidence_refs', string_tuple(self.evidence_refs, 'evidence_refs'))
        integer(self.revision, 'revision')
        _key(self.source)
        integer(self.first_seen_ns, 'first_seen_ns')
        integer(self.last_seen_ns, 'last_seen_ns')
        if self.last_seen_ns < self.first_seen_ns:
            raise ValueError('last_seen_ns precedes first_seen_ns')
        text(self.clock_domain, 'clock_domain')
        for name in ('raw_label', 'category'):
            if getattr(self, name) is not None:
                text(getattr(self, name), name)
        if self.covariance is not None:
            covariance = array(self.covariance, 'covariance', shape=(3, 3))
            transform_covariance(covariance, np.eye(3))
            object.__setattr__(self, 'covariance', covariance)
        for name, columns in [('points_world', 3), ('footprint_xy', 2)]:
            value = getattr(self, name)
            if value is not None:
                value = array(value, name, shape=(None, columns))
                if value.dtype.kind != 'f' or len(value) == 0:
                    raise ValueError(f'{name} must contain floating-point coordinates')
                object.__setattr__(self, name, value)
        if self.appearance is not None and not isinstance(self.appearance, AppearanceFeature):
            raise ValueError('appearance must be AppearanceFeature')


@dataclass(frozen=True)
class ObjectSnapshot(Contract):
    episode_id: str
    revision: int
    source: FrameKey
    objects: Mapping[str, ObjectState]
    aliases: Mapping[str, str]

    def __post_init__(self):
        _episode_source(self.episode_id, self.source)
        integer(self.revision, 'revision')
        objects = typed_mapping(self.objects, ObjectState, 'objects')
        aliases = typed_mapping(self.aliases, str, 'aliases')
        for key, value in objects.items():
            if key != value.object_id or value.source.episode_id != self.episode_id or value.revision > self.revision:
                raise ValueError('object key/episode/revision mismatch')
        for old, target in aliases.items():
            text(target, 'alias target')
            if old in objects:
                raise ValueError('alias key cannot also be a live canonical object')
            seen = {old}
            while target in aliases:
                if target in seen:
                    raise ValueError('alias cycle')
                seen.add(target)
                target = aliases[target]
            if target not in objects:
                raise ValueError('dangling alias')
        object.__setattr__(self, 'objects', objects)
        object.__setattr__(self, 'aliases', aliases)

    def resolve_id(self, object_id: str) -> str:
        text(object_id, 'object_id')
        while object_id in self.aliases:
            object_id = self.aliases[object_id]
        if object_id not in self.objects:
            raise KeyError(object_id)
        return object_id


@dataclass(frozen=True)
class CommitResult(Contract):
    snapshot: ObjectSnapshot
    committed_event_ids: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.snapshot, ObjectSnapshot):
            raise ValueError('snapshot must be ObjectSnapshot')
        object.__setattr__(self, 'committed_event_ids', string_tuple(self.committed_event_ids, 'committed_event_ids'))


@dataclass(frozen=True)
class RegionGrid(Contract):
    episode_id: str
    source_map_revision: int
    resolution_m: float
    origin_xy: tuple[float, float]
    values: np.ndarray
    preprocessing_policy: str = 'extended_unknown_boundary'

    def __post_init__(self):
        text(self.episode_id, 'episode_id')
        integer(self.source_map_revision, 'source_map_revision')
        if finite(self.resolution_m, 'resolution_m') <= 0:
            raise ValueError('resolution_m must be positive')
        object.__setattr__(self, 'origin_xy', coordinates(self.origin_xy, 2, 'origin_xy'))
        object.__setattr__(self, 'values', _raster(self.values, 'values'))
        choice(self.preprocessing_policy, {'extended_unknown_boundary'}, 'preprocessing_policy')

    @classmethod
    def from_nav(cls, nav: NavSnapshot) -> RegionGrid:
        """Copy the observed raster unchanged; preprocessing is the backend's job."""
        if not isinstance(nav, NavSnapshot):
            raise ValueError('nav must be NavSnapshot')
        return cls(nav.episode_id, nav.revision, nav.resolution_m, nav.origin_xy, nav.states)


@dataclass(frozen=True)
class Region(Contract):
    region_id: str
    polygon: np.ndarray
    predecessor_ids: tuple[str, ...] = ()
    adjacency: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.region_id, 'region_id')
        polygon = array(self.polygon, 'polygon', shape=(None, 2))
        if polygon.dtype.kind != 'f' or len(polygon) < 3:
            raise ValueError('region polygon must contain >=3 floating-point vertices')
        area_twice = np.sum(polygon[:, 0] * np.roll(polygon[:, 1], -1) - polygon[:, 1] * np.roll(polygon[:, 0], -1))
        if abs(area_twice) <= 1e-12:
            raise ValueError('region polygon must have nonzero area')
        object.__setattr__(self, 'polygon', polygon)
        object.__setattr__(self, 'predecessor_ids', string_tuple(self.predecessor_ids, 'predecessor_ids'))
        adjacency = string_tuple(self.adjacency, 'adjacency')
        if self.region_id in adjacency:
            raise ValueError('region cannot be adjacent to itself')
        object.__setattr__(self, 'adjacency', adjacency)


@dataclass(frozen=True)
class RegionSnapshot(Contract):
    episode_id: str
    revision: int
    source_map_revision: int
    floor_id: str
    regions: Mapping[str, Region]
    stale: bool

    def __post_init__(self):
        text(self.episode_id, 'episode_id')
        integer(self.revision, 'revision')
        integer(self.source_map_revision, 'source_map_revision')
        text(self.floor_id, 'floor_id')
        boolean(self.stale, 'stale')
        regions = typed_mapping(self.regions, Region, 'regions')
        for key, value in regions.items():
            if key != value.region_id or not set(value.adjacency).issubset(regions):
                raise ValueError('region key or adjacency endpoint mismatch')
        object.__setattr__(self, 'regions', regions)


@dataclass(frozen=True)
class HierarchyNode(Contract):
    node_id: str
    kind: str
    attributes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self):
        text(self.node_id, 'node_id')
        choice(self.kind, {'building', 'floor', 'region', 'place', 'object'}, 'kind')
        if not isinstance(self.attributes, Mapping):
            raise ValueError('attributes must be mapping')
        object.__setattr__(self, 'attributes', freeze(self.attributes))


@dataclass(frozen=True)
class HierarchyEdge(Contract):
    source_id: str
    target_id: str
    kind: str
    status: str
    provenance: Mapping[str, object]
    object_revision: int
    source_map_revision: int
    region_revision: int

    def __post_init__(self):
        text(self.source_id, 'source_id')
        text(self.target_id, 'target_id')
        text(self.kind, 'kind')
        choice(self.status, {'assigned', 'ambiguous', 'unassigned', 'unavailable'}, 'status')
        if self.source_id == self.target_id:
            raise ValueError('hierarchy edge cannot point to itself')
        if not isinstance(self.provenance, Mapping) or not self.provenance:
            raise ValueError('edge requires provenance')
        object.__setattr__(self, 'provenance', freeze(self.provenance))
        for name in ('object_revision', 'source_map_revision', 'region_revision'):
            integer(getattr(self, name), name)


@dataclass(frozen=True)
class HierarchySnapshot(Contract):
    episode_id: str
    revision: int
    object_revision: int
    map_revision: int
    region_revision: int
    nodes: Mapping[str, HierarchyNode]
    edges: tuple[HierarchyEdge, ...]
    statuses: Mapping[str, str]
    latest_nav_revision: int
    source_map_age_ns: int

    def __post_init__(self):
        text(self.episode_id, 'episode_id')
        for name in ('revision', 'object_revision', 'map_revision', 'region_revision', 'latest_nav_revision', 'source_map_age_ns'):
            integer(getattr(self, name), name)
        if self.latest_nav_revision < self.map_revision:
            raise ValueError('latest_nav_revision cannot precede pinned source map')
        nodes = typed_mapping(self.nodes, HierarchyNode, 'nodes')
        if any(key != node.node_id for key, node in nodes.items()):
            raise ValueError('node mapping key mismatch')
        edges = typed_tuple(self.edges, HierarchyEdge, 'edges')
        keys = set()
        for edge in edges:
            if edge.source_id not in nodes or edge.target_id not in nodes:
                raise ValueError('dangling hierarchy endpoint')
            if (edge.object_revision, edge.source_map_revision, edge.region_revision) != (self.object_revision, self.map_revision, self.region_revision):
                raise ValueError('hierarchy edge revision mismatch')
            key = (edge.source_id, edge.target_id, edge.kind)
            if key in keys:
                raise ValueError('duplicate hierarchy edge')
            keys.add(key)
        object.__setattr__(self, 'nodes', nodes)
        object.__setattr__(self, 'edges', edges)
        object.__setattr__(self, 'statuses', typed_mapping(self.statuses, str, 'statuses'))


class NavMapper(Protocol):
    def update(self, observation: Observation) -> NavSnapshot: ...


class RegionBackend(Protocol):
    def update(self, nav: NavSnapshot) -> RegionSnapshot: ...


class ObjectOwner(Protocol):
    def commit(self, source: Observation, batch: DetectionBatch,
               observations: tuple[ObjectObservation, ...]) -> CommitResult: ...


class HierarchyComposer(Protocol):
    def compose(self, objects: ObjectSnapshot, nav: NavSnapshot, regions: RegionSnapshot, *,
                latest_nav_revision: int, now_ns: int, clock_domain: str) -> HierarchySnapshot: ...


class VerificationOwner(Protocol):
    def consume(self, commit: CommitResult) -> None: ...
