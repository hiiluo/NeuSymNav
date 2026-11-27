"""Conservative single-writer fold of durable Hydra object-owner events."""
from dataclasses import dataclass
from itertools import islice
from types import MappingProxyType

from ..contracts.hydra_graph import HydraReadToken
from ..contracts.hydra_lineage import NativeObjectBatch, object_id
from .lifecycle import _graph_scope


@dataclass(frozen=True)
class CanonicalObjectId:
    episode_id: str
    run_id: str
    epoch: int
    native_id: str


@dataclass(frozen=True)
class ObjectLineageView:
    token: HydraReadToken
    epoch: int
    objects: MappingProxyType
    aliases: MappingProxyType

    def resolve(self, identity):
        if not isinstance(identity, CanonicalObjectId):
            return None
        if (identity.episode_id, identity.run_id, identity.epoch) != (
                self.token.episode_id, self.token.run_id, self.epoch):
            return None
        raw = identity.native_id
        while raw in self.aliases:
            raw = self.aliases[raw]
        return self.objects.get(raw)


class NativeObjectLineage:
    """Open from revision one. Revoke continuity after an unaccounted mutation."""

    def __init__(self, *, max_objects=8192):
        if type(max_objects) is not int or not 1 <= max_objects <= 16384:
            raise ValueError('invalid lineage object budget')
        self._max = max_objects
        self._view = None
        self._last_batch = None
        self._allocated = set()
        self._aliases = {}
        self._backend_endpoints = set()
        self.failure = None

    def read(self, token):
        if self.failure is None and self._view is not None and token == self._view.token:
            return self._view
        return None

    def apply(self, token, batch, native_objects):
        if self.failure is not None:
            return None
        try:
            if not isinstance(token, HydraReadToken) or not isinstance(batch, NativeObjectBatch):
                raise ValueError('missing exact native lifecycle proof')
            if not (token.source_sha256 and token.build_sha256 and token.config_sha256):
                raise ValueError('native lifecycle proof needs source, build and config pins')
            if batch.token != token:
                raise ValueError('batch and native publication differ')
            projected = tuple(islice(native_objects, self._max + 1))
            if len(projected) > self._max:
                raise ValueError('object projection exceeds the lineage budget')
            observed = {object_id(raw) for raw in projected}
            if len(observed) != len(projected):
                raise ValueError('duplicate native projection endpoints')

            if self._view is not None:
                previous = self._view.token
                if token == previous and batch == self._last_batch and observed == set(self._view.objects):
                    return self._view
                if (_graph_scope(token) != _graph_scope(previous) or batch.epoch != self._view.epoch
                        or token.graph_revision != previous.graph_revision + 1
                        or batch.timestamp_ns <= self._last_batch.timestamp_ns):
                    raise ValueError('native lifecycle scope, sequence or clock gap')
            elif token.graph_revision != 1:
                raise ValueError('native lifecycle requires the first accepted revision')

            return self._fold(token, batch, observed)
        except (TypeError, ValueError) as exc:
            self.failure = str(exc)
            self._view = None
            return None

    def _fold(self, token, batch, observed):
        allocated = self._allocated.copy()
        aliases = self._aliases.copy()
        backend_endpoints = self._backend_endpoints.copy()
        objects = {} if self._view is None else dict(self._view.objects)
        for event in batch.events:
            source, target = event.source, event.target
            if event.owner == 'frontend' and (source in backend_endpoints or target in backend_endpoints):
                # Crossing owner scopes can resurrect a previously hidden raw ID.
                raise ValueError('frontend mutation touches a backend merge component')
            if event.operation == 'create':
                if source in allocated or len(allocated) >= self._max:
                    raise ValueError('native raw object ID reused or budget exceeded')
                allocated.add(source)
                objects[source] = CanonicalObjectId(token.episode_id, token.run_id, batch.epoch, source)
                continue
            if source not in objects or (target is not None and target not in objects):
                raise ValueError('native event touches a missing canonical endpoint')
            del objects[source]
            if event.operation == 'merge':
                aliases[source] = target
                if event.owner == 'backend':
                    backend_endpoints.update((source, target))

        if set(objects) != observed:
            raise ValueError('native object snapshot is not accounted for by owner events')
        self._allocated, self._aliases, self._backend_endpoints = allocated, aliases, backend_endpoints
        self._last_batch = batch
        self._view = ObjectLineageView(token, batch.epoch, MappingProxyType(objects), MappingProxyType(aliases))
        return self._view
