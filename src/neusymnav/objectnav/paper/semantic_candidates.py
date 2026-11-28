"""Causal joins between exact receipt observations and existing Paper candidates."""

from collections import defaultdict
from dataclasses import dataclass, replace
from math import isfinite

from ...contracts.hydra_graph import HydraReadToken
from ...contracts.observations import FrameKey
from ...reasoninggraph.association_receipts import CategoryVoteReceipt
from ...reasoninggraph.lifecycle import _graph_scope


@dataclass(frozen=True)
class SemanticCandidateConfig:
    mode: str = 'off'
    min_probability: float = .5
    min_observations: int = 2
    max_hits: int = 16
    max_source_age_frames: int = 16
    fallback: str = 'deterministic'

    def __post_init__(self):
        if (self.mode not in ('off', 'shadow', 'probabilistic')
                or self.fallback not in ('deterministic', 'abstain')
                or type(self.min_probability) not in (int, float)
                or not isfinite(self.min_probability) or not 0 < self.min_probability <= 1
                or type(self.min_observations) is not int or not 1 <= self.min_observations <= 16384
                or type(self.max_hits) is not int or not 1 <= self.max_hits <= 64):
            raise ValueError('invalid Paper semantic candidate settings')
        if type(self.max_source_age_frames) is not int or not 1 <= self.max_source_age_frames <= 64:
            raise ValueError('invalid Paper semantic publication age')


@dataclass(frozen=True)
class CandidateObservation:
    cid: int
    source: FrameKey
    detection_id: str
    capture_ns: int
    geometry_hash: str
    vocabulary_id: str
    calibration_id: str
    pose_version: int
    mask_sha256: str
    raw_label: str
    raw_score: float

    @classmethod
    def from_receipt(cls, cid, receipt):
        token, ref = receipt.source_token, receipt.evidence
        return cls(cid, token.source, ref.detection_id, token.capture_monotonic_ns,
                   token.source_geometry_hash, token.vocabulary_id, token.calibration_id,
                   token.pose_version, ref.mask_sha256, receipt.raw_label, receipt.raw_score)


class PaperSemanticTap:
    """One immutable query publication, written by the graph sidecar."""

    def __init__(self):
        self._query = None

    def publish(self, query):
        if query is not None:
            from ...backends.hydra.query import HydraSceneGraphQuery
            if not isinstance(query, HydraSceneGraphQuery):
                raise TypeError('Paper tap requires a native query publication')
        self._query = query

    def latest(self):
        return self._query


def retrieve_candidates(query, joins, category, policy_config, expected_token, *, eligible_cids, current_frame,
                        current_ns=None, cid_aliases=None):
    """Rank only CIDs already cleared by Paper's existing candidate verifier."""
    if (policy_config.mode == 'off' or query is None or not isinstance(expected_token, HydraReadToken)
            or getattr(query, 'read_token', None) != expected_token or not eligible_cids):
        return ()
    by_source = defaultdict(set)
    for item in joins:
        if item.source.episode_id == expected_token.episode_id and item.source.frame_index <= current_frame:
            if cid_aliases and item.cid in cid_aliases:
                item = replace(item, cid=cid_aliases[item.cid])
            by_source[item.source, item.detection_id].add(item)
    try:
        source = query.projection.last_source
        if (source.get('episode_id') != expected_token.episode_id or type(source.get('frame_index')) is not int
                or not 0 <= current_frame - source['frame_index'] <= policy_config.max_source_age_frames):
            return ()
        if current_ns is not None:
            capture_ns = source.get('capture_monotonic_ns')
            if type(capture_ns) is not int or not 0 <= current_ns - capture_ns <= 2_000_000_000:
                return ()
        ranked = query.objects_by_probability(category, expected_token=expected_token, limit=policy_config.max_hits)
        if ranked.status != 'available' or ranked.token != expected_token:
            return ()
        order = [hit.ref.native_id for hit in ranked.value.items
                 if hit.probability >= policy_config.min_probability
                 and hit.belief.observation_count >= policy_config.min_observations]
        if not order:
            return ()
        owners = query.uncertain_objects(expected_token=expected_token, limit=64)
        if owners.status != 'available' or owners.token != expected_token or owners.value.next_cursor is not None:
            return ()
        refs = defaultdict(set)
        by_cid = defaultdict(set)
        for owner in owners.value.items:
            ref = owner.ref
            if ref.token != expected_token or ref.layer_id != 2:
                return ()
            evidence = query.belief_evidence(ref, expected_token=expected_token)
            if (evidence.status != 'available' or evidence.token != expected_token
                    or evidence.value.next_cursor is not None):
                return ()
            raw = ref.native_id
            for receipt in evidence.value.items:
                if (not isinstance(receipt, CategoryVoteReceipt) or receipt.evidence.link_status != 'native_confirmed'
                        or receipt.canonical_object.run_id != expected_token.run_id
                        or _graph_scope(receipt.source_token.native) != _graph_scope(expected_token)
                        or receipt.source_token.native.graph_revision > expected_token.graph_revision):
                    continue
                for observation in by_source.get((receipt.evidence.source, receipt.evidence.detection_id), ()):
                    if CandidateObservation.from_receipt(observation.cid, receipt) == observation:
                        refs[raw].add(observation.cid)
                        by_cid[observation.cid].add(raw)
        if query.status != 'available':
            return ()
    except (AttributeError, TypeError, ValueError):
        return ()
    result = []
    for raw in order:
        if len(refs[raw]) == 1:
            cid = next(iter(refs[raw]))
            if cid in eligible_cids and len(by_cid[cid]) == 1 and cid not in result:
                result.append(cid)
    return tuple(result)
