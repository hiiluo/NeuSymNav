"""Consumer-bound negative proof against the exact committed source/geometry."""
from __future__ import annotations
from ..contracts.observations import validate_detection_batch
from ..objects.negative_evidence import negative_visibility

SEMANTIC_TTL_NS = 750_000_000


def current_source(record, *, now_ns, clock_domain):
    capture = record['capture_monotonic_ns']
    return (record['clock_domain'] == clock_domain
        and 'replay' not in clock_domain.lower()
        and record['temporal_status'] == 'current'
        and type(now_ns) is int and 0 <= capture <= now_ns
        and now_ns - capture <= SEMANTIC_TTL_NS)


def validate_negative(record, batch_record, source, batch, snapshot):
    """Return a reason or None. Time is checked separately after this I/O/work."""
    if batch_record['completion'] != 'complete' or batch_record['cap_reached']:
        return 'incomplete_or_saturated'
    validate_detection_batch(source, batch)
    expected = dict(episode_id=source.key.episode_id, sensor_id=source.key.sensor_id,
                    frame_index=source.key.frame_index)
    for value in (record, batch_record):
        if (value['source'] != expected or value['geometry_hash'] != source.geometry_hash
            or value['clock_domain'] != source.clock_domain
            or value['capture_monotonic_ns'] != source.capture_monotonic_ns
            or value['calibration_id'] != source.calibration_id
            or value['pose_version'] != source.pose_version):
            return 'source_mismatch'
    if (record['source_asset'] != batch_record['source_asset']
        or record['batch_asset'] != batch_record['batch_asset']):
        return 'source_asset_mismatch'
    obj = snapshot.objects.get(record['object_id'])
    if obj is None or obj.revision != record['object_revision']:
        return 'stale_object_revision'
    # Re-run the P04 port of the source all-rays-clear proof; persisted history
    # is not by itself a present-time visibility certificate.
    proofs = negative_visibility(source, batch, snapshot, current=True)
    for proof in proofs:
        if (proof['object_id'] == record['object_id']
            and proof['object_revision'] == record['object_revision']
            and proof['projected_bbox_xyxy'] == record['projected_bbox_xyxy']
            and proof['camera_position'] == record['camera_position']):
            return None
    return 'not_measured_clear'
