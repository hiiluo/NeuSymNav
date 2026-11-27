"""Bounded split-token relationships for one exact native graph publication.

The caller supplies the object references from the pinned native snapshot. No
identity, co-visibility, or lifecycle continuity is inferred by this store.
"""
from dataclasses import asdict, dataclass
import base64
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

import numpy as np

from ..contracts.hydra_graph import NativeNodeRef
from ..contracts.reasoninggraph import GraphReadToken
from .relation_encoder import RelFeatureSpec, RelationTokens, decode_tokens
from .store import _read


@dataclass(frozen=True)
class RelationPool:
    subject: NativeNodeRef
    object: NativeNodeRef
    spec: RelFeatureSpec
    marker_scheme: str
    count: int
    mean: np.ndarray
    event_ids: tuple


@dataclass(frozen=True)
class RelationSupport:
    subject: NativeNodeRef
    object: NativeNodeRef
    spec: RelFeatureSpec
    marker_scheme: str
    count: int
    event_ids: tuple


def _pool_key(event):
    return (event['subject'], event['object'], RelFeatureSpec(**event['spec']), event['marker_scheme'])


class RelationStore:
    """A standalone revision-local store; event IDs must identify source evidence."""

    def __init__(self, token, endpoints, native_is_current, *, max_edges=256,
                 max_events=1024, max_bytes=32 * 1024 * 1024, max_refs_per_edge=64):
        if not isinstance(token, GraphReadToken) or not callable(native_is_current):
            raise ValueError('exact token and freshness callback required')
        if any(type(value) is not int or not 1 <= value <= ceiling for value, ceiling in
               ((max_edges, 8192), (max_events, 8192), (max_bytes, 32 * 1024 * 1024),
                (max_refs_per_edge, 1024))):
            raise ValueError('invalid limits')
        endpoints = tuple(islice(endpoints, 8193))
        if len(endpoints) > 8192 or any(
                not isinstance(r, NativeNodeRef) or r.token != token.native or r.layer_id != 2
                for r in endpoints):
            raise ValueError('endpoints must be object refs from the exact revision')
        refs = frozenset(endpoints)
        self.token, self._refs, self._current = token, refs, native_is_current
        self._limits = (max_edges, max_events, max_bytes, max_refs_per_edge)
        self._events = {}
        self._lock = RLock()

    @property
    def limits(self):
        return self._limits

    @property
    def endpoints(self):
        return self._refs

    def _available(self, token):
        return token == self.token and self._current(token.native)

    def _payload(self, events):
        data = {'schema_version': 1, 'kind': 'revision_local_split_tokens',
                'token': asdict(self.token), 'events': list(events.values())}
        return json.dumps(data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

    def apply_pair(self, event_id, subject, object_ref, asset, token, *, marker_scheme='ordered_roles_v1'):
        with self._lock:
            if not self._available(token):
                return False
            if (not isinstance(event_id, str) or not 0 < len(event_id) <= 256
                    or not isinstance(marker_scheme, str) or not 0 < len(marker_scheme) <= 128
                    or not isinstance(subject, NativeNodeRef) or not isinstance(object_ref, NativeNodeRef)
                    or subject not in self._refs or object_ref not in self._refs or subject == object_ref
                    or not isinstance(asset, RelationTokens)
                    or asset.subject != subject.native_id or asset.object_id != object_ref.native_id):
                return False
            try:
                decode_tokens(asset, asset.spec)
            except (ValueError, TypeError, AttributeError):
                return False
            record = {'id': event_id, 'subject': subject.native_id, 'object': object_ref.native_id,
                      'marker_scheme': marker_scheme, 'spec': asdict(asset.spec),
                      'payload': base64.b64encode(asset.payload).decode('ascii'), 'sha256': asset.sha256}
            prior = self._events.get(event_id)
            if prior is not None:
                return prior == record
            max_edges, max_events, max_bytes, max_refs = self._limits
            key = (subject.native_id, object_ref.native_id, asset.spec, marker_scheme)
            keys = [_pool_key(e) for e in self._events.values()]
            if (len(self._events) >= max_events or keys.count(key) >= max_refs
                    or (key not in keys and len(set(keys)) >= max_edges)):
                return False
            candidate = dict(self._events)
            candidate[event_id] = record
            if len(self._payload(candidate)) > max_bytes or not self._available(token):
                return False
            self._events = candidate
            return True

    def support(self, token):
        """Return direction and provenance without allocating or decoding tensors."""
        with self._lock:
            if not self._available(token):
                return None
            refs = {ref.native_id: ref for ref in self._refs}
            groups = {}
            for event in self._events.values():
                groups.setdefault(_pool_key(event), []).append(event['id'])
            result = tuple(RelationSupport(refs[subject], refs[obj], spec, marker,
                                           len(event_ids), tuple(event_ids))
                           for (subject, obj, spec, marker), event_ids in groups.items())
            return result if self._available(token) else None

    def read(self, token):
        with self._lock:
            if not self._available(token):
                return None
            refs = {r.native_id: r for r in self._refs}
            pools = {}
            for event in self._events.values():
                spec = RelFeatureSpec(**event['spec'])
                key = (event['subject'], event['object'], spec, event['marker_scheme'])
                asset = RelationTokens(spec, event['subject'], event['object'],
                                       base64.b64decode(event['payload'], validate=True), event['sha256'])
                array = decode_tokens(asset, spec)
                if key not in pools:
                    pools[key] = array.astype(np.float64), [event['id']]
                else:
                    total, event_ids = pools[key]
                    total += array
                    event_ids.append(event['id'])
            result = []
            for (subject, obj, spec, marker), (total, event_ids) in pools.items():
                mean = total / len(event_ids)
                immutable = np.frombuffer(mean.tobytes(), dtype=mean.dtype).reshape(mean.shape)
                result.append(RelationPool(refs[subject], refs[obj], spec, marker,
                                           len(event_ids), immutable, tuple(event_ids)))
            return tuple(result) if self._available(token) else None

    def seal(self, path, token):
        with self._lock:
            if not self._available(token):
                raise ValueError('stale relation store')
            payload = self._payload(self._events)
            if len(payload) > self._limits[2]:
                raise ValueError('manifest exceeds byte cap')
            path = Path(path)
            with NamedTemporaryFile('wb', dir=path.parent) as staged:
                staged.write(payload)
                staged.flush()
                os.fsync(staged.fileno())
                if not self._available(token):
                    raise ValueError('stale relation store')
                try:
                    os.link(staged.name, path)
                except FileExistsError:
                    if _read(path, self._limits[2]) != payload:
                        raise ValueError('path already seals another manifest') from None
            return hashlib.sha256(payload).hexdigest()

    def restore(self, path, token, sha256):
        try:
            payload = _read(Path(path), self._limits[2])
            if hashlib.sha256(payload).hexdigest() != sha256:
                return False
            data = json.loads(payload)
            if (set(data) != {'schema_version', 'kind', 'token', 'events'}
                    or type(data['schema_version']) is not int or data['schema_version'] != 1
                    or data['kind'] != 'revision_local_split_tokens'
                    or data['token'] != asdict(token) or not isinstance(data['events'], list)
                    or len(data['events']) > self._limits[1]):
                return False
            trial = RelationStore(token, self._refs, self._current, max_edges=self._limits[0],
                                  max_events=self._limits[1], max_bytes=self._limits[2],
                                  max_refs_per_edge=self._limits[3])
            refs = {r.native_id: r for r in self._refs}
            for e in data['events']:
                if set(e) != {'id', 'subject', 'object', 'marker_scheme', 'spec', 'payload', 'sha256'}:
                    return False
                spec = RelFeatureSpec(**e['spec'])
                asset = RelationTokens(spec, e['subject'], e['object'],
                                       base64.b64decode(e['payload'], validate=True), e['sha256'])
                if e['id'] in trial._events or not trial.apply_pair(e['id'], refs[e['subject']], refs[e['object']],
                                                                    asset, token, marker_scheme=e['marker_scheme']):
                    return False
            if trial._payload(trial._events) != payload:
                return False
            with self._lock:
                if not self._available(token) or (self._events and self._events != trial._events):
                    return False
                self._events = trial._events
                return True
        except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, OverflowError):
            return False
