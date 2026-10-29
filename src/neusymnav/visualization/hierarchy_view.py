"""Presentation-only hierarchy projection from one display envelope."""
from __future__ import annotations

from dataclasses import dataclass

from .publisher import DisplayEnvelope, DisplayVerificationRecord


@dataclass(frozen=True, slots=True)
class HierarchyRow:
    node_id: str
    kind: str
    label: str
    parent_id: str | None
    status: str
    lifecycle: str | None
    verification: str | None
    verification_reason: str | None
    stale: bool
    aliases: tuple[str, ...]


def hierarchy_rows(envelope: DisplayEnvelope) -> tuple[HierarchyRow, ...]:
    """Build rows without joining data from a different hierarchy revision."""
    snapshot = envelope.hierarchy
    parent: dict[str, str] = {}
    for edge in snapshot.edges:
        if edge.kind in {"contains", "in_region", "region_contains_place"} and edge.status == "assigned":
            # For in_region, the object is the source and the region is its
            # parent. The other two relations follow source -> child.
            child, parent_id = ((edge.source_id, edge.target_id) if edge.kind == "in_region"
                               else (edge.target_id, edge.source_id))
            if child not in parent:
                parent[child] = parent_id

    rows: list[HierarchyRow] = []
    for node_id, node in snapshot.nodes.items():
        attrs = node.attributes
        stale = node.kind == "region" and bool(attrs.get("stale", False))
        lifecycle = attrs.get("lifecycle") if node.kind == "object" else None
        membership = attrs.get("membership_status") if node.kind == "object" else None
        verification, verification_reason, _record = (
            resolve_verification(envelope, node_id) if node.kind == "object"
            else (None, None, None)
        )
        if node.kind == "object":
            status = str(membership or snapshot.statuses.get(node_id, "unknown"))
            aliases = tuple(sorted(str(value) for value in attrs.get("aliases", ())))
            label = str(attrs.get("category") or attrs.get("raw_label") or "object")
            label = f"{label} · {node_id[:8]} · {status}"
            if lifecycle is not None:
                label += f" · {lifecycle}"
            label += f" · verification {verification}"
        elif node.kind == "region":
            status = "stale" if stale else str(snapshot.statuses.get("regions", "assigned"))
            label = f"Region {node_id[-8:]} · geometry"
            if stale:
                label += " · STALE"
            aliases = ()
        elif node.kind == "floor":
            status, label, aliases = "assigned", f"Floor {attrs.get('floor_id', node_id)}", ()
        elif node.kind == "building":
            status, label, aliases = "assigned", f"Building {snapshot.episode_id}", ()
        else:
            status = str(snapshot.statuses.get(node_id, "assigned"))
            label, aliases = f"{node.kind.title()} {node_id[-8:]}", ()
        rows.append(HierarchyRow(node_id, node.kind, label, parent.get(node_id), status,
                                 None if lifecycle is None else str(lifecycle), verification,
                                 verification_reason, stale, aliases))
    return tuple(sorted(rows, key=lambda row: (row.kind, row.label, row.node_id)))


def resolve_object_selection(envelope: DisplayEnvelope, object_id: str) -> tuple[str, bool]:
    """Resolve a selected alias through the pinned object publication."""
    if not isinstance(object_id, str) or not object_id.strip():
        raise ValueError("object selection must be a nonempty ID")
    if envelope.sources.objects is not None:
        canonical = envelope.sources.objects.resolve_id(object_id)
        return canonical, canonical != object_id
    node = envelope.hierarchy.nodes.get(object_id)
    if node is not None and node.kind == "object":
        return object_id, False
    raise KeyError(object_id)


def resolve_verification(
    envelope: DisplayEnvelope, object_id: str,
) -> tuple[str, str | None, DisplayVerificationRecord | None]:
    """Return only verification evidence pinned to the selected canonical revision."""
    verification = envelope.sources.verification
    objects = envelope.sources.objects
    if verification is None:
        return "unavailable", "no verifier record", None
    if objects is None:
        return "unavailable", "pinned object snapshot unavailable", None
    if verification.object_revision != envelope.hierarchy.object_revision or verification.object_revision != objects.revision:
        return "unavailable", "verifier snapshot object revision mismatch", None
    try:
        canonical = objects.resolve_id(object_id)
    except KeyError:
        return "unavailable", "canonical object unavailable", None
    hierarchy_node = envelope.hierarchy.nodes.get(canonical)
    if hierarchy_node is None or hierarchy_node.kind != "object":
        return "unavailable", "object is absent from the pinned hierarchy", None
    state = objects.objects.get(canonical)
    record = verification.objects.get(canonical)
    if state is None or record is None:
        return "unavailable", "no verifier record for canonical object", None
    if record.episode_id != envelope.hierarchy.episode_id or record.object_revision != state.revision:
        return "unavailable", "verifier record object revision mismatch", None
    return record.status, None, record


__all__ = ["HierarchyRow", "hierarchy_rows", "resolve_object_selection", "resolve_verification"]
