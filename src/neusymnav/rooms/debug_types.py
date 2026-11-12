"""Immutable UI-only room-label snapshots; never navigation or geometry owners."""
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping
from ..backends.hydra.graph_adapter import HydraGraphProjection
from ..contracts.room_semantics import RoomLabelResult
from .requests import RoomLabelRequest


def _freeze(value):
    if isinstance(value, Mapping): return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if isinstance(value,(list,tuple)): return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True, slots=True)
class RoomLabelDebugJob:
    request: RoomLabelRequest
    graph: HydraGraphProjection
    offered_ns: int
    def __post_init__(self):
        if not isinstance(self.request,RoomLabelRequest) or not isinstance(self.graph,HydraGraphProjection):
            raise TypeError('typed room request and source graph required')
        k=self.request.key;g=self.graph
        if (k.episode_id,k.run_id,k.graph_revision,k.input_prefix_sha256)!=(g.episode_id,g.run_id,g.graph_revision,g.input_prefix_sha256):
            raise ValueError('room job request/source graph mismatch')
        if type(self.offered_ns) is not int or self.offered_ns<0:raise ValueError('nonnegative offer timestamp required')
        object.__setattr__(self,'graph',replace(g,last_source=_freeze(g.last_source),native_metadata=_freeze(g.native_metadata),provenance=_freeze(g.provenance),node_counts=_freeze(g.node_counts)))
        object.__setattr__(self,'request',replace(self.request,source_manifest=_freeze(self.request.source_manifest),context=replace(self.request.context,source_hashes=_freeze(self.request.context.source_hashes))))


@dataclass(frozen=True, slots=True)
class RoomLabelDebugRecord:
    job: RoomLabelDebugJob
    state: str
    result: RoomLabelResult|None = None
    started_ns: int|None = None
    completed_ns: int|None = None
    backend_metrics: Mapping = field(default_factory=dict)
    evidence_quality: Mapping = field(default_factory=dict)
    error: str|None = None
    def __post_init__(self):
        if not isinstance(self.job,RoomLabelDebugJob):raise TypeError('typed job required')
        if self.state not in {'pending','running','complete','error','cancelled'}:raise ValueError('invalid debug record state')
        k=self.job.request.key
        if self.result is not None and (self.result.room_id,self.result.geometry_revision,self.result.input_evidence_hash)!=(k.room_id,k.graph_revision,k.context_hash):
            raise ValueError('room result does not match original snapshot request')
        for stamp in (self.started_ns,self.completed_ns):
            if stamp is not None and (type(stamp) is not int or stamp<self.job.offered_ns):raise ValueError('invalid debug timestamp')
        if self.started_ns is not None and self.completed_ns is not None and self.completed_ns<self.started_ns:raise ValueError('completion precedes start')
        object.__setattr__(self,'backend_metrics',_freeze(self.backend_metrics))
        object.__setattr__(self,'evidence_quality',_freeze(self.evidence_quality))


def record_is_current(record:RoomLabelDebugRecord,graph:HydraGraphProjection|None)->bool:
    if graph is None or graph.status!='available' or graph.stale or graph.replay_required:return False
    k=record.job.request.key
    source=graph.native_metadata.get('room_label_input') or {}
    original=record.job.graph.native_metadata.get('room_label_input') or {}
    return (k.episode_id,k.run_id,k.graph_revision,k.input_prefix_sha256)==(graph.episode_id,graph.run_id,graph.graph_revision,graph.input_prefix_sha256) and bool(source.get('snapshot_sha256')) and source.get('snapshot_sha256')==original.get('snapshot_sha256')==k.geometry_hash and k.world_epoch==graph.native_metadata.get('graph_world_epoch')
