from dataclasses import replace

from neusymnav.contracts.hydra_evidence import ObservationEvidence
from neusymnav.contracts.hydra_graph import HydraReadToken, NativeNodeRef
from neusymnav.contracts.observations import FrameKey
from neusymnav.contracts.reasoninggraph import DetectionGeometry, GraphReadToken, NativeObjectGeometry
from neusymnav.reasoninggraph.evidence import link_evidence


def inputs():
    source = FrameKey('ep', 'rgbd', 5)
    native = HydraReadToken('ep', 'run', 7, '3' * 64, 'epoch')
    token = GraphReadToken(native, source, 100, 'clock', 'calibration', '4' * 64,
                           '5' * 64, 'taxonomy', '6' * 64, 'detector@sha256:' + '7' * 64, 3)
    ref = ObservationEvidence(source, 100, 'clock', 'det5', 'objects/crop.npz', '1' * 64,
        '2' * 64, None, (0, 0, 1, 1), 'calibration', '4' * 64, 3, token.detector_profile_id, '7' * 64,
        'taxonomy', '3' * 64, 'rgbd_aabb_v1', 'geometric_candidate')
    evidence = DetectionGeometry(ref, 'chair', '5' * 64, ((0, 0, 0), (1, 1, 1)), '6' * 64)
    node = NativeObjectGeometry(NativeNodeRef(native, 'O(1)', 2), 'chair', ((0, 0, 0), (1, 1, 1)))
    return evidence, node, token


def test_geometric_link_requires_same_frame_and_leaves_confirmation_unavailable():
    evidence, node, token = inputs()
    link = link_evidence(evidence, [node], token)
    assert link.status == 'geometric_candidate'
    assert link.endpoint == node.ref
    assert link.canonical_id is None
    assert link.overlap == 1.0
    late = replace(evidence, evidence=replace(evidence.evidence, source=FrameKey('ep', 'rgbd', 4)))
    assert link_evidence(late, [node], token).status == 'unavailable'
    changed = replace(evidence, geometry_sha256='0' * 64)
    assert link_evidence(changed, [node], token).status == 'unavailable'
    other_vocabulary = replace(evidence, evidence=replace(evidence.evidence, vocabulary_id='other'))
    assert link_evidence(other_vocabulary, [node], token).status == 'unavailable'
    different_pose = replace(evidence, evidence=replace(evidence.evidence, pose_version=4))
    assert link_evidence(different_pose, [node], token).status == 'unavailable'
    wrong_model = replace(evidence, evidence=replace(evidence.evidence, detector_hash='9' * 64))
    assert link_evidence(wrong_model, [node], token).status == 'unavailable'
    other_labelspace = replace(evidence, labelspace_hash='8' * 64)
    assert link_evidence(other_labelspace, [node], token).status == 'unavailable'


def test_same_class_competing_support_is_ambiguous_across_a_single_revision():
    evidence, node, token = inputs()
    competitor = replace(node, ref=NativeNodeRef(token.native, 'O(2)', 2),
                         bounds=((.03, 0, 0), (1.03, 1, 1)))
    wrong_category = replace(competitor, category='table')
    assert link_evidence(evidence, [node, wrong_category], token).endpoint == node.ref
    result = link_evidence(evidence, [competitor, node], token)
    assert result.status == 'ambiguous'
    assert result.endpoint is None
    assert result.competing == (node.ref, competitor.ref)
    old = replace(node, ref=NativeNodeRef(replace(token.native, graph_revision=6), 'O(1)', 2))
    assert link_evidence(evidence, [old], token).status == 'no_support'


def test_hydra_runtime_exposes_one_exact_revision_without_enabling_a_sidecar():
    from types import SimpleNamespace

    from neusymnav.backends.hydra.runtime import HydraGraphRuntime

    _, node, token = inputs()
    native = token.native
    state = SimpleNamespace(stale=False, replay_required=False, failure_reason=None,
        graph_revision=native.graph_revision, input_prefix_sha256=native.input_prefix_sha256,
        source_sha256=None, build_sha256=None, config_sha256=None, last_source_key=token.source,
        last_capture_monotonic_ns=token.capture_monotonic_ns, last_clock_domain=token.clock_domain,
        last_detector_profile_id=token.detector_profile_id,
        last_transform={'calibration_id': token.calibration_id, 'calibration_hash': token.calibration_hash,
                        'source_geometry_hash': token.source_geometry_hash,
                        'coordinate_convention': token.coordinate_convention, 'pose_version': token.pose_version},
        last_semantics={'vocabulary_id': token.vocabulary_id, 'labelspace_hash': token.labelspace_hash,
                        'source_geometry_hash': token.source_geometry_hash},
        graph_summary={'graph_revision': 7, 'input_prefix_sha256': native.input_prefix_sha256,
            'nodes': [{'native_id': node.ref.native_id, 'layer_id': 2,
                       'semantic_label': 2, 'object_bounds': node.bounds}]})
    runtime = object.__new__(HydraGraphRuntime)
    runtime.session = SimpleNamespace(episode_id='ep', run_id='run', snapshot=lambda: state,
                                      has_detail_token=lambda current: current.graph_revision == state.graph_revision)
    runtime._category_by_label = {2: 'chair'}
    runtime.detector_profile_id = token.detector_profile_id

    observed_token, endpoints = runtime.reasoninggraph_snapshot()
    assert observed_token.native.graph_revision == 7
    assert observed_token.source == token.source
    assert endpoints[0].ref.token == observed_token.native
    assert endpoints[0].bounds == node.bounds
    state.last_detector_profile_id = 'unrecognized'
    assert runtime.reasoninggraph_snapshot() is None
    state.last_detector_profile_id = token.detector_profile_id
    state.stale = True
    assert runtime.reasoninggraph_snapshot() is None


def test_supported_link_cannot_claim_a_different_detector():
    import pytest

    evidence, node, token = inputs()
    link = link_evidence(evidence, [node], token)
    with pytest.raises(ValueError, match='accepted detector checkpoint'):
        replace(link, detector_hash='9' * 64)


def test_two_detections_cannot_independently_claim_the_same_native_endpoint():
    from neusymnav.reasoninggraph.evidence import link_frame

    first, endpoint, token = inputs()
    second = replace(first, evidence=replace(first.evidence, detection_id='det-other'))
    links = link_frame((first, second), (endpoint,), token)
    assert {link.status for link in links} == {'ambiguous'}
    assert all(link.endpoint is None for link in links)
    assert links[0].competing_detections == ('det-other',)
    assert links[1].competing_detections == ('det5',)
