"""Persistent local vision-language room labelling with evidence-bound output."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
import time

from ..contracts.room_semantics import ROOM_LABELS, RoomLabelProposal
from .labels import MAX_RESPONSE_BYTES, _unique_fields
from .output_grammar import (_alternatives_rule, _gbnf_literal, _reason_rules,
    _support_rules, RoomOutputGrammar, MAX_OUTPUT_GRAMMAR_BYTES)
from .persistent_backend import PersistentRoomLabelBackend, _BackendUnavailable
from .prompt import PromptRecord, RoomPromptError
from .requests import RoomLabelRequest

_MAX_VIEWS = 8
_MAX_JPEG_BYTES = 2 * 1024 * 1024


def _validate_views(request, views):
    if not isinstance(views, tuple) or len(views) > _MAX_VIEWS:
        raise RoomPromptError('invalid_room_views')
    ids = set()
    for view in views:
        try:
            ident, jpeg = view.view_id, view.jpeg
            valid = (isinstance(ident, str) and re.fullmatch(r'[0-9a-f]{64}', ident)
                and isinstance(jpeg, bytes) and 0 < len(jpeg) <= _MAX_JPEG_BYTES
                and hashlib.sha256(jpeg).hexdigest() == ident
                and view.room_id == request.key.room_id
                and type(view.frame_index) is int and view.frame_index >= 0
                and type(view.graph_revision) is int and 0 <= view.graph_revision <= request.key.graph_revision
                and isinstance(view.manifest(), dict))
        except (AttributeError, TypeError, ValueError):
            valid = False
        if not valid or ident in ids:
            raise RoomPromptError('invalid_room_views')
        ids.add(ident)


def _slots(request, views):
    objects = [item for item in request.context.objects if item.membership_status == 'assigned']
    return ({f'o{i+1}': item.native_id for i, item in enumerate(objects)},
            {f'v{i+1}': view.view_id for i, view in enumerate(views)})


def _grammar(request, views):
    objects, images = _slots(request, views)
    rules = ['root ::= abstain' + (' | ' + ' | '.join(
        f'proposal-{i}' for i in range(len(ROOM_LABELS)-1)) if objects or images else '')]
    rules.append('abstain ::= ' + _gbnf_literal('{"l":"unknown","o":[],"v":[]}'))
    if objects:
        rules += _support_rules(tuple(sorted(objects)))
    if images:
        rules += [re.sub(r'\bsupport-', 'view-', rule) for rule in _support_rules(tuple(sorted(images)))]
    for i, label in enumerate(sorted(ROOM_LABELS - {'unknown'})) if objects or images else ():
        prefix = '{"l":' + json.dumps(label) + ',"o":['
        middle = '],"v":['
        combos = []
        if objects:
            combos.append('support-list ' + _gbnf_literal(middle) + (' view-list?' if images else ''))
        if images:
            combos.append(_gbnf_literal(middle) + ' view-list')
        rules.append(f'proposal-{i} ::= {_gbnf_literal(prefix)} (' + ' | '.join(combos) +
                     f') {_gbnf_literal("]}")}')
    grammar = '\n'.join(rules) + '\n'
    if len(grammar.encode()) > MAX_OUTPUT_GRAMMAR_BYTES:
        raise RoomPromptError('output_grammar_budget_exceeded')
    return RoomOutputGrammar(grammar, hashlib.sha256(grammar.encode()).hexdigest(), 'room-vlm-slots-v2', tuple(objects.values()))


def build_vlm_prompt(request, views, tokenizer, max_tokens):
    _validate_views(request, views)
    allowed = set(request.source_manifest.get('canonical_categories', ()))
    objects = []
    for item in request.context.objects:
        if not item.category.isascii() or item.category not in allowed:
            raise RoomPromptError('noncanonical_object_category')
        objects.append(item)
    slots, _ = _slots(request, views)
    categories = {item.native_id: item.category for item in objects}
    data = {'objects': {slot: categories[ident] for slot, ident in slots.items()},
            'images': [f'v{i+1}' for i in range(len(views))]}
    prompt = ('Classify the room using only these objects and images, in the listed image order. '
        'Labels: ' + ', '.join(sorted(ROOM_LABELS)) + '. '
        'If uncertain choose unknown. Return JSON with keys l (label), o (supporting object slots), '
        'v (supporting image slots). For a known label cite at least one actual supporting slot. '
        'For unknown use empty arrays. Sort slots lexicographically. Evidence: ' +
        json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True))
    tokens = tokenizer.encode(prompt) if hasattr(tokenizer, 'encode') else tokenizer(prompt)
    if len(tokens) > max_tokens:
        raise RoomPromptError('context_budget_exceeded')
    grammar = _grammar(request, views)
    binding = json.dumps({'text': prompt, 'objects': slots,
        'views': [v.view_id for v in views]}, sort_keys=True, separators=(',', ':'))
    digest = hashlib.sha256(binding.encode()).hexdigest()
    return PromptRecord(prompt, digest, grammar.grammar_sha256,
        tuple(item.native_id for item in request.context.objects), len(tokens), False), grammar


def adapt_vlm_reply(raw, request, views, *, model_hash, prompt_hash):
    def invalid(reason):
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision, request.key.context_hash,
            'unknown', (), (), 'invalid_output', reason, model_hash, prompt_hash)
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > MAX_RESPONSE_BYTES:
        return invalid('response_not_text_or_too_large')
    try:
        value = json.loads(raw, object_pairs_hook=_unique_fields)
        if not isinstance(value, dict) or set(value) != {'l', 'o', 'v'}:
            return invalid('response_schema_mismatch')
        label, obj, vis = value['l'], value['o'], value['v']
        if (not isinstance(label, str) or label not in ROOM_LABELS
            or not isinstance(obj,list) or len(obj)>8 or any(not isinstance(x,str) for x in obj) or len(set(obj)) != len(obj)
            or not isinstance(vis,list) or len(vis)>8 or any(not isinstance(x,str) for x in vis) or len(set(vis)) != len(vis)):
            return invalid('response_field_invalid')
        object_slots, view_slots = _slots(request, views)
        if not set(obj) <= object_slots.keys() or not set(vis) <= view_slots.keys():
            return invalid('unsupported_evidence_id')
        if label != 'unknown' and not (obj or vis):
            return invalid('proposed_label_missing_support')
        if label == 'unknown' and (obj or vis):
            return invalid('abstention_cannot_claim_support')
        return RoomLabelProposal(request.key.room_id, request.key.graph_revision, request.key.context_hash,
            label, (), tuple(object_slots[x] for x in obj), 'unknown' if label == 'unknown' else 'proposed',
            'insufficient evidence' if label == 'unknown' else 'model selected cited evidence',
            model_hash, prompt_hash, supporting_view_ids=tuple(view_slots[x] for x in vis))
    except (ValueError, TypeError, KeyError, UnicodeError):
        return invalid('malformed_json')


class RoomVlmBackend(PersistentRoomLabelBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._views_local = threading.local()

    def infer(self, request: RoomLabelRequest, *, views=()):
        if not isinstance(request, RoomLabelRequest):
            raise TypeError('request must be RoomLabelRequest')
        try:
            _validate_views(request, views)
        except RoomPromptError as exc:
            started = time.monotonic_ns()
            return self._finish(self._failure(request, 'insufficient_evidence', exc.reason),
                self._initial_metrics(request), started)
        self._views_local.views = views
        try:
            return super().infer(request)
        finally:
            self._views_local.views = ()

    def _inference_block_reason(self, request):
        reason = request.inference_block_reason
        return None if reason == 'no_semantic_objects' and self._views_local.views else reason

    def _validate_runtime_pins(self):
        super()._validate_runtime_pins()
        if not self.config.mmproj_path or not self.config.mmproj_sha256:
            raise _BackendUnavailable('mmproj_asset_not_configured')

    def _infer_one(self, request, generation, deadline, metrics):
        self._validate_runtime_pins()
        process, base, reused = self._existing_or_start(request, generation, deadline, metrics)
        metrics.update(server_reused=reused, server_pid=getattr(process, 'pid', None))
        views = self._views_local.views
        def tokenize(prompt):
            response = self._http_deadlined('POST', base + '/tokenize', {'content':prompt}, deadline, generation)
            tokens = response.get('tokens') if isinstance(response, dict) else None
            if not isinstance(tokens, list):
                raise _BackendUnavailable('runtime_tokenize_endpoint_invalid')
            metrics['text_prompt_tokens'] = len(tokens)
            return tokens
        prompt, grammar = build_vlm_prompt(request, views, tokenize, self.config.max_input_tokens)
        metrics.update(prompt_sha256=prompt.prompt_sha256, schema_sha256=prompt.schema_sha256,
            grammar_policy_version=grammar.policy_version, grammar_sha256=grammar.grammar_sha256,
            grammar_bytes=len(grammar.grammar_text.encode()), constraint_transport='request_bound_gbnf')
        content = [{'type':'text','text':prompt.prompt_text}]
        content += [{'type':'image_url', 'image_url':{'url':'data:image/jpeg;base64,' + base64.b64encode(v.jpeg).decode('ascii')}} for v in views]
        body = {'model':self.config.model_id, 'messages':[{'role':'user','content':content}],
            'temperature':0, 'seed':0, 'max_tokens':self.config.max_output_tokens, 'stream':False,
            'cache_prompt':False, 'chat_template_kwargs':{'enable_thinking':False}, 'grammar':grammar.grammar_text}
        response = self._http_deadlined('POST', base + '/v1/chat/completions', body, deadline, generation, max_response_bytes=128*1024)
        choice = response['choices'][0]
        raw = choice['message']['content']
        metrics.update(native_timings=response.get('timings'), native_usage=response.get('usage'), finish_reason=choice.get('finish_reason'))
        usage = response.get('usage')
        if isinstance(usage, dict) and type(usage.get('prompt_tokens')) is int:
            metrics['prompt_tokens'] = usage['prompt_tokens']
            if usage['prompt_tokens'] > self.config.max_input_tokens:
                return self._failure(request, 'insufficient_evidence', 'context_budget_exceeded',
                    model_hash=self.config.model_sha256, prompt_hash=prompt.prompt_sha256), process
        if isinstance(raw, str):
            metrics.update(raw_output_sha256=hashlib.sha256(raw.encode()).hexdigest(), raw_output_bytes=len(raw.encode()))
        self._check_active(generation, deadline)
        if choice.get('finish_reason') == 'length':
            return self._failure(request, 'invalid_output', 'generation_truncated', model_hash=self.config.model_sha256, prompt_hash=prompt.prompt_sha256), process
        return adapt_vlm_reply(raw, request, views, model_hash=self.config.model_sha256, prompt_hash=prompt.prompt_sha256), process
