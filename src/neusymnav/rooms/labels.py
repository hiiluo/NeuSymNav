"""Strict model reply adaptation; the host, never the model, binds identity."""
from __future__ import annotations

import json

from ..contracts._base import digest
from ..contracts.room_semantics import ROOM_LABELS, RoomLabelProposal
from .requests import RoomLabelRequest


MAX_RESPONSE_BYTES = 16 * 1024
_FIELDS = frozenset({'label', 'alternatives', 'supporting_object_ids', 'status', 'reason'})
_STATUSES = frozenset({'proposed', 'unknown', 'insufficient_evidence'})


def _invalid(request: RoomLabelRequest, model_hash: str, prompt_hash: str, reason: str):
    return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
        request.key.context_hash, 'unknown', (), (), 'invalid_output', reason[:256],
        model_hash, prompt_hash)


def _unique_fields(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate_json_key')
        value[key] = item
    return value


def adapt_model_reply(raw: str, request: RoomLabelRequest, *, model_hash: str,
                      prompt_hash: str) -> RoomLabelProposal:
    """Parse exact JSON and validate support membership without repairing output."""
    if not isinstance(request, RoomLabelRequest):
        raise TypeError('request must be RoomLabelRequest')
    digest(model_hash, 'model_hash')
    digest(prompt_hash, 'prompt_hash')
    if not isinstance(raw, str):
        return _invalid(request, model_hash, prompt_hash, 'response_not_text')
    if len(raw.encode('utf-8')) > MAX_RESPONSE_BYTES:
        return _invalid(request, model_hash, prompt_hash, 'response_exceeds_16_kib')
    try:
        value = json.loads(raw, object_pairs_hook=_unique_fields)
    except (json.JSONDecodeError, UnicodeError):
        return _invalid(request, model_hash, prompt_hash, 'malformed_json')
    except ValueError as exc:
        if str(exc) == 'duplicate_json_key':
            return _invalid(request, model_hash, prompt_hash, 'duplicate_json_key')
        raise
    if not isinstance(value, dict) or set(value) != _FIELDS:
        return _invalid(request, model_hash, prompt_hash, 'response_schema_mismatch')
    label, alternatives, supporting, status, reason = (value[name] for name in (
        'label', 'alternatives', 'supporting_object_ids', 'status', 'reason'))
    if (not isinstance(label, str) or label not in ROOM_LABELS
            or not isinstance(alternatives, list) or len(alternatives) > 2
            or any(not isinstance(item, str) or item not in ROOM_LABELS for item in alternatives)
            or len(set(alternatives)) != len(alternatives) or label in alternatives
            or not isinstance(supporting, list) or len(supporting) > 8
            or any(not isinstance(item, str) or not item for item in supporting)
            or len(set(supporting)) != len(supporting)
            or not isinstance(status, str) or status not in _STATUSES
            or not isinstance(reason, str) or not reason.strip()
            or len(reason) > 256):
        return _invalid(request, model_hash, prompt_hash, 'response_field_invalid')
    allowed_categories = set(request.source_manifest.get('canonical_categories', ()))
    if any(not item.category.isascii() or item.category not in allowed_categories
            for item in request.context.objects):
        return _invalid(request, model_hash, prompt_hash, 'noncanonical_input_category')
    by_id = {item.native_id: item for item in request.context.objects}
    if any(item not in by_id for item in supporting):
        return _invalid(request, model_hash, prompt_hash, 'unsupported_object_id')
    if any(by_id[item].membership_status != 'assigned' for item in supporting):
        return _invalid(request, model_hash, prompt_hash, 'support_membership_not_assigned')
    if status == 'proposed' and (label == 'unknown' or not supporting):
        return _invalid(request, model_hash, prompt_hash, 'proposed_label_missing_support')
    if status != 'proposed' and label != 'unknown':
        return _invalid(request, model_hash, prompt_hash, 'abstention_requires_unknown_label')
    if status != 'proposed' and alternatives:
        return _invalid(request, model_hash, prompt_hash, 'abstention_cannot_claim_alternatives')
    if status != 'proposed' and supporting:
        return _invalid(request, model_hash, prompt_hash, 'abstention_cannot_claim_support')
    return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
        request.key.context_hash, label, tuple(alternatives), tuple(supporting), status,
        reason, model_hash, prompt_hash)
