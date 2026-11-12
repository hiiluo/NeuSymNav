"""Versioned room label overlay; never owns geometry or room IDs."""
from __future__ import annotations

from dataclasses import dataclass

from ._base import Contract, choice, digest, integer, string_tuple, text


ROOM_LABELS = frozenset({'bedroom', 'bathroom', 'kitchen', 'living_room',
    'dining_room', 'office', 'hallway', 'utility', 'mixed', 'unknown'})


@dataclass(frozen=True)
class RoomLabelProposal(Contract):
    room_id: str
    geometry_revision: int
    input_evidence_hash: str
    label: str
    alternatives: tuple[str, ...]
    supporting_object_ids: tuple[str, ...]
    status: str
    reason: str | None
    model_sha256: str | None
    prompt_sha256: str | None
    supporting_view_ids: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.room_id, 'room_id')
        integer(self.geometry_revision, 'geometry_revision')
        digest(self.input_evidence_hash, 'input_evidence_hash')
        choice(self.label, ROOM_LABELS, 'label')
        alternatives = string_tuple(self.alternatives, 'alternatives')
        if any(value not in ROOM_LABELS for value in alternatives) or self.label in alternatives:
            raise ValueError('alternatives must be distinct canonical room labels')
        object.__setattr__(self, 'alternatives', alternatives)
        object.__setattr__(self, 'supporting_object_ids',
                           string_tuple(self.supporting_object_ids, 'supporting_object_ids'))
        views = string_tuple(self.supporting_view_ids, 'supporting_view_ids')
        for view in views:
            digest(view, 'supporting_view_id')
        object.__setattr__(self, 'supporting_view_ids', views)
        choice(self.status, {'proposed', 'unknown', 'insufficient_evidence', 'unavailable',
                             'timeout', 'invalid_output'}, 'status')
        if self.reason is not None:
            text(self.reason, 'reason')
        if self.status != 'proposed' and self.reason is None:
            raise ValueError('abstention proposal requires a reason')
        if self.status == 'proposed' and self.label == 'unknown':
            raise ValueError('unknown label must use unknown status')
        if (self.model_sha256 is None) != (self.prompt_sha256 is None):
            raise ValueError('model and prompt hashes must both be present or both be absent')
        if self.model_sha256 is not None:
            digest(self.model_sha256, 'model_sha256')
            digest(self.prompt_sha256, 'prompt_sha256')


@dataclass(frozen=True)
class RoomLabelResult(Contract):
    room_id: str
    geometry_revision: int
    input_evidence_hash: str
    label: str
    alternatives: tuple[str, ...]
    supporting_object_ids: tuple[str, ...]
    status: str
    reason: str | None
    model_sha256: str | None
    prompt_sha256: str | None
    supporting_view_ids: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.room_id, 'room_id')
        integer(self.geometry_revision, 'geometry_revision')
        digest(self.input_evidence_hash, 'input_evidence_hash')
        choice(self.label, ROOM_LABELS, 'label')
        alternatives = string_tuple(self.alternatives, 'alternatives')
        if any(value not in ROOM_LABELS for value in alternatives) or self.label in alternatives:
            raise ValueError('alternatives must be distinct canonical room labels')
        object.__setattr__(self, 'alternatives', alternatives)
        object.__setattr__(self, 'supporting_object_ids', string_tuple(
            self.supporting_object_ids, 'supporting_object_ids'))
        views = string_tuple(self.supporting_view_ids, 'supporting_view_ids')
        for view in views:
            digest(view, 'supporting_view_id')
        object.__setattr__(self, 'supporting_view_ids', views)
        choice(self.status, {'available', 'unknown', 'insufficient_evidence', 'unavailable',
                             'timeout', 'stale', 'invalid'}, 'status')
        if self.reason is not None:
            text(self.reason, 'reason')
        if (self.model_sha256 is None) != (self.prompt_sha256 is None):
            raise ValueError('model and prompt hashes must both be present or both be absent')
        if self.model_sha256 is not None:
            digest(self.model_sha256, 'model_sha256'); digest(self.prompt_sha256, 'prompt_sha256')


def validate_room_label(proposal, context, *, allowed_view_ids=()) -> RoomLabelResult:
    """Validate against the current room and the exact images sent to inference."""
    from ..rooms.context import RoomContext
    if not isinstance(context, RoomContext):
        raise TypeError('context must be RoomContext')
    fields = ('room_id', 'geometry_revision', 'input_evidence_hash', 'label', 'alternatives',
              'supporting_object_ids', 'status', 'reason', 'model_sha256', 'prompt_sha256')
    if isinstance(proposal, dict):
        try:
            if set(proposal) - {'supporting_view_ids'} != set(fields):
                raise ValueError('proposal fields mismatch')
            proposal = RoomLabelProposal(**proposal)
        except (TypeError, ValueError) as exc:
            return RoomLabelResult(context.room_id, context.geometry_revision,
                context.input_evidence_hash, 'unknown', (), (), 'invalid',
                f'invalid_room_label_output:{exc}', None, None)
    if not isinstance(proposal, RoomLabelProposal):
        raise TypeError('proposal must be RoomLabelProposal or a JSON object')
    if (proposal.room_id != context.room_id
            or proposal.geometry_revision != context.geometry_revision
            or proposal.input_evidence_hash != context.input_evidence_hash):
        return RoomLabelResult(context.room_id, context.geometry_revision,
            context.input_evidence_hash, 'unknown', (), (), 'stale',
            'room_geometry_or_context_changed', proposal.model_sha256, proposal.prompt_sha256)
    allowed = {item.native_id for item in context.objects}
    if not set(proposal.supporting_object_ids) <= allowed:
        return RoomLabelResult(context.room_id, context.geometry_revision,
            context.input_evidence_hash, 'unknown', (), (), 'invalid',
            'supporting_object_not_in_context', proposal.model_sha256, proposal.prompt_sha256)
    if not set(proposal.supporting_view_ids) <= set(allowed_view_ids):
        return RoomLabelResult(context.room_id, context.geometry_revision,
            context.input_evidence_hash, 'unknown', (), (), 'invalid',
            'supporting_view_not_in_request', proposal.model_sha256, proposal.prompt_sha256)
    has_visual_support = bool(proposal.supporting_view_ids)
    if proposal.status == 'proposed' and (
            context.geometry_status != 'available' or context.truncated
            or (not context.objects and not has_visual_support)
            or (has_visual_support and any(item.membership_status != 'assigned' for item in context.objects))):
        return RoomLabelResult(context.room_id, context.geometry_revision,
            context.input_evidence_hash, 'unknown', (), (), 'insufficient_evidence',
            'room_geometry_or_object_context_unavailable_or_truncated', proposal.model_sha256,
            proposal.prompt_sha256)
    if proposal.status == 'proposed' and not (proposal.supporting_object_ids or has_visual_support):
        return RoomLabelResult(context.room_id, context.geometry_revision,
            context.input_evidence_hash, 'unknown', (), (), 'invalid',
            'proposed_label_requires_assigned_support', proposal.model_sha256,
            proposal.prompt_sha256)
    if proposal.status == 'proposed':
        by_id = {item.native_id: item for item in context.objects}
        if any(by_id[item].membership_status != 'assigned' for item in proposal.supporting_object_ids):
            return RoomLabelResult(context.room_id, context.geometry_revision,
                context.input_evidence_hash, 'unknown', (), (), 'invalid',
                'supporting_object_membership_not_assigned', proposal.model_sha256,
                proposal.prompt_sha256)
    if proposal.status in {'unknown', 'insufficient_evidence'} and (
            proposal.label != 'unknown' or proposal.alternatives or proposal.supporting_object_ids
            or has_visual_support):
        return RoomLabelResult(context.room_id, context.geometry_revision,
            context.input_evidence_hash, 'unknown', (), (), 'invalid',
            'abstention_must_be_unknown_without_claims', proposal.model_sha256,
            proposal.prompt_sha256)
    status = ('invalid' if proposal.status == 'invalid_output' else
              'available' if proposal.status == 'proposed' else proposal.status)
    if status == 'unknown' and proposal.label != 'unknown':
        return RoomLabelResult(context.room_id, context.geometry_revision,
            context.input_evidence_hash, 'unknown', (), (), 'invalid',
            'unknown_status_requires_unknown_label', proposal.model_sha256, proposal.prompt_sha256)
    return RoomLabelResult(proposal.room_id, proposal.geometry_revision,
        proposal.input_evidence_hash, proposal.label, proposal.alternatives,
        proposal.supporting_object_ids, status, proposal.reason,
        proposal.model_sha256, proposal.prompt_sha256, proposal.supporting_view_ids)
