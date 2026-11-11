"""Request-specific, bounded GBNF for consistent room-label model output."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import itertools
import json

from ..contracts.room_semantics import ROOM_LABELS
from .context import MAX_CONTEXT_OBJECTS
from .requests import RoomLabelRequest


OUTPUT_GRAMMAR_POLICY_VERSION = 'room-output-consistency-v1'
MAX_OUTPUT_GRAMMAR_BYTES = 256 * 1024
MAX_NATIVE_ID_UTF8_BYTES = 128
MAX_SUPPORTING_OBJECT_IDS = 8
MAX_REASON_CHARS = 256


@dataclass(frozen=True, slots=True)
class RoomOutputGrammar:
    grammar_text: str
    grammar_sha256: str
    policy_version: str
    allowed_support_ids: tuple[str, ...]


def _gbnf_literal(value: str) -> str:
    """Quote exact text as one GBNF terminal, escaping GBNF syntax chars."""
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(',', ':'))


def _support_rules(ids: tuple[str, ...]) -> list[str]:
    """Build an unambiguous O(n*k) DAG for sorted nonempty subsets of size <= 8."""
    if not ids:
        return []

    rules = [f'support-id-{index} ::= {_gbnf_literal(_json_string(native_id))}'
        for index, native_id in enumerate(ids)]
    n = len(ids)
    # A root must choose a first ID. Each optional `more` rule is nonempty;
    # skipped IDs can therefore never introduce duplicate empty derivations.
    starts = [f'support-id-{index}' +
        (f' support-more-{index + 1}-7?' if index + 1 < n else '')
        for index in range(n)]
    rules.append('support-list ::= ' + ' | '.join(starts))

    # Each `more` rule chooses its first later member, optionally chooses a
    # bounded suffix, or skips only when a later member will be selected.
    for remaining in range(1, MAX_SUPPORTING_OBJECT_IDS):
        for index in range(n - 1, -1, -1):
            alternatives = [f'"," support-id-{index}']
            if remaining > 1 and index + 1 < n:
                alternatives[0] += f' support-more-{index + 1}-{remaining - 1}?'
            if index + 1 < n:
                alternatives.append(f'support-more-{index + 1}-{remaining}')
            rules.append(f'support-more-{index}-{remaining} ::= '
                + ' | '.join(alternatives))
    return rules


def _alternatives_rule(index: int, primary: str) -> list[str]:
    remaining = sorted(ROOM_LABELS - {primary})
    arrays = ['[]']
    arrays.extend(json.dumps([item], ensure_ascii=True, separators=(',', ':'))
        for item in remaining)
    arrays.extend(json.dumps([first, second], ensure_ascii=True, separators=(',', ':'))
        for first, second in itertools.combinations(remaining, 2))
    return [f'alternatives-{index} ::= ' + ' | '.join(
        _gbnf_literal(value) for value in arrays)]


def _reason_rules() -> list[str]:
    # The first decoded character must be printable ASCII and non-space. Use
    # JSON's exact spelling for the terminal, so quote/backslash are escaped.
    first_chars = [chr(codepoint) for codepoint in range(0x21, 0x7f)]
    first_terminals = [_gbnf_literal(_json_string(char)[1:-1]) for char in first_chars]
    return [
        'reason-json-string ::= "\\\"" reason-first reason-tail "\\\""',
        'reason-first ::= ' + ' | '.join(first_terminals),
        r'reason-char ::= [^"\\\x7F\x00-\x1F] | "\\" (["\\bfnrt] | "u" [0-9a-fA-F]{4})',
        f'reason-tail ::= reason-char{{0,{MAX_REASON_CHARS - 1}}}',
    ]


def build_room_output_grammar(request: RoomLabelRequest) -> RoomOutputGrammar:
    """Compile the exact output language allowed for one bounded room request.

    This is a syntax-level constraint only. Callers must still apply the strict
    host adapter to every generated response.
    """
    if not isinstance(request, RoomLabelRequest):
        raise TypeError('request must be RoomLabelRequest')

    objects = request.context.objects
    if len(objects) > MAX_CONTEXT_OBJECTS:
        raise ValueError(f'room output grammar supports at most {MAX_CONTEXT_OBJECTS} objects')

    support_ids = sorted({item.native_id for item in objects
        if item.membership_status == 'assigned'})
    for native_id in support_ids:
        if not isinstance(native_id, str) or not native_id.strip():
            raise ValueError('assigned native object IDs must be nonempty strings')
        try:
            encoded = native_id.encode('utf-8')
        except UnicodeEncodeError as exc:
            raise ValueError('assigned native object IDs must be valid UTF-8') from exc
        if len(encoded) > MAX_NATIVE_ID_UTF8_BYTES:
            raise ValueError(f'assigned native object IDs must be <= {MAX_NATIVE_ID_UTF8_BYTES} UTF-8 bytes')

    rules = ['root ::= ' + ' | '.join(
        ['abstain-unknown', 'abstain-insufficient'] +
        ([f'proposal-{index}' for index, label in enumerate(sorted(ROOM_LABELS - {'unknown'}))]
            if support_ids else []))]
    rules.extend(_reason_rules())

    abstention_prefixes = {
        'unknown': '{"label":"unknown","alternatives":[],"supporting_object_ids":[],"status":"unknown","reason":',
        'insufficient': '{"label":"unknown","alternatives":[],"supporting_object_ids":[],"status":"insufficient_evidence","reason":',
    }
    for name, prefix in abstention_prefixes.items():
        rules.append(f'abstain-{name} ::= {_gbnf_literal(prefix)} reason-json-string {_gbnf_literal("}")}')

    if support_ids:
        labels = sorted(ROOM_LABELS - {'unknown'})
        for index, primary in enumerate(labels):
            rules.extend(_alternatives_rule(index, primary))
            prefix = ('{"label":' + _json_string(primary) + ',"alternatives":')
            # Keep the wire format canonical and whitespace-free.
            middle = ',"supporting_object_ids":['
            suffix = '],"status":"proposed","reason":'
            rules.append(f'proposal-{index} ::= {_gbnf_literal(prefix)} alternatives-{index} '
                f'{_gbnf_literal(middle)} support-list {_gbnf_literal(suffix)} '
                f'reason-json-string {_gbnf_literal("}")}')
        rules.extend(_support_rules(tuple(support_ids)))

    grammar_text = '\n'.join(rules) + '\n'
    grammar_size = len(grammar_text.encode('utf-8'))
    if grammar_size > MAX_OUTPUT_GRAMMAR_BYTES:
        raise ValueError(f'room output grammar exceeds {MAX_OUTPUT_GRAMMAR_BYTES} bytes')
    sha256 = hashlib.sha256(grammar_text.encode('utf-8')).hexdigest()
    return RoomOutputGrammar(grammar_text, sha256, OUTPUT_GRAMMAR_POLICY_VERSION,
        tuple(support_ids))
