"""Offline room centroid features resolved against one native membership revision."""
from dataclasses import dataclass

import numpy as np

from ..contracts.hydra_graph import NativeNodeRef
from ..contracts.reasoninggraph import FeatureSpec, GraphReadToken
from .lifecycle import validate_progress
from .semantic_encoder import unit_vector


@dataclass(frozen=True)
class RoomFeature:
    ref: NativeNodeRef
    centroids: tuple[tuple[float, ...], ...]
    support: int


@dataclass(frozen=True)
class RoomFeatureView:
    token: GraphReadToken
    spec: FeatureSpec
    rooms: tuple[RoomFeature, ...]
    pending: int


@dataclass(frozen=True)
class RankedRoom:
    ref: NativeNodeRef
    score: float
    support: int


def _centroids(vectors, count, iterations):
    centers = [vectors[0]]
    while len(centers) < min(count, len(vectors)):
        closest = (vectors @ np.asarray(centers).T).max(axis=1)
        index = int(closest.argmin())
        if closest[index] >= 1. - 1e-12:
            break
        centers.append(vectors[index])
    current = np.array(centers)
    for _ in range(iterations):
        assignments = (vectors @ current.T).argmax(axis=1)
        updated = []
        for index, old in enumerate(current):
            group = vectors[assignments == index]
            mean = None if not len(group) else unit_vector(group.sum(axis=0), vectors.shape[1])
            updated.append(old if mean is None else mean)
        revised = np.asarray(updated)
        if np.allclose(revised, current, rtol=0., atol=1e-9):
            break
        current = revised
    return tuple(tuple(float(x) for x in row) for row in current)


class RoomFeatureStore:
    def __init__(self, token, spec, *, clusters=3, iterations=25, max_frames=512, max_bytes=8*1024**2):
        if not isinstance(token, GraphReadToken) or not isinstance(spec, FeatureSpec):
            raise TypeError('room feature store requires a graph token and feature spec')
        if spec.modality != 'room' or not spec.normalized:
            raise ValueError('expected a normalized room feature space')
        for value, maximum in ((clusters, 10), (iterations, 100), (max_frames, 4096), (max_bytes, 32*1024**2)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('invalid room feature budget')
        self._latest = token
        self._spec = spec
        self._clusters, self._iterations = clusters, iterations
        self._max_frames, self._max_bytes = max_frames, max_bytes
        self._views = {}

    def observe_room_view(self, token, feature):
        if token.source in self._views:
            return False
        validate_progress(self._latest, token)
        if (len(self._views) == self._max_frames
                or (len(self._views)+1)*self._spec.dimension*8 > self._max_bytes):
            return False
        vector = unit_vector(feature, self._spec.dimension)
        if vector is None:
            return False
        self._views[token.source] = np.asarray(vector, dtype=np.float64)
        self._latest = token
        return True

    def recluster(self, token, memberships):
        """Use assignments supplied by the owner for the target geometry revision."""
        validate_progress(self._latest, token)
        assigned = {}
        pending = 0
        for source, vector in self._views.items():
            ref = memberships.get(source)
            if ref is None:
                pending += 1
            elif not isinstance(ref, NativeNodeRef) or ref.layer_id != 4 or ref.token != token.native:
                raise ValueError('membership must bind an exact room revision')
            else:
                assigned.setdefault(ref, []).append(vector)
        rooms = []
        for ref, vectors in sorted(assigned.items(), key=lambda item: item[0].native_id):
            rooms.append(RoomFeature(ref, _centroids(np.asarray(vectors), self._clusters, self._iterations),
                                     len(vectors)))
        return RoomFeatureView(token, self._spec, tuple(rooms), pending)


def rank_rooms(view, query_vector, spec, *, scoring='mean', top_k=10):
    if not isinstance(view, RoomFeatureView) or view.spec != spec:
        raise ValueError('query uses a different feature space')
    if scoring not in {'mean', 'max'} or type(top_k) is not int or not 1 <= top_k <= 128:
        raise ValueError('invalid room ranking policy')
    query = unit_vector(query_vector, spec.dimension)
    if query is None:
        raise ValueError('invalid room query vector')
    ranked = []
    for room in view.rooms:
        scores = np.clip(np.asarray(room.centroids) @ query, -1., 1.)
        score = scores.mean() if scoring == 'mean' else scores.max()
        ranked.append(RankedRoom(room.ref, float(score), room.support))
    return tuple(sorted(ranked, key=lambda value: (-value.score, value.ref.native_id))[:top_k])
