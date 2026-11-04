"""Deterministic, bounded admission decisions; no clocks or I/O in evaluation.

Evidence must come from committed owner rows. The caller supplies a pinned,
complete summary and a verification snapshot from the same object revision.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from collections import Counter
import numpy as np
from ..contracts._base import finite, integer, text
from ..contracts.admission import AdmissionDecision, AdmissionSnapshot
from ..contracts.observations import FrameKey


@dataclass(frozen=True)
class AdmissionPolicy:
    version: str = 'object-admission:v1'
    min_detections: int = 3
    min_views: int = 2
    min_depth_fraction: float = .5
    min_voxels: int = 20
    baseline_m: float = .3
    geometry_floor_m: float = .1
    geometry_diagonal_fraction: float = .25
    min_label_support: float = .7
    negative_views: int = 3
    recovery_views: int = 2
    max_views: int = 256

    def __post_init__(self):
        if self.version != 'object-admission:v1': raise ValueError('unsupported policy version')
        for name in ('min_detections', 'min_views', 'min_voxels', 'negative_views', 'recovery_views', 'max_views'):
            integer(getattr(self, name), name, 1)
        for name in ('min_depth_fraction', 'min_label_support'):
            if not 0 <= finite(getattr(self, name), name) <= 1: raise ValueError(name)
        for name in ('baseline_m', 'geometry_floor_m', 'geometry_diagonal_fraction'):
            if finite(getattr(self, name), name) <= 0: raise ValueError(name)
        if self.max_views < max(self.min_detections, self.min_views, self.recovery_views): raise ValueError('max_views too small')

    @property
    def policy_hash(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class AdmissionView:
    event_id: str
    object_id: str
    source: FrameKey
    detection_id: str
    object_revision: int
    capture_monotonic_ns: int
    clock_domain: str
    calibration_id: str
    geometry_hash: str
    vocabulary_id: str
    feature_space: str
    evidence_kind: str
    temporal_status: str
    depth_fraction: float
    voxel_count: int
    centroid: tuple[float, float, float]
    camera_position: tuple[float, float, float]
    label: str

    def __post_init__(self):
        from ..contracts._base import coordinates, digest, choice
        for name in ('event_id', 'object_id', 'detection_id', 'clock_domain', 'calibration_id', 'vocabulary_id', 'feature_space', 'label'):
            text(getattr(self, name), name)
        if not isinstance(self.source, FrameKey): raise ValueError('source must be FrameKey')
        digest(self.geometry_hash)
        integer(self.object_revision, 'object_revision'); integer(self.capture_monotonic_ns, 'capture_monotonic_ns'); integer(self.voxel_count, 'voxel_count')
        if not 0 <= finite(self.depth_fraction, 'depth_fraction') <= 1: raise ValueError('depth_fraction')
        choice(self.evidence_kind, {'detected', 'tracked', 'refined'}, 'evidence_kind')
        choice(self.temporal_status, {'current', 'historical'}, 'temporal_status')
        for name in ('centroid', 'camera_position'):
            object.__setattr__(self, name, coordinates(getattr(self, name), 3, name))


@dataclass(frozen=True)
class AdmissionEvidenceSummary:
    episode_id: str
    object_revision: int
    evidence_revision: int
    views: tuple[AdmissionView, ...]
    complete: bool
    unavailable_objects: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.episode_id, 'episode_id'); integer(self.object_revision, 'object_revision'); integer(self.evidence_revision, 'evidence_revision')
        if type(self.complete) is not bool: raise ValueError('complete must be bool')
        views = tuple(self.views)
        if any(not isinstance(v, AdmissionView) or v.source.episode_id != self.episode_id or v.object_revision > self.object_revision for v in views): raise ValueError('view episode/revision mismatch')
        if len({v.event_id for v in views}) != len(views): raise ValueError('duplicate event ID')
        object.__setattr__(self, 'views', views)
        unavailable = tuple(self.unavailable_objects)
        if len(set(unavailable)) != len(unavailable): raise ValueError('duplicate unavailable object')
        for oid in unavailable: text(oid, 'unavailable object')
        object.__setattr__(self, 'unavailable_objects', unavailable)


def _independent(views, baseline):
    selected = []
    for view in views:
        if all(math.dist(view.camera_position, previous.camera_position) >= baseline for previous in selected):
            selected.append(view)
    return selected


def evaluate_admission(object_snapshot, verification_snapshot, evidence_summary, prior_snapshot, policy):
    if not isinstance(policy, AdmissionPolicy) or not isinstance(evidence_summary, AdmissionEvidenceSummary): raise ValueError('invalid policy or summary')
    s = evidence_summary
    if (s.episode_id != object_snapshot.episode_id or s.object_revision != object_snapshot.revision
        or verification_snapshot.episode_id != s.episode_id or verification_snapshot.object_revision != s.object_revision):
        raise ValueError('episode/revision mismatch')
    if prior_snapshot is not None and (not isinstance(prior_snapshot, AdmissionSnapshot) or prior_snapshot.episode_id != s.episode_id or prior_snapshot.object_revision > s.object_revision or prior_snapshot.evidence_revision > s.evidence_revision or prior_snapshot.policy_hash != policy.policy_hash):
        raise ValueError('invalid prior snapshot')
    grouped = {oid: [] for oid in object_snapshot.objects}
    for v in s.views:
        try: oid = object_snapshot.resolve_id(v.object_id)
        except KeyError: raise ValueError('unknown evidence object') from None
        grouped[oid].append(v)
    decisions = {}
    for oid, obj in object_snapshot.objects.items():
        views = grouped[oid]
        priors = [] if prior_snapshot is None else [decision for old, decision in prior_snapshot.decisions.items()
            if old == oid or (old in object_snapshot.aliases and object_snapshot.resolve_id(old) == oid)]
        review_priors = [decision for decision in priors if decision.state == 'review_required']
        if review_priors:
            state = 'review_required'
            prior_transition = max(decision.quality.get('transition_revision', 0) for decision in review_priors)
        elif any(decision.state == 'admitted' for decision in priors):
            state = 'admitted'
            prior_transition = 0
        else:
            state = 'candidate'
            prior_transition = 0
        reasons = []
        # An old latch means an earlier merge already discarded a prior state;
        # it cannot be repaired from the current checkpoint alone.
        merge_unavailable = any(decision.quality.get('merge_requires_rebuild', False) for decision in priors)
        available = (s.complete and oid not in s.unavailable_objects and not merge_unavailable
            and not verification_snapshot.replay_required and len(views) <= policy.max_views and oid in verification_snapshot.objects)
        # Distinct source frames get at most one vote, also after alias union.
        unique = {}; seen_events = set()
        for v in views:
            key = (v.source.episode_id, v.source.sensor_id, v.source.frame_index)
            if v.event_id in seen_events: raise ValueError('duplicate event')
            seen_events.add(v.event_id)
            if v.evidence_kind == 'detected' and v.temporal_status == 'current': unique.setdefault(key, v)
        eligible = [v for v in unique.values() if v.depth_fraction >= policy.min_depth_fraction and v.voxel_count >= policy.min_voxels]
        independent = _independent(eligible, policy.baseline_m)
        geometry = []
        geometry_candidates = []
        if eligible:
            center = np.median(np.asarray([v.centroid for v in eligible]), axis=0)
            tolerance = max(policy.geometry_floor_m, policy.geometry_diagonal_fraction * float(np.linalg.norm(obj.bounds[1] - obj.bounds[0])))
            geometry_candidates = [v for v in eligible if np.linalg.norm(np.asarray(v.centroid)-center) <= tolerance]
            geometry = _independent(geometry_candidates, policy.baseline_m)
        labels = Counter(v.label for v in eligible)
        support = max(labels.values(), default=0) / len(eligible) if eligible else 0.
        if support < policy.min_label_support: reasons.append('label_uncertain')
        if not available:
            reasons.append('evidence_unavailable')
        else:
            verification = verification_snapshot.objects[oid]
            if state == 'admitted' and verification.negative_views >= policy.negative_views:
                state = 'review_required'
                transition = s.object_revision
            else:
                transition = prior_transition
                if state == 'review_required':
                    fresh = _independent([v for v in geometry_candidates if v.object_revision > transition], policy.baseline_m)
                    if len(fresh) >= policy.recovery_views:
                        state = 'admitted'
                elif state == 'candidate' and len(eligible) >= policy.min_detections and len(independent) >= policy.min_views and len(geometry) >= policy.min_views:
                    state = 'admitted'
        transition = locals().get('transition', 0) if available else prior_transition
        if getattr(obj, 'lifecycle', None) in {'retired', 'merged'}:
            state = 'candidate'
            reasons.append('inactive_lifecycle')
        if state == 'candidate': reasons.append('insufficient_support')
        if state == 'review_required': reasons.append('negative_visibility_review')
        quality = dict(detector_observations=len(eligible), independent_views=len(independent), geometry_views=len(geometry), label_support=support, depth_fraction_min=min((v.depth_fraction for v in unique.values()), default=None), transition_revision=transition, merge_requires_rebuild=merge_unavailable)
        decisions[oid] = AdmissionDecision(oid, state, 'available' if available else 'unavailable', tuple(reasons), tuple(v.event_id for v in eligible), quality)
        del transition
    return AdmissionSnapshot(s.episode_id, s.object_revision, s.evidence_revision, policy.version, policy.policy_hash, decisions)


def committed_evidence_summary(owner, *, policy=AdmissionPolicy()):
    """Read a bounded summary from committed owner rows under its owner lock.

    Old ledgers and cap overflow are explicitly incomplete. No old checkpoint
    is silently upgraded to admitted and no denominator is inferred from clouds.
    This reads at most max_views+1 rows per object, with no unbounded Python
    event set; the durable owner ledger remains the deduplication authority.
    """
    with owner._mutex:
        snapshot = owner.snapshot()
        views = []
        complete = True
        unavailable = set()
        for oid in snapshot.objects:
            rows = owner.ledger.connection.execute(
                'SELECT event_id,data FROM views WHERE object_id=? ORDER BY rowid LIMIT ?',
                (oid, policy.max_views + 1)).fetchall()
            if len(rows) > policy.max_views:
                unavailable.add(oid)
                continue
            for row in rows:
                r = json.loads(row['data'])
                e = r.get('admission_evidence')
                if (not isinstance(e, dict) or e.get('version') != 'source-mask-world-voxel-lower-bound:v1'
                    or not isinstance(e.get('mask_pixels'), int) or e['mask_pixels'] <= 0
                    or not isinstance(e.get('valid_depth_pixels'), int)
                    or not 0 <= e['valid_depth_pixels'] <= e['mask_pixels']):
                    unavailable.add(oid)
                    continue
                try:
                    if not 0.3 <= finite(r['score'], 'score') <= 1:
                        continue
                    views.append(AdmissionView(row['event_id'], oid, FrameKey(**r['source']),
                        r['detection_id'], r['object_revision'], r['capture_monotonic_ns'],
                        r['clock_domain'], r['calibration_id'], r['geometry_hash'], r['vocabulary_id'],
                        e['feature_space'], r['evidence_kind'], r['temporal_status'],
                        e['valid_depth_pixels'] / e['mask_pixels'], e['voxel_count'],
                        tuple(e['centroid']), tuple(r['camera_position']), r['category'] or r['raw_label']))
                except (KeyError, TypeError, ValueError):
                    unavailable.add(oid)
        return AdmissionEvidenceSummary(snapshot.episode_id, snapshot.revision,
            snapshot.revision, tuple(views), complete, tuple(sorted(unavailable)))


class AdmissionJournal:
    """Durably checkpoint decisions; latch unresolved negative gaps per object."""
    KEY = 'admission_journal_v1'

    def __init__(self, owner, policy=AdmissionPolicy()):
        from ..contracts.serialization import loads
        self.owner, self.policy = owner, policy
        with owner._mutex:
            raw = owner.ledger.get(self.KEY)
            self.prior = None
            self.gaps = set()
            self.overflow = False
            count = owner.ledger.connection.execute('SELECT count(*) FROM negatives').fetchone()[0]
            self.negative_count = 0
            if raw is not None:
                data = json.loads(raw)
                if (set(data) != {'snapshot', 'negative_count', 'gaps', 'overflow'}
                    or type(data['negative_count']) is not int or not isinstance(data['gaps'], list)
                    or any(not isinstance(x, str) for x in data['gaps']) or type(data['overflow']) is not bool):
                    raise ValueError('invalid admission journal')
                self.prior = loads(data['snapshot'])
                if (not isinstance(self.prior, AdmissionSnapshot) or self.prior.episode_id != owner.snapshot().episode_id
                    or self.prior.policy_hash != policy.policy_hash or not 0 <= data['negative_count'] <= count):
                    raise ValueError('admission journal profile/ledger mismatch')
                self.gaps = set(data['gaps'])
                self.overflow = data['overflow']
                self.negative_count = data['negative_count']

    def evaluate(self, verification_owner):
        from dataclasses import replace
        from ..contracts.serialization import dumps
        from ..verification.negative import current_source
        from .ledger import canonical
        with self.owner._mutex:
            summary = committed_evidence_summary(self.owner, policy=self.policy)
            verification = verification_owner.snapshot()
            rows = self.owner.ledger.connection.execute(
                'SELECT event_id,object_id FROM negatives ORDER BY rowid LIMIT ? OFFSET ?',
                (self.policy.max_views + 1, self.negative_count)).fetchall()
            if len(rows) > self.policy.max_views:
                self.overflow = True
            for row in rows[:self.policy.max_views]:
                proof = verification_owner._db.execute(
                    'SELECT accepted,reason,data FROM negatives WHERE event_id=?', (row['event_id'],)).fetchone()
                uncertain = proof is None
                if proof is not None:
                    record = json.loads(proof['data'])
                    if proof['accepted']:
                        uncertain = (record.get('consumer_epoch') != verification_owner._negative_epoch or not current_source(record,
                            now_ns=verification_owner._now_ns(), clock_domain=verification_owner.clock_domain))
                    elif proof['reason'] == 'historical_or_expired':
                        # Live rejection was never credited. A replay or old
                        # ambiguous record cannot prove the lost interval.
                        uncertain = record.get('consumption_mode') != 'live'
                if uncertain:
                    try: self.gaps.add(self.owner.resolve_id(row['object_id']))
                    except KeyError: self.overflow = True
            canonical_gaps = set()
            for oid in self.gaps:
                try: canonical_gaps.add(self.owner.resolve_id(oid))
                except KeyError: self.overflow = True
            self.gaps = canonical_gaps
            summary = replace(summary, complete=summary.complete and not self.overflow,
                unavailable_objects=tuple(sorted(set(summary.unavailable_objects) | self.gaps)))
            result = evaluate_admission(self.owner.snapshot(), verification, summary, self.prior, self.policy)
            if self.gaps or self.overflow:
                decisions = dict(result.decisions)
                for oid, decision in decisions.items():
                    if self.overflow or oid in self.gaps:
                        decisions[oid] = replace(decision, reason_codes=decision.reason_codes + ('negative_recovery_gap',))
                result = replace(result, decisions=decisions)
            conn = self.owner.ledger.connection
            count = conn.execute('SELECT count(*) FROM negatives').fetchone()[0]
            data = canonical(dict(snapshot=dumps(result), negative_count=count, gaps=sorted(self.gaps), overflow=self.overflow))
            conn.execute('BEGIN IMMEDIATE')
            try:
                self.owner.ledger.set(self.KEY, data)
                conn.execute('COMMIT')
            except BaseException:
                conn.execute('ROLLBACK')
                raise
            self.prior = result
            self.negative_count = count
            return result
