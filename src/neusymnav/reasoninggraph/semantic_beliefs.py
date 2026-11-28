"""A unique accepted observation contributes one categorical vote."""

from collections import Counter, defaultdict

from ..contracts._base import digest, finite, integer
from ..contracts.hydra_evidence import ObservationEvidence
from ..contracts.hydra_lineage import object_id
from ..contracts.observations import Taxonomy
from ..contracts.reasoninggraph import GraphReadToken
from ..contracts.semantic_beliefs import ObjectSemanticBelief, VoteKey
from .association_receipts import CategoryVoteReceipt, METHOD
from .native_lineage import CanonicalObjectId


def validate_vote(taxonomy, receipt):
    if not isinstance(receipt, CategoryVoteReceipt):
        raise TypeError('expected CategoryVoteReceipt')
    token, ref, owner = receipt.source_token, receipt.evidence, receipt.canonical_object
    if (not isinstance(token, GraphReadToken) or not isinstance(ref, ObservationEvidence)
            or not isinstance(owner, CanonicalObjectId)):
        raise ValueError('vote needs a typed source, evidence and owner')
    object_id(owner.native_id)
    integer(owner.epoch, 'owner epoch', minimum=1)
    if (receipt.category not in taxonomy.categories or taxonomy.canonicalize(receipt.raw_label) != receipt.category
            or token.vocabulary_id != taxonomy.vocabulary_id or finite(receipt.raw_score, 'raw_score', 0) > 1):
        raise ValueError('vote disagrees with the pinned taxonomy or detector score')
    if ((owner.episode_id, owner.run_id) != (token.native.episode_id, token.native.run_id)
            or ref.link_status != 'native_confirmed' or ref.link_method != METHOD or ref.depth_sha256 is None
            or (ref.source, ref.capture_monotonic_ns, ref.clock_domain, ref.calibration_id, ref.calibration_hash,
                ref.pose_version, ref.detector_profile_id, ref.detector_hash, ref.vocabulary_id, ref.input_prefix_sha256) != (
                token.source, token.capture_monotonic_ns, token.clock_domain, token.calibration_id, token.calibration_hash,
                token.pose_version, token.detector_profile_id, token.detector_hash, token.vocabulary_id,
                token.native.input_prefix_sha256)):
        raise ValueError('vote source or owner does not match its confirmed evidence')
    digest(receipt.support_sha256, 'instance support')
    return VoteKey(token.native.run_id, ref.source, ref.detection_id)


def summarize_votes(taxonomy, object_key, receipts, *, top_k=5, reason='no_confirmed_evidence'):
    if not 1 <= integer(top_k, 'top_k', minimum=1) <= 64:
        raise ValueError('top_k must be in [1, 64]')
    counts = tuple(sorted(Counter(r.category for r in receipts).items()))
    times = [r.evidence.capture_monotonic_ns for r in receipts]
    return ObjectSemanticBelief(object_key, taxonomy.vocabulary_id, taxonomy.categories, counts, top_k,
                                min(times, default=None), max(times, default=None),
                                max((r.source_token.native.graph_revision for r in receipts), default=None),
                                'available' if counts else 'unavailable', None if counts else reason)


class SemanticVoteAccumulator:
    def __init__(self, taxonomy):
        if not isinstance(taxonomy, Taxonomy):
            raise TypeError('expected Taxonomy')
        self.taxonomy = taxonomy
        self._votes = {}
        self._by_object = defaultdict(list)
        self._pins = {}

    def apply(self, receipt):
        key = validate_vote(self.taxonomy, receipt)
        if key in self._votes:
            if self._votes[key] != receipt:
                raise ValueError('conflicting payload for a confirmed observation')
            return False
        token = receipt.source_token
        owner = receipt.canonical_object
        pins = (token.clock_domain, token.detector_profile_id, token.labelspace_hash,
                token.calibration_hash, token.native.world_epoch, token.native.source_sha256,
                token.native.build_sha256, token.native.config_sha256)
        if self._pins.get(owner, pins) != pins:
            raise ValueError('object voting scope changed')
        self._pins[owner] = pins
        self._votes[key] = receipt
        self._by_object[owner].append(receipt)
        return True

    def belief(self, object_key, *, top_k=5):
        return summarize_votes(self.taxonomy, object_key, self._by_object.get(object_key, ()), top_k=top_k)
