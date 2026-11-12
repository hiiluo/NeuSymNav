"""Display-only room-label text for the live scene-graph views (no Qt here).

The debug records remain bound to their source revisions. The live VLM overlay
can keep the last classification while the same room awaits a new result.
"""
from __future__ import annotations

from .debug_types import RoomLabelDebugRecord, record_is_current


def _text(result, backend) -> str:
    if result.status == 'available':
        text = f'{backend} {result.label}'
        if result.alternatives:
            text += ' (or ' + '/'.join(result.alternatives) + ')'
        return text
    if result.status in {'unknown', 'insufficient_evidence'}:
        return f'{backend} unknown'
    return f'{backend} {result.status}'


def current_room_labels(records, graph, *, backend=None, retained=None) -> dict[str, str]:
    """Map current room node IDs to short label text for display."""
    if graph is None or graph.status != 'available' or graph.stale or graph.replay_required:
        return {}
    room_ids = {node.node_id for node in graph.nodes if node.layer_id == 4}
    labels: dict[str, str] = {}
    running: dict[str, str] = {}
    for record in records or ():
        if not isinstance(record, RoomLabelDebugRecord):
            continue
        room_id = record.job.request.key.room_id
        if room_id not in room_ids or not record_is_current(record, graph):
            continue
        prefix = 'VLM' if (backend or record.backend_metrics.get('label_backend')) == 'vlm' else 'SLM'
        if record.state == 'complete' and record.result is not None:
            labels.setdefault(room_id, _text(record.result, prefix))
        elif record.state == 'error':
            labels.setdefault(room_id, f'{prefix} unavailable')
        elif record.state == 'running':
            running.setdefault(room_id, f'{prefix} …')
    for room_id, label in running.items():
        labels.setdefault(room_id, label)
    if backend == 'vlm':
        for room_id, result in (retained or {}).items():
            if room_id in room_ids:
                labels[room_id] = _text(result, 'VLM')
        for room_id in room_ids:
            labels.setdefault(room_id, 'VLM pending')
    return labels
