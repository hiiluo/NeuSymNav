import pytest

from neusymnav.contracts import dumps, loads
from neusymnav.contracts.hydra_evidence import (
    EvidencePage, HydraEvidenceIndex, HydraObjectKey, ObservationEvidence,
)
from neusymnav.contracts.observations import FrameKey


def ref(*, frame=1, detection='d1', prefix='a', link_status='geometric_candidate'):
    return ObservationEvidence(
        source=FrameKey('episode-1', 'rgbd-1', frame), capture_monotonic_ns=1_000_000_000 + frame,
        clock_domain='sim-clock-1', detection_id=detection,
        asset_key=f'obs/episode-1/rgbd-1/{frame}/{detection}',
        rgb_sha256='1' * 64, mask_sha256='2' * 64, depth_sha256='3' * 64,
        bbox_xyxy=(1, 2, 8, 9), calibration_id='cal-1', calibration_hash='4' * 64,
        pose_version=frame, detector_profile_id='detector-1', detector_hash='5' * 64,
        vocabulary_id='vocab-1', input_prefix_sha256=prefix * 64,
        link_method='mesh_depth_mask_v1', link_status=link_status,
    )


def key(revision=4, native_id='O(1)'):
    return HydraObjectKey('episode-1', 'run-1', native_id, revision)


def test_evidence_contracts_round_trip_with_exact_revision_and_source():
    value = ref()
    assert loads(dumps(value)) == value
    assert key().graph_revision == 4
    index = HydraEvidenceIndex(run_id='run-1', episode_id='episode-1')
    with pytest.raises(ValueError, match='episode'):
        index.add(key(), ObservationEvidence(**{**value.__dict__,
            'source': FrameKey('other', 'rgbd-1', 1)}))


def test_index_paginates_and_deduplicates_only_exact_object_revision():
    index = HydraEvidenceIndex(run_id='run-1', episode_id='episode-1')
    object_key = key()
    first, second, third = ref(frame=1), ref(frame=2), ref(frame=3)
    index.add(object_key, first)
    index.add(object_key, first)  # repeated frame/replay does not add another vote
    index.add(object_key, second)
    index.add(object_key, third)

    page1 = index.resolve(object_key, limit=2)
    assert isinstance(page1, EvidencePage)
    assert page1.status == 'available'
    assert page1.refs == (first, second)
    assert page1.next_cursor == 2
    page2 = index.resolve(object_key, limit=2, cursor=page1.next_cursor)
    assert page2.refs == (third,)
    assert page2.next_cursor is None
    assert index.resolve(key(revision=5), limit=2).status == 'no_evidence'


def test_index_fail_closes_wrong_run_episode_and_invalid_page_arguments():
    index = HydraEvidenceIndex(run_id='run-1', episode_id='episode-1')
    value = ref()
    index.add(key(), value)
    assert index.resolve(HydraObjectKey('episode-other', 'run-1', 'O(1)', 4)).status == 'unavailable'
    assert index.resolve(HydraObjectKey('episode-1', 'run-other', 'O(1)', 4)).status == 'unavailable'
    with pytest.raises(ValueError):
        index.resolve(key(), limit=0)
    with pytest.raises(ValueError):
        index.resolve(key(), limit=65)


def test_candidate_link_is_not_native_confirmation_and_stale_revision_does_not_carry():
    index = HydraEvidenceIndex(run_id='run-1', episode_id='episode-1')
    index.add(key(), ref(link_status='ambiguous'))
    page = index.resolve(key())
    assert page.refs[0].link_status == 'ambiguous'
    assert page.native_confirmed is False
    assert index.resolve(key(revision=5)).refs == ()


def test_quota_eviction_is_visible_and_path_escape_is_rejected():
    index = HydraEvidenceIndex(run_id='run-1', episode_id='episode-1', max_entries=1)
    index.add(key(), ref(frame=1, detection='d1'))
    index.add(key(revision=5), ref(frame=2, detection='d2'))
    assert index.resolve(key()).status == 'evicted'
    assert index.resolve(key(revision=5)).status == 'available'
    with pytest.raises(ValueError, match='relative'):
        ObservationEvidence(**{**ref().__dict__, 'asset_key': '../outside.png'})


def test_native_confirmed_status_requires_lineage_hash():
    with pytest.raises(ValueError, match='lineage'):
        ObservationEvidence(**{**ref().__dict__, 'link_status': 'native_confirmed'})
