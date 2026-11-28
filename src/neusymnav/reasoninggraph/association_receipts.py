"""Exact-source receipts for owner-resolved RGB-D instance associations."""

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
import json

from ..contracts._base import digest, finite, text
from ..contracts.hydra_evidence import ObservationEvidence
from ..contracts.hydra_lineage import object_id
from ..contracts.reasoninggraph import DetectionGeometry, GraphReadToken
from .evidence import evidence_matches_token
from .lifecycle import validate_progress
from .native_lineage import CanonicalObjectId, ObjectLineageView


METHOD = 'rgbd_corroborated_native_v1'


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def lineage_digest(lineage):
    return _digest({"token": asdict(lineage.token), "epoch": lineage.epoch,
                    "objects": sorted(lineage.objects), "aliases": dict(lineage.aliases)})


@dataclass(frozen=True)
class InstanceAnchor:
    """One prior accepted source with a corroborated edge to the current detection."""

    token: GraphReadToken
    detection_id: str
    raw_endpoint: str
    epoch: int
    intermediate_revisions: tuple[int, ...]
    support_sha256: str

    def __post_init__(self):
        if not isinstance(self.token, GraphReadToken):
            raise TypeError('instance anchor needs an accepted graph token')
        text(self.detection_id, 'detection_id')
        object_id(self.raw_endpoint)
        digest(self.support_sha256, 'support_sha256')
        if (type(self.epoch) is not int or self.epoch < 1 or not isinstance(self.intermediate_revisions, tuple)
                or not 2 <= len(self.intermediate_revisions) <= 24
                or any(type(revision) is not int for revision in self.intermediate_revisions)):
            raise ValueError('invalid corroborating anchor')


@dataclass(frozen=True)
class InstanceConfirmation:
    """A trusted instance matcher may submit one unique proof per exact source detection."""

    token: GraphReadToken
    detection_id: str
    current_endpoint: str
    anchors: tuple[InstanceAnchor, InstanceAnchor]

    def __post_init__(self):
        if not isinstance(self.token, GraphReadToken):
            raise TypeError('instance confirmation needs an accepted graph token')
        text(self.detection_id, 'detection_id')
        object_id(self.current_endpoint)
        if (not isinstance(self.anchors, tuple) or len(self.anchors) != 2
                or any(not isinstance(anchor, InstanceAnchor) for anchor in self.anchors)):
            raise ValueError('confirmation requires two prior anchors')


@dataclass(frozen=True)
class CategoryVoteReceipt:
    source_token: GraphReadToken
    canonical_object: CanonicalObjectId
    category: str
    raw_label: str
    raw_score: float
    evidence: ObservationEvidence
    support_sha256: str

    @property
    def vote_key(self):
        return self.source_token.native.run_id, self.evidence.source, self.evidence.detection_id


def confirm_evidence(token, geometry, proof, lineage, *, raw_label, score):
    """Issue a deterministic receipt only from exact source and two valid owner anchors."""
    if (not isinstance(token, GraphReadToken) or not isinstance(geometry, DetectionGeometry)
            or not isinstance(proof, InstanceConfirmation) or not isinstance(lineage, ObjectLineageView)
            or token != proof.token or token.native != lineage.token
            or not evidence_matches_token(geometry, token)
            or geometry.evidence.detection_id != proof.detection_id or geometry.evidence.depth_sha256 is None):
        return None
    endpoint = lineage.objects.get(proof.current_endpoint)
    if endpoint is None:
        return None
    anchors = sorted(proof.anchors, key=lambda anchor: anchor.token.native.graph_revision)
    if (anchors[0].token.native.graph_revision == anchors[1].token.native.graph_revision
            or anchors[0].token.source == anchors[1].token.source):
        return None
    for anchor in anchors:
        try:
            validate_progress(anchor.token, token)
        except ValueError:
            return None
        earlier, later = anchor.token.native.graph_revision, token.native.graph_revision
        if (anchor.epoch != lineage.epoch or not 0 < later - earlier <= 24
                or len({rev for rev in anchor.intermediate_revisions if earlier < rev < later}) < 2
                or any(not earlier < rev < later for rev in anchor.intermediate_revisions)):
            return None
        historical = CanonicalObjectId(endpoint.episode_id, endpoint.run_id, lineage.epoch, anchor.raw_endpoint)
        if lineage.resolve(historical) != endpoint:
            return None

    ref = replace(geometry.evidence, link_method=METHOD, link_status='native_confirmed',
                  native_lineage_sha256=lineage_digest(lineage))
    raw_score = finite(score, 'raw_score', minimum=0)
    if raw_score > 1:
        raise ValueError('raw_score must be in [0, 1]')
    return CategoryVoteReceipt(token, endpoint, geometry.category, text(raw_label, 'raw_label'), raw_score, ref,
                               _digest([asdict(anchor) for anchor in anchors]))
