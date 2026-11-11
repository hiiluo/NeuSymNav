"""View-only Hydra graph visibility shared by the 2D and 3D widgets."""
from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from ..backends.hydra.graph_adapter import (
    HydraDisplayEdge,
    HydraDisplayNode,
    HydraGraphProjection,
)


DISPLAY_NODE_BUDGET = 300
PLACE_NODE_BUDGET = 200
LAYER_NAMES = MappingProxyType({2: 'object', 3: 'place', 4: 'room', 5: 'building'})
_PRESETS = MappingProxyType({
    'rooms_objects': frozenset({2, 4}),
    'topology': frozenset({3, 4, 5}),
    'all_debug': frozenset({2, 3, 4, 5}),
})
_LAYER_PRIORITY = MappingProxyType({2: 0, 4: 1, 5: 2, 3: 3})


@dataclass(frozen=True, slots=True)
class GraphVisibility:
    """Immutable display choices; changing them never mutates graph state."""

    preset: str
    visible_layers: frozenset[int]
    place_budget: int = PLACE_NODE_BUDGET
    show_place_labels: bool = False
    show_derived_membership: bool = False
    show_point_cloud: bool = True

    def __post_init__(self):
        if self.preset not in {*_PRESETS, 'custom'}:
            raise ValueError('unknown Hydra visibility preset')
        layers = frozenset(self.visible_layers)
        if any(type(layer) is not int or layer not in range(8) for layer in layers):
            raise ValueError('visible_layers must contain known integer layer IDs')
        if type(self.place_budget) is not int or not 0 <= self.place_budget <= PLACE_NODE_BUDGET:
            raise ValueError(f'place_budget must be between 0 and {PLACE_NODE_BUDGET}')
        for name in ('show_place_labels', 'show_derived_membership', 'show_point_cloud'):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f'{name} must be bool')
        object.__setattr__(self, 'visible_layers', layers)

    @classmethod
    def for_preset(cls, name: str) -> 'GraphVisibility':
        if name not in _PRESETS:
            raise ValueError(f'unknown Hydra visibility preset: {name}')
        return cls(name, _PRESETS[name])

    def with_layer(self, layer_id: int, visible: bool) -> 'GraphVisibility':
        if type(layer_id) is not int or layer_id not in range(8):
            raise ValueError('layer_id must be a known integer')
        if type(visible) is not bool:
            raise ValueError('visible must be bool')
        layers = set(self.visible_layers)
        if visible:
            layers.add(layer_id)
        else:
            layers.discard(layer_id)
        return replace(self, preset='custom', visible_layers=frozenset(layers))

    def with_point_cloud(self, visible: bool) -> 'GraphVisibility':
        if type(visible) is not bool:
            raise ValueError('visible must be bool')
        return replace(self, show_point_cloud=visible)


@dataclass(frozen=True, slots=True)
class VisibleGraphCounts:
    raw_by_layer: Mapping[int, int]
    shown_by_layer: Mapping[int, int]
    filtered_count: int
    budget_hidden_count: int
    shown_count: int


@dataclass(frozen=True, slots=True)
class VisibleGraph:
    nodes: tuple[HydraDisplayNode, ...]
    edges: tuple[HydraDisplayEdge, ...]
    counts: VisibleGraphCounts
    selected_id: str | None


def select_visible_nodes(
    graph: HydraGraphProjection,
    policy: GraphVisibility,
    selected_id: str | None = None,
) -> VisibleGraph:
    """Return a bounded projection with object/room priority over places.

    Native edges are included only when both endpoints survive display policy.
    When places are hidden, an optional derived object-to-room edge may be
    emitted from a complete parent chain; it is explicitly not a native edge.
    """
    if not isinstance(graph, HydraGraphProjection):
        raise TypeError('graph must be HydraGraphProjection')
    if not isinstance(policy, GraphVisibility):
        raise TypeError('policy must be GraphVisibility')

    raw_by_layer = {layer: int(graph.node_counts.get(str(layer), 0)) for layer in range(8)}
    eligible = [node for node in graph.nodes if node.layer_id in policy.visible_layers]
    eligible_places = [node for node in eligible if node.layer_id == 3]
    selected_place = next((node for node in eligible_places if node.node_id == selected_id), None)
    place_order = sorted(eligible_places, key=lambda node: node.node_id)
    if selected_place is not None:
        place_order = [selected_place] + [node for node in place_order if node.node_id != selected_id]
    visible_places = place_order[:policy.place_budget]

    non_places = [node for node in eligible if node.layer_id != 3]
    ordered = sorted(non_places, key=lambda node: (
        node.node_id != selected_id,
        _LAYER_PRIORITY.get(node.layer_id, 4),
        node.node_id,
    ))
    ordered.extend(visible_places)
    ordered.sort(key=lambda node: (
        node.node_id != selected_id,
        _LAYER_PRIORITY.get(node.layer_id, 4),
        node.node_id,
    ))
    selected = next((node for node in ordered if node.node_id == selected_id), None)
    if selected is not None:
        ordered = [selected] + [node for node in ordered if node.node_id != selected_id]
    visible_nodes = tuple(ordered[:DISPLAY_NODE_BUDGET])
    visible_ids = {node.node_id for node in visible_nodes}

    visible_edges = [edge for edge in graph.edges
                     if edge.source in visible_ids and edge.target in visible_ids]
    if policy.show_derived_membership:
        visible_edges.extend(_derived_membership_edges(graph, visible_nodes, visible_ids))

    shown_by_layer = {layer: sum(node.layer_id == layer for node in visible_nodes)
                      for layer in range(8)}
    filtered_count = max(0, len(graph.nodes) - len(visible_nodes))
    eligible_hidden = max(0, len(eligible) - len(visible_nodes))
    counts = VisibleGraphCounts(
        raw_by_layer=MappingProxyType(raw_by_layer),
        shown_by_layer=MappingProxyType(shown_by_layer),
        filtered_count=filtered_count,
        budget_hidden_count=eligible_hidden,
        shown_count=len(visible_nodes),
    )
    return VisibleGraph(visible_nodes, tuple(visible_edges), counts,
                        selected_id if selected_id in visible_ids else None)


def _derived_membership_edges(
    graph: HydraGraphProjection,
    visible_nodes: tuple[HydraDisplayNode, ...],
    visible_ids: set[str],
) -> list[HydraDisplayEdge]:
    by_id = {node.node_id: node for node in graph.nodes}
    edges: list[HydraDisplayEdge] = []
    for node in visible_nodes:
        if node.layer_id != 2:
            continue
        current = by_id.get(node.parent_id) if node.parent_id is not None else None
        seen = {node.node_id}
        skipped_hidden_parent = False
        while current is not None and current.node_id not in seen:
            seen.add(current.node_id)
            if current.node_id in visible_ids:
                if skipped_hidden_parent and current.layer_id == 4:
                    edges.append(HydraDisplayEdge(node.node_id, current.node_id,
                                                  'derived_room_membership'))
                break
            skipped_hidden_parent = True
            current = by_id.get(current.parent_id) if current.parent_id is not None else None
    return edges
