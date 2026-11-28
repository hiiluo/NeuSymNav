"""Optional producer for per-instance evidence on accepted Hydra revisions."""
from collections import Counter
from dataclasses import asdict, replace
import hashlib
from itertools import islice
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from threading import Event, Lock, Thread
import time

import numpy as np

from ..contracts.hydra_evidence import HydraEvidenceIndex, HydraObjectKey, ObservationEvidence
from ..contracts.observations import validate_detection_batch
from ..contracts.reasoninggraph import DetectionGeometry
from ..perception.projector import Projector
from .association_receipts import InstanceConfirmation, confirm_evidence
from .evidence import link_frame


ARCHIVE_LIMIT = 64 * 1024**2
FRAME_BYTES = 32 * 1024**2
FRAME_COUNT = 2
FRAME_AGE_S = 2.
MANIFEST_LIMIT = 1024**2


def _sha(array):
    return hashlib.sha256(array.tobytes(order='C')).hexdigest()


def _crop(observation, detection, projected, token, directory):
    y, x = np.nonzero(detection.mask)
    x0, y0, x1, y1 = map(int, (x.min(), y.min(), x.max() + 1, y.max() + 1))
    pixels = np.s_[y0:y1, x0:x1]
    rgb, mask, depth = observation.rgb[pixels], detection.mask[pixels], observation.depth_m[pixels]
    valid = observation.valid_depth[pixels]
    filename = hashlib.sha256(detection.detection_id.encode()).hexdigest() + '.npz'
    ref = ObservationEvidence(observation.key, observation.capture_monotonic_ns, observation.clock_domain,
        detection.detection_id, directory + '/' + filename, _sha(rgb), _sha(mask), _sha(depth),
        (x0, y0, x1, y1), observation.calibration_id, token.calibration_hash, observation.pose_version,
        token.detector_profile_id, token.detector_hash, token.vocabulary_id, token.native.input_prefix_sha256,
        'rgbd_aabb_overlap_v1', 'unavailable')
    points = projected.points_world
    evidence = DetectionGeometry(ref, detection.category, observation.geometry_hash,
                                 (points.min(axis=0), points.max(axis=0)), token.labelspace_hash)
    return evidence, filename, (rgb, mask, depth, valid)


class EvidenceProducer:
    """A single bounded writer. Reading evidence never runs projection or file IO."""

    def __init__(self, root, run_id, *, accepted, native_is_current, projector=None, quota=None,
                 confirmation_source=None, lineage_reader=None, receipt_commit=None):
        if not isinstance(run_id, str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', run_id) or run_id in {'.', '..'}:
            raise ValueError('invalid ReasoningGraph run directory')
        if ((confirmation_source is not None or lineage_reader is not None)
                and not (callable(confirmation_source) and callable(lineage_reader))):
            raise ValueError('instance confirmations require a native lineage reader')
        if receipt_commit is not None and not callable(receipt_commit):
            raise TypeError('receipt_commit must be callable')
        self.root = Path(root) / 'reasoninggraph' / run_id
        self.root.mkdir(parents=True, exist_ok=False)
        if quota is not None:
            try:
                quota.reserve(('reasoninggraph', run_id), ARCHIVE_LIMIT, covered_path=self.root)
            except (OSError, ValueError, RuntimeError):
                self.root.rmdir()
                raise
        self._quota = quota
        self._reservation = ('reasoninggraph', run_id)
        self._accepted = accepted
        self._native_is_current = native_is_current
        self._projector = projector or Projector()
        self._confirmation_source = confirmation_source
        self._lineage_reader = lineage_reader
        self._receipt_commit = receipt_commit
        self._lock = Lock()
        self._pending = {}
        self._index = None
        self._written = 0
        self._attempted = None
        self._thread = None
        self._wake = Event()
        self._stop = Event()
        self._stats = dict(staged=0, dropped=0, published=0, stale=0, errors=0, budget_skipped=0)

    def stage(self, observation, batch):
        """Retain immutable inputs only after a queued Hydra offer."""
        size = sum(value.nbytes for value in (observation.rgb, observation.depth_m, observation.valid_depth,
                   observation.no_return, observation.far_plane) if value is not None)
        size += sum(detection.mask.nbytes for detection in batch.detections)
        with self._lock:
            if self._stop.is_set() or size > FRAME_BYTES or len(batch.detections) > 256:
                self._stats['dropped'] += 1
                return False
            self._pending.pop(observation.key, None)
            while self._pending and (len(self._pending) == FRAME_COUNT
                    or size + sum(item[3] for item in self._pending.values()) > FRAME_BYTES):
                self._pending.pop(next(iter(self._pending)))
                self._stats['dropped'] += 1
            self._pending[observation.key] = (observation, batch, time.monotonic(), size)
            self._stats['staged'] += 1
        self._wake.set()
        return True

    def start(self):
        actor = Thread(target=self._run, name='neusymnav-reasoninggraph', daemon=True)
        actor.start()
        self._thread = actor

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait(.05)
            self._wake.clear()
            try:
                self.update()
            except (OSError, TypeError, ValueError, RuntimeError) as exc:
                with self._lock:
                    self._stats['errors'] += 1
                    self._stats['last_error'] = type(exc).__name__
            except Exception as exc:
                with self._lock:
                    self._stats['errors'] += 1
                    self._stats['terminal_error'] = type(exc).__name__
                self._stop.set()

    def update(self):
        now = time.monotonic()
        with self._lock:
            for key, (_, _, timestamp, _) in tuple(self._pending.items()):
                if now - timestamp > FRAME_AGE_S:
                    del self._pending[key]
                    self._stats['dropped'] += 1
            if self._stop.is_set() or not self._pending:
                return False
        exact = self._accepted()
        if exact is None:
            return False
        token, endpoints = exact
        with self._lock:
            entry = self._pending.pop(token.source, None)
        if entry is None or token.native == self._attempted:
            return False
        self._attempted = token.native
        obs, batch, timestamp, _ = entry
        validate_detection_batch(obs, batch)
        if (obs.geometry_hash, obs.clock_domain, obs.capture_monotonic_ns, obs.calibration_id, obs.pose_version,
                batch.vocabulary_id) != (token.source_geometry_hash, token.clock_domain, token.capture_monotonic_ns,
                                         token.calibration_id, token.pose_version, token.vocabulary_id):
            self._bump('stale')
            return False
        return self._publish(token, endpoints, obs, batch, timestamp)

    def _publish(self, token, endpoints, obs, batch, timestamp):
        directory = f'revision-{token.native.graph_revision:010d}'
        available = ARCHIVE_LIMIT - self._written
        if available < MANIFEST_LIMIT:
            self._bump('budget_skipped')
            return False
        detections = {d.detection_id: d for d in batch.detections if d.category is not None}
        proofs, lineage = self._confirmation_inputs(token)
        index = HydraEvidenceIndex(run_id=token.native.run_id, episode_id=token.native.episode_id, max_entries=256)
        with TemporaryDirectory(prefix='.staging-', dir=self.root) as staging:
            stage = Path(staging)
            total, links, refs, receipts = 0, [], [], []
            prepared = []
            for item in self._projector.project(obs, batch):
                detection = detections.get(item.detection_id)
                if detection is not None:
                    prepared.append(_crop(obs, detection, item, token, directory))
            resolved = link_frame([row[0] for row in prepared], endpoints, token)
            for (geometry, filename, arrays), link in zip(prepared, resolved):
                links.append(asdict(link))
                detection = detections[geometry.evidence.detection_id]
                proof = proofs.get(detection.detection_id)
                receipt = confirm_evidence(token, geometry, proof, lineage,
                    raw_label=detection.raw_label, score=detection.score) if proof is not None else None
                if receipt is None and link.status != 'geometric_candidate':
                    continue
                if total + sum(value.nbytes for value in arrays) + 4096 + MANIFEST_LIMIT > available:
                    self._bump('budget_skipped')
                    return False
                rgb, mask, depth, valid = arrays
                path = stage / filename
                np.savez(path, rgb=rgb, mask=mask, depth_m=depth, valid=valid)
                total += path.stat().st_size
                if receipt is None:
                    ref = replace(geometry.evidence, link_status=link.status, link_method=link.policy_version)
                    raw_endpoint = link.endpoint.native_id
                else:
                    ref = receipt.evidence
                    raw_endpoint = receipt.canonical_object.native_id
                    receipts.append(receipt)
                refs.append(asdict(ref))
                index.add(HydraObjectKey(token.native.episode_id, token.native.run_id,
                                         raw_endpoint, token.native.graph_revision), ref)
            manifest = {**asdict(token), 'links': links, 'refs': refs}
            if self._confirmation_source is not None:
                manifest['confirmed_receipts'] = [asdict(receipt) for receipt in receipts]
            payload = json.dumps(manifest,
                                 separators=(',', ':'), sort_keys=True, allow_nan=False).encode()
            if len(payload) > MANIFEST_LIMIT or total + len(payload) > available:
                self._bump('budget_skipped')
                return False
            (stage / 'manifest.json').write_bytes(payload)
            if (self._stop.is_set() or time.monotonic() - timestamp > FRAME_AGE_S
                    or not self._native_is_current(token.native)
                    or (receipts and self._lineage_reader(token) != lineage)):
                self._bump('stale')
                return False
            stage.rename(self.root / directory)
            self._written += total + len(payload)
        if self._receipt_commit is not None and not self._receipt_commit(token, tuple(receipts)):
            self._bump('belief_rejected')
        with self._lock:
            self._index = (token.native, index)
            self._stats['published'] += 1
        return True

    def _confirmation_inputs(self, token):
        if self._confirmation_source is None:
            return {}, None
        lineage = self._lineage_reader(token)
        if lineage is None or lineage.token != token.native:
            return {}, None
        candidates = tuple(islice(self._confirmation_source(token), 257))
        if len(candidates) > 256 or any(not isinstance(proof, InstanceConfirmation) for proof in candidates):
            raise ValueError('invalid confirmation source batch')
        current = tuple(proof for proof in candidates if proof.token == token)
        detections = Counter(proof.detection_id for proof in current)
        endpoints = Counter(proof.current_endpoint for proof in current)
        return {proof.detection_id: proof for proof in current if detections[proof.detection_id] == 1
                and endpoints[proof.current_endpoint] == 1}, lineage

    def _bump(self, name):
        with self._lock:
            self._stats[name] = self._stats.get(name, 0) + 1

    def index(self, native):
        with self._lock:
            cached = self._index
        if self._stop.is_set() or cached is None or cached[0] != native or not self._native_is_current(native):
            return None
        return cached[1]

    def diagnostics(self):
        with self._lock:
            return {**self._stats, 'pending': len(self._pending), 'artifact_bytes': self._written}

    def close(self, timeout_s):
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout_s)
        with self._lock:
            self._pending.clear()
        pending = self._thread is not None and self._thread.is_alive()
        if not pending and self._quota is not None:
            self._quota.release(self._reservation)
            self._quota = None
        stats = self.diagnostics()
        return {**stats, 'worker_pending': pending, 'clean_shutdown': not pending and 'terminal_error' not in stats}
