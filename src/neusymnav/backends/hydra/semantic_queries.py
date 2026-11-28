"""Revision-safe semantic belief reads on the existing Hydra topology."""

from dataclasses import dataclass

from ...contracts.hydra_graph import HydraReadResult, HydraReadToken, NativeNodeRef
from ...contracts.semantic_beliefs import ObjectSemanticBelief


@dataclass(frozen=True)
class SemanticReadResult(HydraReadResult):
    token: HydraReadToken | None = None


@dataclass(frozen=True)
class BeliefObject:
    ref: NativeNodeRef
    belief: ObjectSemanticBelief | None
    probability: float | None = None


@dataclass(frozen=True)
class BeliefSubgraph:
    graph: object
    objects: tuple[BeliefObject, ...]


class SemanticQueries:
    def _semantic_result(self, result=None, *, value=None):
        result = result or self._read_status() or HydraReadResult('available', value)
        return SemanticReadResult(result.status, result.value, result.reason, self.read_token)

    def _semantic_view(self, expected_token):
        if not isinstance(expected_token, HydraReadToken):
            raise TypeError('expected a Hydra read token')
        if expected_token != self.read_token:
            return None, HydraReadResult('stale', reason='graph_token_mismatch')
        status = self._read_status()
        if status is not None:
            return None, status
        if self._belief_reader is None:
            return None, HydraReadResult('unavailable', reason='semantic_memory_disabled')
        view = self._belief_reader(expected_token)
        if view is None or view.token.native != expected_token or view.taxonomy != self._taxonomy:
            return None, HydraReadResult('unavailable', reason='belief_revision_unavailable')
        return view, None

    def _semantic_ref(self, ref):
        if not isinstance(ref, NativeNodeRef):
            raise TypeError('expected a native node reference')
        if ref.token != self.read_token:
            return HydraReadResult('stale', reason='graph_token_mismatch')
        if ref.layer_id != 2:
            return HydraReadResult('unavailable', reason='object_layer_required')
        return None

    def _semantic_page(self, items, scope, limit, cursor):
        return self._semantic_result(self._page(items, scope, limit, cursor))

    def object_belief(self, ref, *, expected_token, top_k=5):
        view, status = self._semantic_view(expected_token)
        status = status or self._semantic_ref(ref)
        if status is not None:
            return self._semantic_result(status)
        belief = view.belief(ref.native_id, top_k=top_k)
        if belief is None or belief.object_key.native_id not in self._nodes_by_native:
            return self._semantic_result(HydraReadResult('missing', reason='object_not_found'))
        if belief.status != 'available':
            return self._semantic_result(HydraReadResult('unavailable', reason=belief.reason))
        return self._semantic_result(value=belief)

    def category_probability(self, ref, category, *, expected_token):
        if category not in self._taxonomy.categories:
            raise ValueError('category is outside the belief vocabulary')
        result = self.object_belief(ref, expected_token=expected_token)
        return self._semantic_result(value=result.value.probability(category)) if result.status == 'available' else result

    def objects_by_probability(self, category, *, expected_token, limit=64, cursor=None):
        if category not in self._taxonomy.categories:
            raise ValueError('category is outside the belief vocabulary')
        view, status = self._semantic_view(expected_token)
        if status is not None:
            return self._semantic_result(status)
        items = []
        for ref in self._index()[0].get(2, ()):
            belief = view.belief(ref.native_id)
            if belief is not None and (probability := belief.probability(category)) is not None and probability > 0:
                items.append(BeliefObject(ref, belief, probability))
        items.sort(key=lambda item: (-item.probability, item.ref.native_id))
        return self._semantic_page(items, ('belief_probability', category), limit, cursor)

    def uncertain_objects(self, *, expected_token, limit=64, cursor=None):
        view, status = self._semantic_view(expected_token)
        if status is not None:
            return self._semantic_result(status)
        items = []
        for ref in self._index()[0].get(2, ()):
            belief = view.belief(ref.native_id)
            if belief is not None and belief.observation_count:
                items.append(BeliefObject(ref, belief))
        items.sort(key=lambda item: (-item.belief.entropy_nats, item.ref.native_id))
        return self._semantic_page(items, ('belief_uncertainty',), limit, cursor)

    def probabilistic_room_context(self, room, *, expected_token, limit=64, cursor=None):
        view, status = self._semantic_view(expected_token)
        status = status or self._check_ref(room, 4)
        if status is not None:
            return self._semantic_result(status)
        node = self._nodes_by_native[room.native_id]
        refs = self._index()[1].get((node.node_id, 2), ())
        items = tuple(BeliefObject(ref, view.belief(ref.native_id)) for ref in refs)
        return self._semantic_page(items, ('belief_room', room), limit, cursor)

    def probabilistic_subgraph(self, seeds, *, expected_token, max_nodes=64, max_edges=128):
        view, status = self._semantic_view(expected_token)
        if status is not None:
            return self._semantic_result(status)
        graph = self.subgraph(seeds, max_nodes=max_nodes, max_edges=max_edges)
        if graph.status != 'available':
            return self._semantic_result(graph)
        objects = tuple(BeliefObject(ref, view.belief(ref.native_id))
                        for ref in graph.value.nodes if ref.layer_id == 2)
        return self._semantic_result(value=BeliefSubgraph(graph.value, objects))

    def belief_evidence(self, ref, *, expected_token, limit=64, cursor=None):
        view, status = self._semantic_view(expected_token)
        status = status or self._semantic_ref(ref)
        if status is not None:
            return self._semantic_result(status)
        belief = view.belief(ref.native_id)
        if belief is None or belief.object_key.native_id not in self._nodes_by_native:
            return self._semantic_result(HydraReadResult('missing', reason='object_not_found'))
        return self._semantic_page(view.evidence(ref.native_id), ('belief_evidence', ref.native_id), limit, cursor)
