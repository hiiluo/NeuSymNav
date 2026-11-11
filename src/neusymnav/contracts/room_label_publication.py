"""Immutable room-label result envelope, pinned to one complete request key."""
from __future__ import annotations

from dataclasses import dataclass

from ._base import Contract, choice, digest, integer, text
from .room_semantics import RoomLabelResult
from ..rooms.requests import RoomLabelRequestKey


@dataclass(frozen=True, slots=True)
class RoomLabelPublication(Contract):
    request_key: RoomLabelRequestKey
    result: RoomLabelResult
    model_manifest_hash: str
    prompt_hash: str
    schema_hash: str
    runtime_hash: str
    started_at_ns: int
    completed_at_ns: int
    clock_domain: str
    display_state: str

    def __post_init__(self):
        if not isinstance(self.request_key, RoomLabelRequestKey):
            raise ValueError('request_key must be RoomLabelRequestKey')
        if not isinstance(self.result, RoomLabelResult):
            raise ValueError('result must be RoomLabelResult')
        key = self.request_key
        result = self.result
        if (key.room_id != result.room_id or key.graph_revision != result.geometry_revision
                or key.context_hash != result.input_evidence_hash):
            raise ValueError('publication result identity differs from request key')
        for name in ('model_manifest_hash', 'prompt_hash', 'schema_hash', 'runtime_hash'):
            digest(getattr(self, name), name)
        if result.prompt_sha256 is not None and result.prompt_sha256 != self.prompt_hash:
            raise ValueError('publication prompt hash differs from result prompt hash')
        integer(self.started_at_ns, 'started_at_ns')
        integer(self.completed_at_ns, 'completed_at_ns')
        if self.completed_at_ns < self.started_at_ns:
            raise ValueError('publication completion precedes start')
        text(self.clock_domain, 'clock_domain')
        choice(self.display_state, {'current', 'stale', 'history'}, 'display_state')

    @property
    def request_id(self) -> str:
        return self.request_key.request_id

    def matches_current(self, current: RoomLabelRequestKey) -> bool:
        return self.display_state == 'current' and self.request_key.matches_current(current)
