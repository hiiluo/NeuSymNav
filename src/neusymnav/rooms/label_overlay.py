"""Display-only room-label text for the live scene-graph views (no Qt here).

Only labels whose request is bound to the exact current graph revision and
snapshot are shown; an older answer never appears on a newer room. Semantic
reuse in the service is what keeps labels current while Hydra keeps
publishing revisions with unchanged room contents.
"""
from __future__ import annotations

from .debug_types import RoomLabelDebugRecord, record_is_current


def _text(result) -> str:
    if result.status == 'available':
        text = f'SLM {result.label}'
        if result.alternatives:
            text += ' (or ' + '/'.join(result.alternatives) + ')'
        return text
    if result.status in {'unknown', 'insufficient_evidence'}:
        return 'SLM unknown'
    return f'SLM {result.status}'


def current_room_labels(records, graph) -> dict[str, str]:
    """Map current room node IDs to short label text for display."""
    if graph is None:
        return {}
    room_ids = {node.node_id for node in graph.nodes if node.layer_id == 4}
    labels: dict[str, str] = {}
    running: set[str] = set()
    for record in records or ():
        if not isinstance(record, RoomLabelDebugRecord):
            continue
        room_id = record.job.request.key.room_id
        if room_id not in room_ids or not record_is_current(record, graph):
            continue
        if record.state == 'complete' and record.result is not None:
            labels.setdefault(room_id, _text(record.result))
        elif record.state == 'running':
            running.add(room_id)
    for room_id in running - set(labels):
        labels[room_id] = 'SLM …'
    return labels
