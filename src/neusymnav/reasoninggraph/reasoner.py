"""Synchronous fixture reasoner: no action authority or relation inference."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import time

from ..contracts.hydra_graph import NativeNodeRef
from ..contracts.reasoninggraph import FeatureSpec, GraphReadToken
from .query import RevisionQuery


_DIRECT_REQUEST = re.compile(r'find [a-z][a-z0-9_]{0,63}')


@dataclass(frozen=True)
class ReasoningBudget:
    max_calls: int = 2
    max_response_chars: int = 2048
    deadline: float = float('inf')  # absolute time in the injected monotonic clock

    def __post_init__(self):
        if (type(self.max_calls) is not int or not 0 <= self.max_calls <= 2
                or type(self.max_response_chars) is not int or not 1 <= self.max_response_chars <= 8192
                or not isinstance(self.deadline, (int, float)) or math.isnan(self.deadline)):
            raise ValueError('invalid reasoning budget')


@dataclass(frozen=True)
class Proposal:
    status: str
    ref: NativeNodeRef | None
    evidence: tuple
    trace: tuple[str, ...]
    model_id: str
    prompt_id: str
    token: GraphReadToken | None = None


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate field')
        result[key] = value
    return result


class TaskReasoner:
    """Fixture transport must return JSON strings; deadline does not cancel it."""

    def __init__(self, completion, *, model_id, prompt_id, clock=time.monotonic):
        if (not callable(completion) or not callable(clock)
                or any(not isinstance(x, str) or not 0 < len(x) <= 256 for x in (model_id, prompt_id))):
            raise ValueError('invalid reasoner configuration')
        self._completion, self._clock = completion, clock
        self.model_id, self.prompt_id = model_id, prompt_id

    def propose(self, view, token, instruction, vector, spec, budget):
        """Evaluate the fixture grammar `find <category_slug>` on one read view."""
        trace = []
        def abstain(reason):
            return Proposal('insufficient_evidence', None, (), tuple(trace + [reason]), self.model_id, self.prompt_id)
        if not isinstance(view, RevisionQuery) or not isinstance(budget, ReasoningBudget):
            raise ValueError('invalid reasoner inputs')
        if (not isinstance(instruction, str) or len(instruction) > 69
                or not _DIRECT_REQUEST.fullmatch(instruction)):
            return abstain('unsupported_instruction')
        if budget.max_calls < 2:
            return abstain('call_budget')
        try:
            if not isinstance(spec, FeatureSpec) or spec.modality not in {'object', 'room'}:
                return abstain('unsupported_feature_space')
            kind = spec.modality

            def check():
                if self._clock() >= budget.deadline:
                    raise TimeoutError()
                view.require_current(token)

            def call(stage, payload):
                check()
                raw = self._completion(stage, payload)
                check()
                if not isinstance(raw, str) or len(raw) > budget.max_response_chars:
                    raise ValueError('invalid completion')
                return json.loads(raw, object_pairs_hook=_pairs)

            check()
            rank = view.objects if kind == 'object' else view.rooms
            candidates = tuple(item for item in rank(token, vector, spec).items if item.support > 0)
            if not candidates:
                return abstain('missing_candidates')
            parsed = call('parse', {'instruction': instruction, 'model_id': self.model_id, 'prompt_id': self.prompt_id})
            if not isinstance(parsed, dict) or set(parsed) != {'kind'} or parsed['kind'] != kind:
                return abstain('unsupported_or_ambiguous')
            trace.append('parse:' + kind)
            payload = {'instruction': instruction, 'kind': kind, 'allowed_ids': tuple(c.ref.native_id for c in candidates),
                       'ranked_candidates': tuple((c.ref.native_id, c.cosine if kind == 'object' else c.score, c.support) for c in candidates),
                       'model_id': self.model_id, 'prompt_id': self.prompt_id}
            selected = call('select', payload)
            if not isinstance(selected, dict) or set(selected) != {'id'} or not isinstance(selected['id'], str):
                return abstain('invalid_selection')
            match = next((c for c in candidates if c.ref.native_id == selected['id']), None)
            if match is None:
                return abstain('foreign_id')
            check()
            trace.append('select:grounded')
            return Proposal('proposed', match.ref, (('feature_support', match.support),),
                            tuple(trace), self.model_id, self.prompt_id, token)
        except Exception:
            return abstain('unavailable_or_invalid')
