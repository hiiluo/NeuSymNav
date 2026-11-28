from threading import Event

from neusymnav.objectnav.paper.native_tap import PaperNativeTap
from test_hydra_scene_graph_query import _query


def test_tap_publishes_before_close_and_does_not_wait_for_worker_on_offer():
    entered, release, published, closed = Event(), Event(), Event(), Event()
    query = _query()
    calls = []

    class Owner:
        def consume(self, *args):
            calls.append(args)
            if len(calls) == 1:
                entered.set()
                assert release.wait(3)
            return query

        def close(self):
            closed.set()
            return {'complete': True}

    class ObservedTap(PaperNativeTap):
        def publish(self, value):
            super().publish(value)
            if value is not None and len(calls) == 2:
                published.set()

    tap = ObservedTap(lambda: Owner())
    try:
        assert tap.offer(1, 2, 3) and entered.wait(1)
        assert tap.latest() is None
        assert tap.offer(4, 5, 6)
        assert not tap.offer(7, 8, 9)
        release.set()
        assert published.wait(1)
        assert tap.latest() is query
        assert calls == [(1, 2, 3), (4, 5, 6)]
    finally:
        release.set()
        outcome = tap.close(2)
    assert closed.is_set() and outcome['clean_shutdown']
    assert outcome['counts']['published'] == 2 and outcome['counts']['dropped'] == 1
    assert tap.latest() is None and not tap.offer(1, 2, 3)


def test_live_receipt_matcher_requires_two_prior_corroborated_anchors():
    from dataclasses import replace

    import numpy as np
    from types import MappingProxyType

    from neusymnav.contracts.observations import Detection, DetectionBatch
    from neusymnav.reasoninggraph.live_instance_confirmation import LiveInstanceConfirmation
    from neusymnav.reasoninggraph.native_lineage import CanonicalObjectId, ObjectLineageView
    from test_rg_semantic_beliefs import receipt
    from contract_helpers import observation

    base = observation()
    depth = np.ones((10, 10), dtype=np.float32)
    mask = np.ones(depth.shape, dtype=np.bool_)
    geometry = replace(base, rgb=np.zeros((*depth.shape, 3), dtype=np.uint8), depth_m=depth,
                       valid_depth=mask, K=np.eye(3))
    token = receipt().source_token
    token = replace(token, native=replace(token.native, episode_id=base.key.episode_id), source=base.key)
    object_id = CanonicalObjectId(token.native.episode_id, token.native.run_id, 1, 'O(0)')
    matcher = LiveInstanceConfirmation()
    for revision in range(1, 6):
        obs = replace(geometry, key=replace(geometry.key, frame_index=revision),
                      capture_monotonic_ns=100 + revision)
        batch = DetectionBatch.from_observation(obs, (Detection('0', 'chair', 'chair', .8, mask),),
                                                vocabulary_id=token.vocabulary_id)
        exact = replace(token, native=replace(token.native, graph_revision=revision, input_prefix_sha256=f'{revision:064x}'),
                        source=obs.key, capture_monotonic_ns=obs.capture_monotonic_ns,
                        source_geometry_hash=obs.geometry_hash)
        lineage = ObjectLineageView(exact.native, 1, MappingProxyType({'O(0)': object_id}), MappingProxyType({}))
        proofs = matcher.observe(exact, obs, batch, lineage, {'0': 'O(0)'})
        if revision < 5:
            assert not proofs
    (proof,) = proofs
    assert [a.token.native.graph_revision for a in proof.anchors] == [1, 2]


def test_native_mesh_claim_uses_depth_and_refuses_competing_endpoints():
    import numpy as np

    from contract_helpers import observation
    from neusymnav.contracts.observations import Detection
    from neusymnav.reasoninggraph.live_instance_confirmation import native_mesh_claims

    shape = 8, 8
    mask = np.ones(shape, dtype=np.bool_)
    depth = np.ones(shape, dtype=np.float32)
    obs = observation(rgb=np.zeros((*shape, 3), dtype=np.uint8), depth_m=depth,
                      valid_depth=mask, K=np.eye(3))
    v, u = np.indices(shape)
    points = np.column_stack((u.ravel(), v.ravel(), np.ones(depth.size)))
    detection = Detection('first', 'table', 'table', .9, mask)
    assert native_mesh_claims(obs, (detection,), {'O(1)': points}) == {'first': 'O(1)'}
    assert not native_mesh_claims(obs, (detection,), {'O(1)': points, 'O(2)': points})
    assert not native_mesh_claims(obs, (detection,), {'O(1)': points + (0, 0, .3)})


def test_mesh_paging_rejects_incomplete_candidate_set():
    from types import SimpleNamespace

    from neusymnav.contracts.hydra_graph import HydraReadResult
    from neusymnav.objectnav.paper.native_tap import PaperHydraOwner
    from test_rg_evidence import inputs

    _, _, token = inputs()
    session = SimpleNamespace(read=lambda request: HydraReadResult('available',
        SimpleNamespace(offset=0, total_rows=4097)))
    assert PaperHydraOwner._read_meshes(session, token.native, {'O(1)': None}) is None
