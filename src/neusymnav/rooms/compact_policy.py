"""Low-latency room-label policy: short prompt, short constrained answer.

The verbose ``json-v1`` policy spent most of its time prefilling a JSON
schema plus constant per-object fields and decoding a free-text reason.
``compact-v2`` keeps the same fail-closed contract but:

* lists only the information that varies per room (index + canonical
  category); membership must already be ``assigned`` or the request is
  blocked before inference;
* keeps every room-independent instruction in one static prefix so the
  llama.cpp prompt cache reuses it across requests;
* asks for one line ``label|alternatives|support indices`` constrained by a
  request-bound GBNF, then expands it on the host into the canonical JSON
  reply and runs the unchanged strict adapter on it.

The model never sees or emits native IDs; the host maps 1-based indices back
to the request's own object rows, so an index cannot name an object outside
this request.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re

from ..contracts.room_semantics import ROOM_LABELS, RoomLabelProposal
from .labels import _invalid, adapt_model_reply
from .output_grammar import MAX_OUTPUT_GRAMMAR_BYTES, MAX_SUPPORTING_OBJECT_IDS, RoomOutputGrammar
from .prompt import PromptBudget, PromptRecord, RoomPromptError
from .requests import RoomLabelRequest


COMPACT_POLICY_VERSION = 'room-compact-v2'
COMPACT_MAX_OUTPUT_TOKENS = 64
_CATEGORY = re.compile(r'^[a-z0-9]+(?:[ _-][a-z0-9]+)*$')
_LABELS = tuple(sorted(ROOM_LABELS - {'unknown'}))

# Room-independent: identical bytes for every request so the server-side
# prompt cache keeps it. Generic common-sense cues only; no scene annotation.
STATIC_PREFIX = (
    'You name rooms of an indoor 3D scene graph from the objects detected inside each room.\n'
    'Room types: ' + ', '.join(_LABELS) + '.\n'
    'Typical evidence: toilet, bathtub, shower, or sink with mirror or towel -> bathroom; '
    'bed, nightstand, wardrobe or dresser -> bedroom; '
    'sofa, armchair, television, coffee table or fireplace -> living_room; '
    'fridge, oven, microwave, dishwasher, kitchen island or counter -> kitchen; '
    'dining table with chairs -> dining_room; '
    'desk, computer monitor, printer or laptop -> office; '
    'washing machine -> utility; '
    'clear evidence for two different room types -> mixed.\n'
    'Doors, windows, paintings, curtains, rugs, carpets, lamps, plants, clocks, vases '
    'and pillows alone do not identify a room.\n'
    'Answer with one line: room_type|other plausible room types (0 to 2, comma separated)|'
    'numbers of the objects that support room_type (ascending, comma separated).\n'
    'Decide only from the objects listed below for this room.\n'
    'If the objects do not identify a room, answer: unknown\n'
    'Objects in this room:\n'
)


def _checked_objects(request: RoomLabelRequest):
    allowed = set(request.source_manifest.get('canonical_categories', ()))
    rows = []
    for item in request.context.objects:
        if not _CATEGORY.fullmatch(item.category) or item.category not in allowed:
            raise RoomPromptError('noncanonical_object_category')
        rows.append(item)
    return rows


def render_compact_room_prompt(request: RoomLabelRequest, tokenizer,
                               budget: PromptBudget | int) -> PromptRecord:
    if not isinstance(request, RoomLabelRequest):
        raise TypeError('request must be RoomLabelRequest')
    if isinstance(budget, int) and not isinstance(budget, bool):
        budget = PromptBudget(budget)
    if not isinstance(budget, PromptBudget):
        raise TypeError('budget must be PromptBudget or integer token count')
    blocked = request.inference_block_reason
    if blocked:
        raise RoomPromptError(blocked)
    if tokenizer is None:
        raise ValueError('tokenizer is required to enforce the input budget')
    rows = _checked_objects(request)
    prompt = STATIC_PREFIX + ''.join(
        f'{index} {item.category}\n' for index, item in enumerate(rows, start=1))
    encoded = tokenizer.encode(prompt) if hasattr(tokenizer, 'encode') else tokenizer(prompt)
    token_count = len(encoded)
    if token_count > budget.max_input_tokens:
        raise RoomPromptError('context_budget_exceeded')
    return PromptRecord(prompt, hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
        COMPACT_SCHEMA_SHA256, tuple(item.native_id for item in request.context.objects),
        token_count, False)


def _literal(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _support_rules(terminals: tuple[str, ...]) -> list[str]:
    """Sorted, unique, nonempty subsets of size <= 8, as one unambiguous DAG."""
    n = len(terminals)
    rules = [f'sid-{index} ::= {_literal(value)}' for index, value in enumerate(terminals)]
    starts = [f'sid-{index}' + (f' smore-{index + 1}-{MAX_SUPPORTING_OBJECT_IDS - 1}?'
        if index + 1 < n else '') for index in range(n)]
    rules.append('support-list ::= ' + ' | '.join(starts))
    for remaining in range(1, MAX_SUPPORTING_OBJECT_IDS):
        for index in range(n - 1, -1, -1):
            alternatives = [f'"," sid-{index}']
            if remaining > 1 and index + 1 < n:
                alternatives[0] += f' smore-{index + 1}-{remaining - 1}?'
            if index + 1 < n:
                alternatives.append(f'smore-{index + 1}-{remaining}')
            rules.append(f'smore-{index}-{remaining} ::= ' + ' | '.join(alternatives))
    return rules


def build_compact_output_grammar(request: RoomLabelRequest) -> RoomOutputGrammar:
    if not isinstance(request, RoomLabelRequest):
        raise TypeError('request must be RoomLabelRequest')
    rows = request.context.objects
    support = tuple(str(index) for index, item in enumerate(rows, start=1)
        if item.membership_status == 'assigned')
    rules = ['root ::= ' + ' | '.join(['"unknown"'] +
        ([f'proposal-{index}' for index in range(len(_LABELS))] if support else []))]
    if support:
        for index, label in enumerate(_LABELS):
            others = [item for item in _LABELS if item != label]
            choices = others + [','.join(pair) for pair in itertools.combinations(others, 2)]
            rules.append(f'alts-{index} ::= ' + ' | '.join(_literal(item) for item in choices))
            rules.append(f'proposal-{index} ::= {_literal(label + "|")} alts-{index}? '
                f'"|" support-list')
        rules.extend(_support_rules(support))
    grammar_text = '\n'.join(rules) + '\n'
    if len(grammar_text.encode('utf-8')) > MAX_OUTPUT_GRAMMAR_BYTES:
        raise ValueError(f'room output grammar exceeds {MAX_OUTPUT_GRAMMAR_BYTES} bytes')
    support_ids = tuple(rows[int(value) - 1].native_id for value in support)
    return RoomOutputGrammar(grammar_text,
        hashlib.sha256(grammar_text.encode('utf-8')).hexdigest(),
        COMPACT_POLICY_VERSION, tuple(sorted(support_ids)))


_WIRE = re.compile(r'^([a-z_]+)\|([a-z_,]*)\|([0-9,]+)$')


def adapt_compact_reply(raw, request: RoomLabelRequest, *, model_hash: str,
                        prompt_hash: str) -> RoomLabelProposal:
    """Expand one compact line into canonical JSON, then apply the strict adapter."""
    if not isinstance(request, RoomLabelRequest):
        raise TypeError('request must be RoomLabelRequest')
    if not isinstance(raw, str):
        return _invalid(request, model_hash, prompt_hash, 'response_not_text')
    line = raw.strip()
    if len(line) > 1024:
        return _invalid(request, model_hash, prompt_hash, 'compact_response_too_long')
    if line == 'unknown':
        canonical = {'label': 'unknown', 'alternatives': [], 'supporting_object_ids': [],
            'status': 'unknown', 'reason': 'model abstained: objects do not identify a room type'}
        return adapt_model_reply(json.dumps(canonical), request,
            model_hash=model_hash, prompt_hash=prompt_hash)
    match = _WIRE.fullmatch(line)
    if match is None:
        return _invalid(request, model_hash, prompt_hash, 'compact_response_malformed')
    label, alternatives_text, indices_text = match.groups()
    alternatives = [item for item in alternatives_text.split(',') if item] if alternatives_text else []
    if alternatives_text and len(alternatives) != len(alternatives_text.split(',')):
        return _invalid(request, model_hash, prompt_hash, 'compact_response_malformed')
    try:
        indices = [int(item) for item in indices_text.split(',')]
    except ValueError:
        return _invalid(request, model_hash, prompt_hash, 'compact_response_malformed')
    rows = request.context.objects
    if any(index < 1 or index > len(rows) for index in indices):
        return _invalid(request, model_hash, prompt_hash, 'unsupported_object_id')
    supporting = [rows[index - 1].native_id for index in indices]
    evidence = ', '.join(f'{rows[index - 1].category} {rows[index - 1].native_id}'
        for index in indices)
    reason = f'supported by {evidence}'
    if len(reason) > 256:
        reason = reason[:253] + '...'
    canonical = {'label': label, 'alternatives': alternatives,
        'supporting_object_ids': supporting, 'status': 'proposed', 'reason': reason}
    return adapt_model_reply(json.dumps(canonical), request,
        model_hash=model_hash, prompt_hash=prompt_hash)


COMPACT_SCHEMA_SHA256 = hashlib.sha256(
    (COMPACT_POLICY_VERSION + '\0' + STATIC_PREFIX).encode('utf-8')).hexdigest()
