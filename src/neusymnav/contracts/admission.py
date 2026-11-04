"""Immutable, versioned object-admission publications."""
from dataclasses import dataclass
import math
from typing import Mapping
from ._base import Contract, choice, digest, freeze, integer, string_tuple, text, typed_mapping


def _quality_value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            text(key, 'quality key')
            _quality_value(item)
        return
    if isinstance(value, (tuple, list)):
        for item in value: _quality_value(item)
        return
    raise ValueError('quality must contain finite JSON-like values')


@dataclass(frozen=True)
class AdmissionDecision(Contract):
    object_id: str
    state: str
    availability: str
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    quality: Mapping[str, object]

    def __post_init__(self):
        text(self.object_id, 'object_id')
        choice(self.state, {'candidate', 'admitted', 'review_required'}, 'state')
        choice(self.availability, {'available', 'unavailable'}, 'availability')
        object.__setattr__(self, 'reason_codes', string_tuple(self.reason_codes, 'reason_codes'))
        object.__setattr__(self, 'evidence_refs', string_tuple(self.evidence_refs, 'evidence_refs'))
        if not isinstance(self.quality, Mapping):
            raise ValueError('quality must be a mapping')
        _quality_value(self.quality)
        object.__setattr__(self, 'quality', freeze(self.quality))


@dataclass(frozen=True)
class AdmissionSnapshot(Contract):
    episode_id: str
    object_revision: int
    evidence_revision: int
    policy_version: str
    policy_hash: str
    decisions: Mapping[str, AdmissionDecision]

    def __post_init__(self):
        text(self.episode_id, 'episode_id')
        integer(self.object_revision, 'object_revision')
        integer(self.evidence_revision, 'evidence_revision')
        if self.policy_version != 'object-admission:v1':
            raise ValueError('unsupported admission policy version')
        digest(self.policy_hash, 'policy_hash')
        decisions = typed_mapping(self.decisions, AdmissionDecision, 'decisions')
        if any(k != v.object_id for k, v in decisions.items()):
            raise ValueError('decision key mismatch')
        object.__setattr__(self, 'decisions', decisions)
