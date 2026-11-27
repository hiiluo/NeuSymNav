"""Offline pooling and retrieval scoped to one native object revision."""
from dataclasses import dataclass

import numpy as np

from ..contracts.hydra_graph import NativeNodeRef
from ..contracts.reasoninggraph import FeatureSpec, GraphReadToken
from .semantic_encoder import CHANNELS, ObjectChannels, ObjectRecipe, unit_vector


@dataclass(frozen=True)
class ObjectFeature:
    ref: NativeNodeRef
    vector: tuple[float, ...]
    support: int


@dataclass(frozen=True)
class ObjectFeatureView:
    token: GraphReadToken
    spec: FeatureSpec
    objects: tuple[ObjectFeature, ...]


@dataclass(frozen=True)
class RankedObject:
    ref: NativeNodeRef
    cosine: float
    support: int


class ObjectFeatureStore:
    def __init__(self, token, spec, recipe, *, max_events=4096, max_bytes=8*1024**2):
        if not isinstance(token, GraphReadToken) or not isinstance(spec, FeatureSpec):
            raise TypeError('object feature store requires exact graph token and spec')
        if spec.modality != 'object' or not spec.normalized or not isinstance(recipe, ObjectRecipe):
            raise ValueError('invalid object feature store recipe or spec')
        if (type(max_events) is not int or not 1 <= max_events <= 8192
                or type(max_bytes) is not int or not 1 <= max_bytes <= 32*1024**2):
            raise ValueError('invalid object feature store caps')
        self._token, self._spec, self._recipe = token, spec, recipe
        self._events, self._accumulators = set(), {}
        self._max_events, self._max_bytes = max_events, max_bytes

    def add(self, ref, evidence_id, channels):
        if not isinstance(ref, NativeNodeRef) or ref.layer_id != 2 or ref.token != self._token.native:
            raise ValueError('object feature requires an exact object revision')
        if not isinstance(channels, ObjectChannels) or channels.spec != self._spec:
            raise ValueError('object feature has a different feature space')
        if not isinstance(evidence_id, str) or not 0 < len(evidence_id) <= 256:
            raise ValueError('invalid feature evidence ID')
        if evidence_id in self._events or len(self._events) == self._max_events:
            return False
        pending = ref not in self._accumulators
        if (len(self._accumulators) + pending) * self._spec.dimension * 8 > self._max_bytes:
            return False
        features, weights = [], []
        for name, weight in zip(CHANNELS, self._recipe.weights):
            value = getattr(channels, name)
            if value is not None and weight > 0:
                vector = unit_vector(value, self._spec.dimension)
                if vector is None:
                    raise ValueError('invalid object feature vector')
                features.append(vector)
                weights.append(weight)
        if not features:
            return False
        combined = np.average(features, axis=0, weights=weights)
        if unit_vector(combined, self._spec.dimension) is None:
            return False
        old, count = self._accumulators.get(ref, (0., 0))
        self._accumulators[ref] = old + combined, count + 1
        self._events.add(evidence_id)
        return True

    def view(self):
        objects = []
        for ref, (total, support) in sorted(self._accumulators.items(), key=lambda pair: pair[0].native_id):
            vector = unit_vector(total, self._spec.dimension)
            if vector is not None:
                objects.append(ObjectFeature(ref, vector, support))
        return ObjectFeatureView(self._token, self._spec, tuple(objects))


def rank_objects(view, query_vector, spec, top_k=10, room_scope=None):
    if not isinstance(view, ObjectFeatureView) or view.spec != spec:
        raise ValueError('query uses a different feature space')
    if type(top_k) is not int or not 1 <= top_k <= 128:
        raise ValueError('invalid rank limit')
    query = unit_vector(query_vector, spec.dimension)
    if query is None:
        raise ValueError('invalid query vector')
    scope = None if room_scope is None else frozenset(room_scope)
    candidates = [RankedObject(item.ref, float(np.clip(np.dot(item.vector, query), -1., 1.)), item.support)
                  for item in view.objects if scope is None or item.ref in scope]
    return tuple(sorted(candidates, key=lambda item: (-item.cosine, item.ref.native_id))[:top_k])
