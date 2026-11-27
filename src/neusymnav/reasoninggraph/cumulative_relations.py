"""Opt-in offline relation history over authoritative consecutive M1 views.

The caller authenticates each view and sample against their source owners.
Freshness checks are optimistic, with no native-owner lease across publication.
Consumers revalidate the exact token at their read boundary.
"""
from dataclasses import asdict, dataclass
import base64
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

import numpy as np

from ..contracts.hydra_graph import HydraReadToken
from .lifecycle import _graph_scope
from .store import _read
from .native_lineage import CanonicalObjectId, ObjectLineageView
from .relation_encoder import RelFeatureSpec, RelationTokens, decode_tokens


@dataclass(frozen=True)
class RelationSample:
    event_id: str
    origin: HydraReadToken
    asset: RelationTokens
    marker_scheme: str


@dataclass(frozen=True)
class CumulativePool:
    subject: CanonicalObjectId
    object: CanonicalObjectId
    spec: RelFeatureSpec
    marker_scheme: str
    count: int
    mean: np.ndarray
    samples: tuple[RelationSample, ...]


class CumulativeRelations:
    def __init__(self, view, is_authoritative, authenticate_sample, *, max_edges=256, max_events=1024,
                 max_bytes=32 * 1024 * 1024, max_refs_per_edge=64):
        limits = (max_edges, max_events, max_bytes, max_refs_per_edge)
        if any(type(n) is not int or not 1 <= n <= cap for n, cap in
               zip(limits, (8192, 8192, 32 * 1024 * 1024, 1024))):
            raise ValueError('invalid limits')
        if (not callable(is_authoritative) or not callable(authenticate_sample)
                or not self._valid(view) or view.token.graph_revision != 1):
            raise ValueError('first authoritative M1 view and sample authenticator required')
        if not is_authoritative(view):
            raise ValueError('stale M1 view')
        self._current = is_authoritative
        self._authenticate_sample = authenticate_sample
        self._view = view
        self._limits = limits
        self._samples = {}
        self._history = (view.token,)
        self._seen = set(view.objects) | set(view.aliases)
        self._failed = False
        self._lock = RLock()

    @staticmethod
    def _valid(view):
        if (not isinstance(view, ObjectLineageView) or not isinstance(view.token, HydraReadToken)
                or not all((view.token.source_sha256,
                view.token.build_sha256, view.token.config_sha256))):
            return False
        try:
            if len(view.objects) + len(view.aliases) > 16384 or set(view.objects) & set(view.aliases):
                return False
            for raw, identity in view.objects.items():
                if identity != CanonicalObjectId(view.token.episode_id, view.token.run_id, view.epoch, raw):
                    return False
            for raw in view.aliases:
                visited = set()
                while raw in view.aliases:
                    if raw in visited:
                        return False
                    visited.add(raw)
                    raw = view.aliases[raw]
            return True
        except (TypeError, AttributeError):
            return False

    def _available(self, view):
        return not self._failed and view is self._view and self._current(view)

    def advance(self, view):
        with self._lock:
            old = self._view
            if (self._failed or not self._valid(view) or not self._current(view)
                    or _graph_scope(old.token) != _graph_scope(view.token)
                    or view.epoch != old.epoch or view.token.graph_revision != old.token.graph_revision + 1
                    or any(view.aliases.get(k) != v for k, v in old.aliases.items())
                    or any(raw in self._seen and raw not in old.objects for raw in view.objects)
                    or len(self._history) >= 8192
                    or len(self._payload(self._samples, self._history + (view.token,))) > self._limits[2]
                    or not self._within_edge_budget(self._groups(view, self._samples))
                    or not self._current(view)):
                self._failed = True
                return False
            self._seen.update(view.objects)
            self._seen.update(view.aliases)
            self._view = view
            self._history += (view.token,)
            return True

    def _groups(self, view, samples):
        groups = {}
        for sample in samples.values():
            asset = sample.asset
            scope = (sample.origin.episode_id, sample.origin.run_id, view.epoch)
            subject = view.resolve(CanonicalObjectId(*scope, asset.subject))
            obj = view.resolve(CanonicalObjectId(*scope, asset.object_id))
            if subject is None or obj is None or subject == obj:
                continue
            key = (subject, obj, asset.spec, sample.marker_scheme)
            groups.setdefault(key, []).append(sample)
        return groups

    def _within_edge_budget(self, groups):
        refs = Counter()
        for (subject, obj, _, _), samples in groups.items():
            refs[subject, obj] += len(samples)
        return len(refs) <= self._limits[0] and all(n <= self._limits[3] for n in refs.values())

    def add(self, event_id, view, asset, *, marker_scheme='ordered_roles_v1'):
        with self._lock:
            if (not self._available(view) or not isinstance(event_id, str) or not 0 < len(event_id) <= 256
                    or not isinstance(marker_scheme, str) or not 0 < len(marker_scheme) <= 128
                    or not isinstance(asset, RelationTokens) or asset.subject not in view.objects
                    or asset.object_id not in view.objects):
                return False
            try:
                decode_tokens(asset, asset.spec)
            except (ValueError, TypeError, AttributeError):
                return False
            sample = RelationSample(event_id, view.token, asset, marker_scheme)
            if not self._authenticate_sample(sample):
                return False
            if event_id in self._samples:
                return self._samples[event_id] == sample
            trial = dict(self._samples)
            trial[event_id] = sample
            groups = self._groups(view, trial)
            _, events, byte_cap, _ = self._limits
            if (len(trial) > events or len(self._payload(trial, self._history)) > byte_cap
                    or not self._within_edge_budget(groups) or not self._available(view)):
                return False
            self._samples = trial
            return True

    def read(self, view):
        with self._lock:
            if not self._available(view):
                return None
            result = []
            for (subject, obj, spec, marker), samples in self._groups(view, self._samples).items():
                total = np.zeros((spec.token_count, spec.dimension), dtype=np.float64)
                for sample in samples:
                    total += decode_tokens(sample.asset, spec)
                mean = total / len(samples)
                mean = np.frombuffer(mean.tobytes(), dtype=mean.dtype).reshape(mean.shape)
                result.append(CumulativePool(subject, obj, spec, marker, len(samples), mean, tuple(samples)))
            return tuple(result) if self._available(view) else None

    @staticmethod
    def _payload(samples, history):
        records = [{'id': s.event_id, 'origin': asdict(s.origin), 'spec': asdict(s.asset.spec),
                    'subject': s.asset.subject, 'object': s.asset.object_id,
                    'payload': base64.b64encode(s.asset.payload).decode('ascii'),
                    'sha256': s.asset.sha256, 'marker': s.marker_scheme}
                   for s in samples.values()]
        return json.dumps({'schema_version': 1, 'kind': 'm1_cumulative_relations',
                           'history': [asdict(t) for t in history], 'samples': records},
                          sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

    def seal(self, path, view):
        with self._lock:
            if not self._available(view):
                raise ValueError('stale lineage view')
            payload = self._payload(self._samples, self._history)
            if len(payload) > self._limits[2]:
                raise ValueError('manifest exceeds byte cap')
            path = Path(path)
            with NamedTemporaryFile('wb', dir=path.parent) as staged:
                staged.write(payload)
                staged.flush()
                os.fsync(staged.fileno())
                if not self._available(view):
                    raise ValueError('stale lineage view')
                try:
                    os.link(staged.name, path)
                except FileExistsError:
                    if _read(path, self._limits[2]) != payload:
                        raise ValueError('path already seals another manifest') from None
            return hashlib.sha256(payload).hexdigest()

    def restore(self, path, view, sha256, archived_view):
        """Replay authenticated exact historical owner views; never replace committed data.

        archived_view(token) must authenticate and return the exact M1 owner view
        for that token, including revisions with no samples. The caller owns this
        external authentication; serialized data cannot establish its own lineage.
        """
        try:
            payload = _read(Path(path), self._limits[2])
            if not callable(archived_view) or hashlib.sha256(payload).hexdigest() != sha256:
                return False
            data = json.loads(payload)
            if (set(data) != {'schema_version', 'kind', 'history', 'samples'}
                    or type(data['schema_version']) is not int or data['schema_version'] != 1
                    or data['kind'] != 'm1_cumulative_relations'
                    or not isinstance(data['history'], list) or not 1 <= len(data['history']) <= 8192
                    or not isinstance(data['samples'], list) or len(data['samples']) > self._limits[1]):
                return False
            tokens = tuple(HydraReadToken(**item) for item in data['history'])
            if tokens[-1] != view.token:
                return False
            views = tuple(archived_view(t) for t in tokens)
            if any(not isinstance(v, ObjectLineageView) or v.token != t for v, t in zip(views, tokens)):
                return False
            if views[-1] is not view:
                return False
            by_token = dict(zip(tokens, views))
            trial = CumulativeRelations(views[0], lambda v: by_token.get(v.token) is v,
                                        self._authenticate_sample, max_edges=self._limits[0], max_events=self._limits[1],
                                        max_bytes=self._limits[2], max_refs_per_edge=self._limits[3])
            records = []
            for record in data['samples']:
                if set(record) != {'id', 'origin', 'spec', 'subject', 'object', 'payload', 'sha256', 'marker'}:
                    return False
                origin = HydraReadToken(**record['origin'])
                spec = RelFeatureSpec(**record['spec'])
                asset = RelationTokens(spec, record['subject'], record['object'],
                                       base64.b64decode(record['payload'], validate=True), record['sha256'])
                records.append((origin, record['id'], asset, record['marker']))
            index = 0
            for i, historical in enumerate(views):
                if i and not trial.advance(historical):
                    return False
                while index < len(records) and records[index][0] == historical.token:
                    _, event_id, asset, marker = records[index]
                    if event_id in trial._samples or not trial.add(event_id, historical, asset, marker_scheme=marker):
                        return False
                    index += 1
            if index != len(records) or trial._payload(trial._samples, trial._history) != payload:
                return False
            with self._lock:
                if (self._failed or not self._current(view)
                        or self._history != trial._history[:len(self._history)]
                        or any(trial._samples.get(k) != sample for k, sample in self._samples.items())):
                    return False
                self._view, self._history = view, trial._history
                self._samples, self._seen = trial._samples, trial._seen
                return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            return False
