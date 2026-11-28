from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from neusymnav.objectnav.paper.semantic_candidates import (
    CandidateObservation, SemanticCandidateConfig, retrieve_candidates,
)
from test_rg_semantic_beliefs import receipt


def source(vote, cid):
    t, ref = vote.source_token, vote.evidence
    return CandidateObservation(cid, t.source, ref.detection_id, t.capture_monotonic_ns,
        t.source_geometry_hash, t.vocabulary_id, t.calibration_id, t.pose_version,
        ref.mask_sha256, vote.raw_label, vote.raw_score)


def query_for(vote, *, status='available'):
    t = vote.source_token.native
    ref = SimpleNamespace(native_id=vote.canonical_object.native_id, token=t, layer_id=2)
    object_hit = SimpleNamespace(ref=ref, probability=.75, belief=SimpleNamespace(observation_count=3))
    roster = SimpleNamespace(status=status, token=t,
                             value=SimpleNamespace(items=(object_hit,), next_cursor=None))
    return SimpleNamespace(read_token=t, status=status, projection=SimpleNamespace(
        last_source={"episode_id": t.episode_id, "frame_index": vote.evidence.source.frame_index}),
        objects_by_probability=lambda *_a, **_kw: SimpleNamespace(
            status=status, token=t, value=SimpleNamespace(items=(object_hit,))),
        uncertain_objects=lambda **_kw: roster,
        belief_evidence=lambda *_a, **_kw: SimpleNamespace(
            status='available', token=t, value=SimpleNamespace(items=(vote,), next_cursor=None)))


def test_join_rejects_a_second_native_owner_outside_the_ranked_category():
    vote = receipt()
    q = query_for(vote)
    hit, = q.objects_by_probability().value.items
    other_ref = SimpleNamespace(native_id='O(99)', token=q.read_token, layer_id=2)
    other = replace(vote, canonical_object=replace(vote.canonical_object, native_id='O(99)'))
    q.uncertain_objects().value.items += (SimpleNamespace(ref=other_ref),)
    q.belief_evidence = lambda ref, **_: SimpleNamespace(status='available', token=q.read_token,
        value=SimpleNamespace(items=(vote if ref == hit.ref else other,), next_cursor=None))
    observed = source(vote, 12)
    assert not retrieve_candidates(q, (observed,), 'chair', SemanticCandidateConfig(mode='shadow'),
        q.read_token, eligible_cids={12}, current_frame=observed.source.frame_index)


def test_join_uses_shared_exact_receipt_and_still_eligible_paper_candidates():
    v = receipt()
    q = query_for(v)
    observed = source(v, 12)
    cfg = SemanticCandidateConfig(mode='probabilistic')
    args = (q, (observed,), 'chair', cfg, q.read_token)
    assert retrieve_candidates(*args, eligible_cids={12}, current_frame=observed.source.frame_index) == (12,)
    assert not retrieve_candidates(*args, eligible_cids=set(), current_frame=observed.source.frame_index)
    assert not retrieve_candidates(*args, eligible_cids={12}, current_frame=observed.source.frame_index - 1)
    assert not retrieve_candidates(q, (replace(observed, mask_sha256='f'*64),), 'chair', cfg,
                                   q.read_token, eligible_cids={12}, current_frame=99)


def test_stale_or_ambiguous_join_does_not_change_candidate_order():
    v = receipt()
    q = query_for(v)
    one = source(v, 12)
    cfg = SemanticCandidateConfig(mode='shadow')
    assert not retrieve_candidates(q, (one, replace(one, cid=13)), 'chair', cfg,
                                   q.read_token, eligible_cids={12, 13}, current_frame=99)
    assert not retrieve_candidates(query_for(v, status='stale'), (one,), 'chair', cfg,
                                   q.read_token, eligible_cids={12}, current_frame=99)
    assert not retrieve_candidates(SimpleNamespace(read_token=q.read_token), (one,), 'chair', cfg,
                                   q.read_token, eligible_cids={12}, current_frame=99)
    q.projection.last_source['frame_index'] = 100
    assert not retrieve_candidates(q, (one,), 'chair', cfg, q.read_token,
                                   eligible_cids={12}, current_frame=99)


def test_shadow_records_rank_without_applying_and_rejects_old_publication():
    from neusymnav.objectnav.paper.b0 import PaperB0Policy

    vote = receipt()
    q = query_for(vote)
    current = vote.evidence.source.frame_index
    baseline, alternative = SimpleNamespace(cid=4), SimpleNamespace(cid=12)
    policy = SimpleNamespace(_semantic_config=SemanticCandidateConfig(mode='shadow'),
        _semantic_tap=SimpleNamespace(latest=lambda: q),
        _semantic_observations=(source(vote, alternative.cid),),
        _semantic_frame=current, _semantic_decisions=[], step=8, target='chair',
        categories=SimpleNamespace(labels={'chair': ['chair']}))
    assert PaperB0Policy._semantic_choice(policy, (baseline, alternative), baseline) is baseline
    assert policy._semantic_decisions[-1]['semantic'] == alternative.cid
    assert policy._semantic_decisions[-1]['publication'] == {
        'revision': q.read_token.graph_revision,
        'input_prefix_sha256': q.read_token.input_prefix_sha256,
        'source_frame': current,
        'policy_frame': current,
    }
    policy._semantic_frame += policy._semantic_config.max_source_age_frames + 1
    assert PaperB0Policy._semantic_choice(policy, (baseline, alternative), baseline) is baseline
    assert policy._semantic_decisions[-1]['status'] == 'unavailable'
    assert policy._semantic_decisions[-1]['publication']['policy_frame'] == policy._semantic_frame
    policy._semantic_tap = None
    assert PaperB0Policy._semantic_choice(policy, (baseline, alternative), baseline) is baseline
    assert policy._semantic_decisions[-1]['publication'] is None


def test_guarded_policy_reranks_only_verified_candidates_using_fresh_receipt():
    from neusymnav.objectnav.b0.policy import B0Policy

    vote = receipt()
    q = query_for(vote)
    now = vote.source_token.capture_monotonic_ns
    q.projection.last_source['capture_monotonic_ns'] = now
    near = SimpleNamespace(cid=4, centroid_xy=(1., 0.), points=np.array([[1., 0., 0.]]))
    supported = SimpleNamespace(cid=12, centroid_xy=(2., 0.), points=np.array([[2., 0., 0.]]))
    pool = [near, supported]
    events = []
    policy = SimpleNamespace(
        target='chair', categories=SimpleNamespace(labels={'chair': ['chair']}),
        memory=SimpleNamespace(confirmed_for=lambda _: pool),
        _semantic_config=SemanticCandidateConfig(mode='probabilistic'),
        _semantic_tap=SimpleNamespace(latest=lambda: q),
        _semantic_observations=(source(vote, supported.cid),),
        _semantic_frame=vote.evidence.source.frame_index, _semantic_decisions=[],
        cfg=SimpleNamespace(stop_distance_m=.4, aim_margin_m=.1),
        _to=lambda state, ctx, note: events.append((state, note)),
    )
    ctx = SimpleNamespace(robot_xy=(0., 0.), now_ns=now, cycle=5, nav=None,
                          navigator=SimpleNamespace(can_reach_approach=lambda *_: True))
    assert B0Policy._pick(policy, ctx)
    assert policy._target_cid == supported.cid
    assert events[-1] == ('APPROACH', 'confirmed')
    assert policy._semantic_decisions[-1]['applied'] == supported.cid
    policy._semantic_config = replace(policy._semantic_config, mode='shadow')
    assert B0Policy._pick(policy, ctx) and policy._target_cid == near.cid
    policy._semantic_config = replace(policy._semantic_config, mode='probabilistic')
    ctx.navigator.can_reach_approach = lambda *_: False
    assert B0Policy._pick(policy, ctx) and policy._target_cid == near.cid
    ctx.navigator.can_reach_approach = lambda *_: True
    policy._semantic_frame -= 1
    assert B0Policy._pick(policy, ctx) and policy._target_cid == near.cid
    policy._semantic_frame += 1
    ctx.now_ns += 2_000_000_001
    assert B0Policy._pick(policy, ctx) and policy._target_cid == near.cid
    ctx.now_ns = now
    pool.pop()
    assert B0Policy._pick(policy, ctx) and policy._target_cid == near.cid
