from dataclasses import replace
from types import MappingProxyType

import pytest

from neusymnav.reasoninggraph.association_receipts import InstanceAnchor, InstanceConfirmation, confirm_evidence
from neusymnav.reasoninggraph.native_lineage import CanonicalObjectId, ObjectLineageView
from test_rg_evidence import inputs


def fixture():
    geometry, _, token = inputs()
    geometry = replace(geometry, evidence=replace(geometry.evidence, depth_sha256="d" * 64))
    raw = 'O(2)'
    retired = 'O(1)'
    identity = CanonicalObjectId(token.native.episode_id, token.native.run_id, 1, raw)
    lineage = ObjectLineageView(token.native, 1, MappingProxyType({raw: identity}),
                                MappingProxyType({retired: raw}))
    anchors = tuple(InstanceAnchor(
        replace(token, native=replace(token.native, graph_revision=revision,
                                      input_prefix_sha256=f"{revision:064x}"),
                source=replace(token.source, frame_index=revision),
                capture_monotonic_ns=token.capture_monotonic_ns - 8 + revision),
        f"witness-{revision}", retired, 1, (revision + 1, revision + 2), "c" * 64,
    ) for revision in (1, 2))
    proof = InstanceConfirmation(token, geometry.evidence.detection_id, raw, anchors)
    return geometry, token, lineage, proof


def test_receipt_resolves_two_accepted_anchors_into_one_current_canonical_id():
    geometry, token, lineage, proof = fixture()
    receipt = confirm_evidence(token, geometry, proof, lineage, raw_label='chair', score=.8)
    assert receipt is not None
    assert receipt.canonical_object == lineage.objects['O(2)']
    assert receipt.evidence.link_status == 'native_confirmed'
    assert receipt.source_token == token
    assert receipt.raw_label == receipt.category == 'chair'
    assert receipt == confirm_evidence(token, geometry, proof, lineage, raw_label='chair', score=.8)


@pytest.mark.parametrize("change", ["pose_version", "detector_profile_id", "vocabulary_id", "native",
                                    "detection_id", "epoch", "ambiguous", "duplicate", "no_lineage"])
def test_receipt_fails_closed_on_mismatch_or_ambiguity(change):
    geometry, token, lineage, proof = fixture()
    if change == "pose_version":
        proof = replace(proof, token=replace(token, pose_version=token.pose_version + 1))
    elif change == "detector_profile_id":
        proof = replace(proof, token=replace(token, detector_profile_id='other@sha256:' + 'a' * 64))
    elif change == "vocabulary_id":
        proof = replace(proof, token=replace(token, vocabulary_id='other'))
    elif change == "native":
        lineage = replace(lineage, token=replace(token.native, input_prefix_sha256='f' * 64))
    elif change == "detection_id":
        proof = replace(proof, detection_id='other')
    elif change == "epoch":
        proof = replace(proof, anchors=(replace(proof.anchors[0], epoch=3), proof.anchors[1]))
    elif change == "ambiguous":
        proof = replace(proof, anchors=(replace(proof.anchors[0], raw_endpoint='O(8)'), proof.anchors[1]))
    elif change == "duplicate":
        proof = replace(proof, anchors=(proof.anchors[0], proof.anchors[0]))
    elif change == "no_lineage":
        lineage = None
    assert confirm_evidence(token, geometry, proof, lineage, raw_label='chair', score=.8) is None
