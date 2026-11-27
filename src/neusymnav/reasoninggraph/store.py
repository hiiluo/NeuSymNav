"""Bounded publication of a single immutable ReasoningGraph revision."""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock

from ..contracts.hydra_graph import NativeNodeRef
from ..contracts.reasoninggraph import GraphReadToken, NativeLink
from .lifecycle import validate_progress


@dataclass(frozen=True)
class RevisionView:
    token: GraphReadToken
    links: tuple[NativeLink, ...]


def _encode(value):
    return json.dumps(asdict(value), separators=(',', ':'), sort_keys=True, allow_nan=False).encode()


def _read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError('sidecar must be a regular file')
    with path.open('rb') as stream:
        payload = stream.read(limit + 1)
    if len(payload) > limit:
        raise ValueError('sidecar exceeds byte cap')
    return payload


def _decode_link(raw, token):
    values = dict(raw)
    if values.pop('token') != asdict(token):
        raise ValueError('sidecar link scope differs from the manifest')

    def ref(value):
        values = dict(value)
        if values.pop('token') != asdict(token.native):
            raise ValueError('sidecar endpoint scope differs from native graph')
        return NativeNodeRef(token.native, **values)

    endpoint = values.pop('endpoint')
    competing = values.pop('competing')
    return NativeLink(token=token, endpoint=None if endpoint is None else ref(endpoint),
                      competing=tuple(ref(value) for value in competing), **values)


class RevisionStore:
    def __init__(self, native_is_current, *, max_links=256, max_bytes=1024 * 1024):
        if not callable(native_is_current):
            raise TypeError('publication requires a native freshness check')
        if not (type(max_links) is int and 1 <= max_links <= 8192
                and type(max_bytes) is int and 1 <= max_bytes <= 32 * 1024 * 1024):
            raise ValueError('invalid revision cache limits')
        self._max_links = max_links
        self._max_bytes = max_bytes
        self._native_is_current = native_is_current
        self._view = None
        self._lock = Lock()

    def publish(self, token, links):
        if not isinstance(token, GraphReadToken):
            raise TypeError('expected GraphReadToken')
        entries = {}
        if len(links) > self._max_links * 2:
            return False
        nbytes = len(_encode(RevisionView(token, ())))
        if nbytes > self._max_bytes:
            return False
        for link in links:
            if not isinstance(link, NativeLink) or link.token != token:
                return False
            key = (link.detector_hash, link.detection_id)
            prior = entries.get(key)
            if prior is not None:
                if prior != link:
                    return False
                continue
            nbytes += len(_encode(link)) + bool(entries)
            if len(entries) == self._max_links or nbytes > self._max_bytes:
                return False
            entries[key] = link
        view = RevisionView(token, tuple(entries[k] for k in sorted(entries)))
        with self._lock:
            if not self._native_is_current(token.native):
                return False
            if self._view is not None:
                before = self._view.token
                try:
                    validate_progress(before, token)
                except ValueError:
                    return False
                if token == before:
                    return self._view == view
            self._view = view
            return True

    def read(self, token):
        """Return the pinned view if current at this read boundary."""
        with self._lock:
            if self._view is None or self._view.token != token or not self._native_is_current(token.native):
                return None
            return self._view

    def seal(self, path, token):
        """Write an immutable manifest for the exact view and return its checksum."""
        path = Path(path)
        view = self.read(token)
        if view is None:
            raise ValueError('cannot seal an unavailable view')
        payload = _encode(view)
        with NamedTemporaryFile('wb', dir=path.parent) as staged:
            staged.write(payload)
            staged.flush()
            os.fsync(staged.fileno())
            try:
                os.link(staged.name, path)
            except FileExistsError:
                if _read(path, self._max_bytes) != payload:
                    raise ValueError('sidecar path already seals a different view') from None
        return hashlib.sha256(payload).hexdigest()

    def restore(self, path, expected_token, expected_sha256):
        """Publish a verified manifest only against the caller's current native pin."""
        try:
            raw = _read(Path(path), self._max_bytes)
            if hashlib.sha256(raw).hexdigest() != expected_sha256:
                return False
            data = json.loads(raw)
            if set(data) != {'token', 'links'} or data['token'] != asdict(expected_token):
                return False
            links = data['links']
            if not isinstance(links, list) or len(links) > self._max_links:
                return False
            return self.publish(expected_token, tuple(_decode_link(link, expected_token) for link in links))
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return False
