from dataclasses import replace

import pytest

from neusymnav.contracts.observations import FrameKey
from neusymnav.reasoninggraph.evidence import link_evidence
from neusymnav.reasoninggraph.lifecycle import apply_delta
from neusymnav.reasoninggraph.store import RevisionStore
from test_rg_evidence import inputs


def test_revision_store_publishes_exact_view_and_revokes_reused_id():
    evidence, node, token = inputs()
    store = RevisionStore(lambda _native: True, max_links=1, max_bytes=4096)
    link = link_evidence(evidence, [node], token)
    assert store.publish(token, (link, link))
    assert store.read(token).links == (link,)
    assert store.publish(token, (link,))
    assert store.read(replace(token, clock_domain='other')) is None
    changed = replace(token, native=replace(token.native, graph_revision=8,
                     input_prefix_sha256='8' * 64), source=FrameKey('ep', 'rgbd', 6), capture_monotonic_ns=101)
    assert not store.publish(changed, (link,))
    assert store.read(token) is not None
    assert store.publish(changed, ())
    assert store.read(token) is None
    assert not store.publish(token, (link,))


def test_revision_gap_and_raw_id_reappearance_carry_no_lifecycle_proof():
    _, _, token = inputs()
    later = replace(token, native=replace(token.native, graph_revision=9,
                    input_prefix_sha256='8' * 64), source=FrameKey('ep', 'rgbd', 8), capture_monotonic_ns=103)
    delta = apply_delta(token, later)
    assert delta.status == 'revision_only'
    assert delta.aliases == ()
    assert delta.requires_rebase
    with pytest.raises(ValueError, match='native lifecycle proof'):
        apply_delta(token, later, {'aliases': {'O(0)': 'O(1)'}})


def test_store_fails_closed_on_conflict_and_quota():
    evidence, node, token = inputs()
    store = RevisionStore(lambda _native: True, max_links=1, max_bytes=4096)
    link = link_evidence(evidence, [node], token)
    other = replace(link, detection_id='two')
    assert not store.publish(token, (link, other))
    assert store.read(token) is None
    assert store.publish(token, (link,))
    assert not store.publish(token, (replace(link, overlap=.5),))
    assert store.read(token).links == (link,)
    assert not RevisionStore(lambda _native: True, max_links=1, max_bytes=20).publish(token, (link,))


def test_store_rejects_late_publication_and_revokes_when_native_advances():
    evidence, node, original = inputs()
    current = [original.native]
    store = RevisionStore(lambda native: native == current[0])
    assert store.publish(original, ())
    later = replace(original, sidecar_revision=1)
    link = link_evidence(evidence, [node], later)
    assert store.publish(later, (link,))
    assert not store.publish(original, ())
    assert not store.publish(replace(later, sidecar_revision=2, clock_domain='other'), ())
    assert store.read(later).links == (link,)
    current[0] = replace(original.native, graph_revision=8, input_prefix_sha256='a' * 64)
    assert store.read(later) is None
    assert not store.publish(later, (link,))


def test_lifecycle_rejects_rollback_and_cross_epoch_delta():
    _, _, token = inputs()
    with pytest.raises(ValueError, match='older'):
        apply_delta(token, replace(token, native=replace(token.native, graph_revision=6)))
    with pytest.raises(ValueError, match='scope'):
        apply_delta(token, replace(token, native=replace(token.native, world_epoch='new')))
    with pytest.raises(ValueError, match='source identity'):
        apply_delta(token, replace(token, source=FrameKey('ep', 'rgbd', 6)))
    with pytest.raises(ValueError, match='older sidecar'):
        apply_delta(replace(token, sidecar_revision=2), token)


def test_sealed_view_restores_only_at_exact_revision_and_checksum(tmp_path):
    evidence, node, token = inputs()
    current = [token.native]
    store = RevisionStore(lambda native: native == current[0])
    link = link_evidence(evidence, [node], token)
    assert store.publish(token, (link,))
    manifest = tmp_path / 'sidecar.json'
    checksum = store.seal(manifest, token)
    assert store.seal(manifest, token) == checksum
    recovered = RevisionStore(lambda native: native == current[0])
    wrong = replace(token, calibration_hash='9' * 64)
    assert not recovered.restore(manifest, wrong, checksum)
    assert recovered.restore(manifest, token, checksum)
    assert recovered.read(token).links == (link,)
    current[0] = replace(token.native, graph_revision=8)
    assert not recovered.restore(manifest, token, checksum)
    current[0] = token.native
    manifest.write_bytes(manifest.read_bytes() + b' ')
    assert not recovered.restore(manifest, token, checksum)
