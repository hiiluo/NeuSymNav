from types import SimpleNamespace

from neusymnav.regions.rebuild_room_worker import _validated_m5_result


def test_room_worker_record_consumption_does_not_reset_m3_update_mode():
    from neusymnav.regions.rebuild_room_worker import _PersistentMappingRecords
    records=_PersistentMappingRecords()
    mode='full_refresh' if not records else 'partial_update'
    records.append({'m3_mode':mode})
    assert records.pop()['m3_mode']=='full_refresh'
    assert len(records)==0 and bool(records)
    mode='full_refresh' if not records else 'partial_update'
    assert mode=='partial_update'


def _candidate(polygon):
    return SimpleNamespace(
        persistent_id=7,
        polygon=SimpleNamespace(outer=polygon),
        source_grid_revision=3,
        adjacent_region_ids=(),
        timestamp_s=0.6,
    )


def test_invalid_m5_polygon_is_a_stale_rejection_not_a_worker_failure():
    # Bow-tie ring has nonzero signed area but self-intersects.
    invalid = _candidate(((0., 0.), (2., 2.), (0., 2.), (2., 0.)))
    accepted, regions, reason = _validated_m5_result(
        SimpleNamespace(accepted=True, current_regions=(invalid,), reason=None)
    )
    assert not accepted
    assert regions is None
    assert reason.startswith("invalid_m5_geometry:")


def test_valid_m5_polygon_is_serialized_with_map_revision():
    valid = _candidate(((0., 0.), (2., 0.), (2., 2.), (0., 2.)))
    accepted, regions, reason = _validated_m5_result(
        SimpleNamespace(accepted=True, current_regions=(valid,), reason=None)
    )
    assert accepted and reason is None
    assert regions[0]["source_map_revision"] == 3
    assert regions[0]["polygon"] == [[0., 0.], [2., 0.], [2., 2.], [0., 2.]]


def test_native_m5_rejection_preserves_reason_without_serializing_regions():
    accepted, regions, reason = _validated_m5_result(
        SimpleNamespace(accepted=False, current_regions=(), reason="no valid support")
    )
    assert not accepted and regions is None
    assert reason == "no valid support"
