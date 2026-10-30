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
    # Only source-supported membership relations survive the display projection.
    # Conflicting parents fail closed rather than depending on edge iteration order.
    candidates: dict[str, set[str]] = {}
    for edge in snapshot.edges:
        if edge.status != "assigned":
            continue
        source = snapshot.nodes.get(edge.source_id)
        target = snapshot.nodes.get(edge.target_id)
        if source is None or target is None:
            continue
        if edge.kind == "contains" and source.kind == "floor" and target.kind == "region":
            child, owner = target.node_id, source.node_id
        elif (edge.kind == "in_region" and source.kind == "object" and target.kind == "region"
              and not target.attributes.get("stale", False)
              and source.attributes.get("membership_status", snapshot.statuses.get(source.node_id)) == "assigned"):
            child, owner = source.node_id, target.node_id
        else:
            continue
        candidates.setdefault(child, set()).add(owner)
    parent = {child: next(iter(owners)) for child, owners in candidates.items() if len(owners) == 1}

    rows: list[HierarchyRow] = []
    for node_id, node in snapshot.nodes.items():
        if node.kind not in {"floor", "region", "object"}:
            continue
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
            if status == "assigned" and node_id not in parent:
                status = "unassigned"
            aliases = tuple(sorted(str(value) for value in attrs.get("aliases", ())))
            label = str(attrs.get("category") or attrs.get("raw_label") or "object")
            label = f"{label} · {node_id[:8]} · {status}"
            if lifecycle is not None:
                label += f" · {lifecycle}"
            label += f" · verification {verification}"
        elif node.kind == "region":
            status = "stale" if stale else str(snapshot.statuses.get("regions", "assigned"))
            label = f"Room {node_id[-8:]} · geometry"
            if stale:
                label += " · STALE"
            aliases = ()
        elif node.kind == "floor":
            status, label, aliases = "assigned", f"Floor {attrs.get('floor_id', node_id)}", ()
        rows.append(HierarchyRow(node_id, "room" if node.kind == "region" else node.kind, label,
                                 None if node.kind == "floor" else parent.get(node_id), status,
                                 None if lifecycle is None else str(lifecycle), verification,
                                 verification_reason, stale, aliases))
    return tuple(sorted(rows, key=lambda row: ({"floor": 0, "room": 1, "object": 2}[row.kind], row.label, row.node_id)))


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


def hierarchy_links(envelope: DisplayEnvelope, visible_ids=None) -> tuple[tuple[str, str, str], ...]:
    """Membership first, then current structural room topology; never infer links.

    Adjacency is not a robot-clearance or current traversability certificate.
    All views use the same source-supported, deduplicated display projection.
    """
    rows = {r.node_id: r for r in hierarchy_rows(envelope)}
    visible = set(rows) if visible_ids is None else set(visible_ids) & rows.keys()
    links = [(row.parent_id, key, 'contains') for key, row in rows.items()
             if key in visible and row.parent_id in visible]
    pairs = set()
    snapshot = envelope.hierarchy
    for edge in snapshot.edges:
        if edge.kind != 'region_adjacent_to' or edge.status != 'assigned' or edge.provenance.get('stale', False):
            continue
        a, b = edge.source_id, edge.target_id
        if a not in visible or b not in visible or rows[a].kind != 'room' or rows[b].kind != 'room':
            continue
        ra, rb = rows[a], rows[b]
        if ra.stale or rb.stale or ra.status != 'assigned' or rb.status != 'assigned':
            continue
        aa, ab = snapshot.nodes[a].attributes, snapshot.nodes[b].attributes
        if (ra.parent_id is None or ra.parent_id != rb.parent_id
                or aa.get('floor_id') != ab.get('floor_id')):
            continue
        pairs.add(tuple(sorted((a, b))))
    links.extend((a, b, 'region_adjacent_to') for a, b in sorted(pairs))
    return tuple(links[:1200])


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


__all__ = ["HierarchyRow", "hierarchy_rows", "hierarchy_links", "resolve_object_selection", "resolve_verification"]
