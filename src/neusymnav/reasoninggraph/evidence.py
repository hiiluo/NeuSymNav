"""Exact-source geometric evidence linking without assigning canonical IDs."""
from collections import defaultdict
from dataclasses import replace
from math import prod

from ..contracts.reasoninggraph import DetectionGeometry, GraphReadToken, NativeLink


def _iou(a, b):
    alo, ahi = a
    blo, bhi = b
    intersection = prod(max(0., min(ax, bx) - max(an, bn)) for an, ax, bn, bx in zip(alo, ahi, blo, bhi))
    union = prod(x - n for n, x in zip(alo, ahi)) + prod(x - n for n, x in zip(blo, bhi)) - intersection
    return intersection / union if union > 0 else 0.


def evidence_matches_token(evidence, token):
    """Check all per-instance source pins against an accepted revision."""
    ref = evidence.evidence
    return (ref.source, ref.capture_monotonic_ns, ref.clock_domain, ref.calibration_id,
            ref.calibration_hash, evidence.geometry_sha256, ref.vocabulary_id,
            ref.detector_profile_id, ref.detector_hash, ref.pose_version, evidence.labelspace_hash,
            ref.input_prefix_sha256) == (
            token.source, token.capture_monotonic_ns, token.clock_domain, token.calibration_id,
            token.calibration_hash, token.source_geometry_hash, token.vocabulary_id,
            token.detector_profile_id, token.detector_hash, token.pose_version, token.labelspace_hash,
            token.native.input_prefix_sha256)


def link_evidence(evidence, projection, token):
    """Score same-category AABBs using IoU >= 0.25 and a 0.10 lead for unique support."""
    if not isinstance(evidence, DetectionGeometry) or not isinstance(token, GraphReadToken):
        raise TypeError('expected DetectionGeometry and GraphReadToken')
    ref = evidence.evidence
    args = (token, ref.detector_hash, ref.detection_id)
    if not evidence_matches_token(evidence, token):
        return NativeLink(*args, 'unavailable')
    scores = {}
    for native in projection:
        if native.ref.token == token.native and native.category == evidence.category:
            overlap = _iou(evidence.bounds, native.bounds)
            if overlap >= .25:
                scores[native.ref] = max(overlap, scores.get(native.ref, 0.))
    ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0].native_id))
    if not ranked:
        return NativeLink(*args, 'no_support')
    endpoint, top = ranked[0]
    competing = tuple(other for other, score in ranked[:32] if top - score <= .10)
    if len(competing) > 1:
        return NativeLink(*args, 'ambiguous', overlap=top, competing=competing)
    return NativeLink(*args, 'geometric_candidate', endpoint=endpoint, overlap=top)


def link_frame(evidences, projection, token):
    """Require a unique detection claim before publishing a candidate endpoint."""
    if len(evidences) > 256:
        raise ValueError('excessive frame evidence')
    nodes = tuple(projection)
    claims = defaultdict(list)
    links = []
    ids = set()
    for evidence in evidences:
        link = link_evidence(evidence, nodes, token)
        if link.detection_id in ids:
            raise ValueError('duplicate detector instance in frame evidence')
        ids.add(link.detection_id)
        links.append(link)
        if link.endpoint is not None:
            claims[link.endpoint].append(link.detection_id)
    result = []
    for link in links:
        conflicts = tuple(sorted(item for item in claims.get(link.endpoint, ())
                                 if item != link.detection_id))[:32]
        if conflicts:
            link = replace(link, status='ambiguous', endpoint=None, competing_detections=conflicts)
        result.append(replace(link, policy_version='rgbd_aabb_frame_unique_v1'))
    return tuple(result)
