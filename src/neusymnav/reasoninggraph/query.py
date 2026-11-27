"""Bounded, revision-local semantic retrieval without relation inference."""
from dataclasses import dataclass
from itertools import islice

from ..contracts.hydra_graph import NativeNodeRef
from ..contracts.reasoninggraph import GraphReadToken
from .object_features import ObjectFeatureView, rank_objects
from .room_features import RoomFeatureView, rank_rooms
from .relation_store import RelationStore


@dataclass(frozen=True)
class Ranking:
    items: tuple
    total: int
    pending: int = 0


@dataclass(frozen=True)
class Subgraph:
    nodes: tuple
    edges: tuple
    truncated: bool


class RevisionQuery:
    """Read only fixture-scoped data; caller supplies native freshness authority."""

    def __init__(self, token, object_view, room_view, relation_store, native_is_current):
        if (not isinstance(token, GraphReadToken) or not isinstance(object_view, ObjectFeatureView)
                or not isinstance(room_view, RoomFeatureView) or not isinstance(relation_store, RelationStore)
                or not callable(native_is_current)):
            raise ValueError('invalid query inputs')
        if object_view.token != token or room_view.token != token or relation_store.token != token:
            raise ValueError('query token mismatch')
        if len(object_view.objects) > 8192 or len(room_view.rooms) > 4096:
            raise ValueError('query view exceeds budget')
        for entries, layer in ((object_view.objects, 2), (room_view.rooms, 4)):
            refs = [entry.ref for entry in entries]
            if len(set(refs)) != len(refs) or any(not isinstance(r, NativeNodeRef) or r.token != token.native or r.layer_id != layer for r in refs):
                raise ValueError('view references mismatch')
        if any(value > cap for value, cap in zip(relation_store.limits, (256, 1024, 32 * 1024 * 1024, 64))):
            raise ValueError('relation store exceeds query budget')
        self.token, self.object_view, self.room_view = token, object_view, room_view
        self._relations, self._current = relation_store, native_is_current

    def require_current(self, token):
        if token != self.token or not self._current(self.token.native):
            raise ValueError('stale query token')

    def objects(self, token, vector, spec, *, top_k=10, room_scope=None):
        self.require_current(token)
        if room_scope is not None:
            room_scope = tuple(islice(room_scope, 8193))
            if len(room_scope) > 8192 or any(not isinstance(r, NativeNodeRef) or r.token != token.native or r.layer_id != 2 for r in room_scope):
                raise ValueError('invalid object scope')
            room_scope = frozenset(room_scope)
        items = rank_objects(self.object_view, vector, spec, top_k, room_scope)
        total = sum(room_scope is None or item.ref in room_scope for item in self.object_view.objects)
        self.require_current(token)
        return Ranking(items, total)

    def rooms(self, token, vector, spec, *, top_k=10, scoring='mean'):
        self.require_current(token)
        items = rank_rooms(self.room_view, vector, spec, scoring=scoring, top_k=top_k)
        self.require_current(token)
        return Ranking(items, len(self.room_view.rooms), self.room_view.pending)

    def _support(self, token):
        self.require_current(token)
        support = self._relations.support(token)
        if support is None:
            raise ValueError('stale relation store')
        self.require_current(token)
        return support

    def relations(self, token, subject, object_ref):
        for ref in (subject, object_ref):
            if not isinstance(ref, NativeNodeRef) or ref.token != self.token.native or ref.layer_id != 2:
                raise ValueError('invalid relation endpoint')
        return tuple(p for p in self._support(token) if p.subject == subject and p.object == object_ref)

    def retrieve_subgraph(self, token, seeds, *, max_nodes, max_edges):
        if (type(max_nodes) is not int or not 1 <= max_nodes <= 128
                or type(max_edges) is not int or not 0 <= max_edges <= 256):
            raise ValueError('invalid subgraph budget')
        self.require_current(token)
        seeds = tuple(islice(seeds, max_nodes + 1))
        if (not seeds or len(seeds) > max_nodes or any(not isinstance(r, NativeNodeRef) for r in seeds)
                or len(set(seeds)) != len(seeds)):
            raise ValueError('invalid seeds')
        known = self._relations.endpoints | {x.ref for x in self.object_view.objects} | {
            x.ref for x in self.room_view.rooms}
        if any(r not in known for r in seeds):
            raise ValueError('unknown or mismatched seed')
        pools = sorted(self._support(token), key=lambda p: (p.subject.native_id, p.object.native_id, repr(p.spec), p.marker_scheme))
        nodes = list(sorted(seeds, key=lambda r: (r.layer_id, r.native_id)))
        selected = set(nodes)
        edges = []
        truncated = False
        # Expand from seeds through relation edges until no more reachable nodes.
        remaining = list(pools)
        while remaining:
            progress = False
            for edge in remaining[:]:
                if edge.subject not in selected and edge.object not in selected:
                    continue
                missing = [r for r in (edge.subject, edge.object) if r not in selected]
                if len(nodes) + len(missing) > max_nodes or len(edges) == max_edges:
                    truncated = True
                    remaining.remove(edge)
                    continue
                nodes.extend(missing)
                selected.update(missing)
                edges.append(edge)
                remaining.remove(edge)
                progress = True
            if not progress:
                break
        self.require_current(token)
        return Subgraph(tuple(nodes), tuple(edges), truncated)
