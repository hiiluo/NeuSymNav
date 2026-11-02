"""Presentation-only hierarchy projection from one display envelope."""
from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import numpy as np

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


@dataclass(frozen=True, slots=True)
class RoomDebugItem:
    """Private, display-only projection of optional room stability diagnostics."""
    item_id: str
    kind: str
    status: str
    reason: str
    detail: str
    region_ids: tuple[str, ...] = ()
    geometry: object | None = None
    geometries: tuple[object, ...] = ()
    stale: bool = False


def room_debug_items(envelope: DisplayEnvelope) -> tuple[RoomDebugItem, ...]:
    """Normalize the optional JSON-safe floor ``room_debug`` payload.

    The projection tolerates absent/new fields so older publications remain
    readable. Raw DuDe regions remain the source of polygons; the payload only
    annotates stable identities, evidence and candidate portals.
    """
    floor = next((node for node in envelope.hierarchy.nodes.values() if node.kind == "floor"), None)
    if floor is None:
        return ()
    debug = floor.attributes.get("room_debug", {})
    if not isinstance(debug, Mapping) or not debug:
        return ()
    if debug.get("episode_id", envelope.hierarchy.episode_id) != envelope.hierarchy.episode_id:
        return ()
    source_revision = debug.get("source_map_revision")
    if source_revision is not None and source_revision != envelope.hierarchy.map_revision:
        return ()
    publication_stale = bool(debug.get("stale", False))
    nav = envelope.sources.nav
    bounds = None
    if nav is not None and nav.revision == envelope.hierarchy.map_revision:
        bounds = (nav.origin_xy[0] - nav.resolution_m * 1.5,
                  nav.origin_xy[1] - nav.resolution_m * 1.5,
                  nav.origin_xy[0] + nav.states.shape[1] * nav.resolution_m + nav.resolution_m * 1.5,
                  nav.origin_xy[1] + nav.states.shape[0] * nav.resolution_m + nav.resolution_m * 1.5)

    def safe_geometry(value, minimum_points):
        try:
            points = np.asarray(value, dtype=float)
        except (TypeError, ValueError):
            return None
        if points.ndim != 2 or points.shape[1] != 2 or len(points) < minimum_points or not np.isfinite(points).all():
            return None
        if bounds is not None and (np.any(points[:, 0] < bounds[0]) or np.any(points[:, 0] > bounds[2])
                                   or np.any(points[:, 1] < bounds[1]) or np.any(points[:, 1] > bounds[3])):
            return None
        return points
    regions: dict[str, object] = {
        str(node.attributes.get("stable_room_id")): node.attributes
        for node in envelope.hierarchy.nodes.values()
        if node.kind == "region" and node.attributes.get("stable_room_id") is not None
    }
    rooms = debug.get("rooms", debug.get("stable_rooms", ()))
    if isinstance(rooms, Mapping):
        rooms = [dict(value, stable_room_id=key) if isinstance(value, Mapping) else {"stable_room_id": key}
                 for key, value in rooms.items()]
    result: list[RoomDebugItem] = []
    if isinstance(rooms, (tuple, list)):
        for index, raw in enumerate(rooms):
            if not isinstance(raw, Mapping):
                continue
            stable_id = str(raw.get("stable_room_id", raw.get("room_id", raw.get("id", f"room-{index}"))))
            annotations = regions.get(stable_id, {})
            region_ids = raw.get("source_region_ids", raw.get("region_ids", raw.get("source_regions", ())))
            if isinstance(region_ids, str): region_ids = (region_ids,)
            if not region_ids:
                region_ids = tuple(str(n.node_id) for n in envelope.hierarchy.nodes.values()
                                   if n.kind == "region" and n.attributes.get("stable_room_id") == stable_id)
            status = str(raw.get("status", annotations.get("stable_room_status", annotations.get("status", "unknown"))))
            stale = publication_stale or bool(annotations.get("stable_room_stale", False))
            reason = str(raw.get("reason", annotations.get("stable_room_reason", annotations.get("reason", "unavailable"))))
            support = raw.get("support_count", raw.get("support", raw.get("observations",
                                   annotations.get("stable_room_support_count", "unknown"))))
            lineage = raw.get("lineage", raw.get("predecessor_ids", raw.get("predecessors", annotations.get("predecessors", ()))))
            if isinstance(lineage, str): lineage = (lineage,)
            detail = (f"Stable ID: {stable_id}\nStatus: {status}\nPublication: {'stale' if stale else 'current'}\nReason: {reason}\n"
                      f"Support: {support}\nSource DuDe regions: {', '.join(map(str, region_ids)) or 'unavailable'}\n"
                      f"Lineage: {', '.join(map(str, lineage)) or 'none reported'}")
            polygons = raw.get("polygons")
            if isinstance(polygons, (tuple, list)) and polygons:
                geometries = tuple(valid for poly in polygons if (valid := safe_geometry(poly, 3)) is not None)
            else:
                geometry = raw.get("polygon", raw.get("geometry"))
                valid = None if geometry is None else safe_geometry(geometry, 3)
                geometries = () if valid is None else (valid,)
            result.append(RoomDebugItem(stable_id, "room", status, reason, detail,
                                        tuple(map(str, region_ids)), geometries[0] if geometries else None, geometries, stale))
    portals = debug.get("candidate_portals", debug.get("portals", ()))
    if isinstance(portals, Mapping):
        portals = [dict(value, portal_id=key) if isinstance(value, Mapping) else {"portal_id": key}
                   for key, value in portals.items()]
    if isinstance(portals, (tuple, list)):
        for index, raw in enumerate(portals):
            if not isinstance(raw, Mapping):
                continue
            portal_id = str(raw.get("portal_id", raw.get("id", f"portal-{index}")))
            source_status = str(raw.get("status", "candidate"))
            status = "tentative"
            stale = publication_stale
            reason = str(raw.get("reason", "geometry candidate; not a detected door or traversability certificate"))
            regions_for_portal = raw.get("region_ids", raw.get("source_region_ids", ()))
            if isinstance(regions_for_portal, str): regions_for_portal = (regions_for_portal,)
            detail = (f"Candidate portal: {portal_id}\nStatus: {status}\nSource status: {source_status}\n"
                      f"Publication: {'stale' if stale else 'current'}\nReason: {reason}\n"
                      f"Adjacent regions: {', '.join(map(str, regions_for_portal)) or 'unavailable'}\n"
                      "Geometry candidate only; no door detection or passage clearance is claimed.")
            raw_geometry = raw.get("endpoints", raw.get("segment", raw.get("line_xy", raw.get("polygon", raw.get("geometry", raw.get("xy"))))))
            geometry = None if raw_geometry is None else safe_geometry(raw_geometry, 2)
            result.append(RoomDebugItem(portal_id, "portal", status, reason, detail,
                                        tuple(map(str, regions_for_portal)), geometry,
                                        () if geometry is None else (geometry,), stale))
    return tuple(result)


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
        elif edge.kind == "contains_source_region" and source.kind == "floor" and target.kind == "source_region":
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
        if node.kind not in {"floor", "region", "source_region", "object"}:
            continue
        attrs = node.attributes
        stale = node.kind in {"region", "source_region"} and bool(attrs.get("stale", False))
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
            source_membership=str(attrs.get('rebuild_region_membership_status','unavailable'))
            source_region=attrs.get('rebuild_region_membership_id')
            source_candidates=tuple(attrs.get('rebuild_region_membership_candidates',()))
            if source_membership=='assigned' and source_region:
                label+=f" · Rebuild M5 {source_region.rsplit(':',1)[-1]}"
            elif source_membership=='ambiguous':
                label+=f" · Rebuild M5 ambiguous ({len(source_candidates)})"
            elif attrs.get('rebuild_region_map_domain_id') is not None:
                label+=f" · Rebuild M5 {source_membership}"
        elif node.kind == "region":
            status = "stale" if stale else str(snapshot.statuses.get("regions", "assigned"))
            label = f"Room {node_id[-8:]} · geometry"
            if stale:
                label += " · STALE"
            aliases = ()
        elif node.kind == "floor":
            status, label, aliases = "assigned", f"Floor {attrs.get('floor_id', node_id)}", ()
        elif node.kind == "source_region":
            status='stale' if stale else str(snapshot.statuses.get('rebuild_regions','assigned'))
            label=f"Rebuild M5 region {attrs.get('raw_region_id',node_id)}"
            if stale:label+=' · STALE'
            aliases=()
        rows.append(HierarchyRow(node_id, "room" if node.kind == "region" else node.kind, label,
                                 None if node.kind == "floor" else parent.get(node_id), status,
                                 None if lifecycle is None else str(lifecycle), verification,
                                 verification_reason, stale, aliases))
    return tuple(sorted(rows, key=lambda row: ({"floor": 0, "room": 1, "source_region": 2, "object": 3}[row.kind], row.label, row.node_id)))


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
    source_pairs = set()
    source_memberships = set()
    snapshot = envelope.hierarchy
    for edge in snapshot.edges:
        if edge.status=='assigned' and edge.kind=='in_source_region':
            source=snapshot.nodes.get(edge.source_id);target=snapshot.nodes.get(edge.target_id)
            if (source is not None and target is not None and source.kind=='object'
                    and target.kind=='source_region' and not target.attributes.get('stale',True)
                    and source.attributes.get('rebuild_region_membership_status')=='assigned'
                    and source.attributes.get('rebuild_region_map_domain_id')==target.attributes.get('map_domain_id')
                    and source.attributes.get('rebuild_region_map_revision')==target.attributes.get('source_map_revision')
                    and edge.source_id in visible and edge.target_id in visible):
                source_memberships.add((edge.source_id,edge.target_id))
        if edge.kind not in {'region_adjacent_to','source_region_adjacent_to'} or edge.status != 'assigned' or edge.provenance.get('stale', False):
            continue
        a, b = edge.source_id, edge.target_id
        if a not in visible or b not in visible:
            continue
        ra, rb = rows[a], rows[b]
        if ra.stale or rb.stale or ra.status != 'assigned' or rb.status != 'assigned':
            continue
        aa, ab = snapshot.nodes[a].attributes, snapshot.nodes[b].attributes
        if edge.kind=='source_region_adjacent_to':
            if (ra.kind!='source_region' or rb.kind!='source_region'
                    or aa.get('map_domain_id')!=ab.get('map_domain_id')):continue
            source_pairs.add(tuple(sorted((a,b))))
            continue
        if ra.kind!='room' or rb.kind!='room':continue
        if (ra.parent_id is None or ra.parent_id != rb.parent_id
                or aa.get('floor_id') != ab.get('floor_id')):
            continue
        pairs.add(tuple(sorted((a, b))))
    links.extend((a, b, 'region_adjacent_to') for a, b in sorted(pairs))
    links.extend((a,b,'source_region_adjacent_to') for a,b in sorted(source_pairs))
    links.extend((a,b,'in_source_region') for a,b in sorted(source_memberships))
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
