"""Checksummed schema-v1 JSON and schema-v2 binary recordings; no capture is published on a live clock.

``frames`` uses a private replay domain and retains source intervals. The
manifest preserves original capture times/domains and source geometry hashes.
``source_frames`` is a forensic byte-validation API, never a live PoseSource.
Checksums detect accidental damage; they are not authentication signatures.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
import stat
from pathlib import Path
import time
from typing import Iterator
import uuid

from neusymnav.contracts import Observation
from .codec import decode as decode_binary

MAX_MANIFEST_BYTES = 64 * 1024**2


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bounded(path: Path, limit: int, expected_size: int | None = None) -> bytes:
    """Bound the actual read even if a payload changes after its stat check."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ValueError('file size exceeds reader bound or is not a regular file')
        if expected_size is not None and info.st_size != expected_size:
            raise ValueError('payload size/checksum mismatch')
        payload = stream.read(min(limit, info.st_size) + 1)
        if len(payload) != info.st_size:
            raise ValueError('file size changed during bounded read')
        return payload


def _write_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(path.name + '.tmp')
    try:
        with temporary.open('wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _manifest_bytes(manifest: dict) -> bytes:
    value = dict(manifest)
    value['manifest_sha256'] = _digest(_canonical(manifest))
    return _canonical(value)


class ReplayReader:
    """Read one isolated episode, rejecting incomplete recordings by default.

    ``allow_incomplete`` permits recovery of individually verified frames; it
    never changes the completeness certificate. No sleeping or live timing is
    performed. One reader owns one immutable replay-clock identity.
    """
    def __init__(self, path: str | Path, *, allow_incomplete: bool = False,
                 start_ns: int | None = None, session: ReplaySession | None = None):
        self.path = Path(path)
        self.allow_incomplete = allow_incomplete
        self.start_ns = time.monotonic_ns() if start_ns is None else start_ns
        if type(self.start_ns) is not int or self.start_ns < 0:
            raise ValueError('start_ns must be nonnegative integer')
        self.clock_domain = 'replay:' + str(uuid.uuid4())
        if session is not None:
            if start_ns is not None:raise ValueError('session supplies start_ns; do not override')
            session.validate_input(self.path)
            self.start_ns=session.start_ns;self.clock_domain=session.clock_domain
        try:
            value = json.loads(_read_bounded(self.path / 'manifest.json', MAX_MANIFEST_BYTES))
            checksum = value.pop('manifest_sha256')
            if (checksum != _digest(_canonical(value)) or type(value.get('format_version')) is not int
                    or value['format_version'] not in (1, 2)):
                raise ValueError('manifest checksum or version mismatch')
            if not isinstance(value['records'], list) or not isinstance(value['certificate'], dict):
                raise ValueError('invalid manifest records/certificate')
            if value['source_provenance']['pose_source'] != 'simulator_ground_truth':
                raise ValueError('invalid manifest pose provenance')
        except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError('cannot read valid replay manifest') from exc
        self.manifest = value
        self.certificate = dict(value['certificate'])
        certificate = self.certificate
        if certificate.get('complete'):
            count = certificate.get('written_count')
            if (certificate.get('stopped') is not True or type(count) is not int or count <= 0
                    or certificate.get('expected_count') != count
                    or certificate.get('accepted_count') != count
                    or certificate.get('missing_count') != 0
                    or certificate.get('source_gap_count') != 0
                    or certificate.get('rejection_counts') or certificate.get('error') is not None
                    or len(value['records']) != count):
                raise ValueError('invalid completed certificate or source gap')

    def _source_frames(self) -> Iterator[Observation]:
        if not self.certificate.get('complete') and not self.allow_incomplete:
            raise ValueError('incomplete recording; recovery requires allow_incomplete=True')
        seen = set()
        last = {}
        try:
            if self.certificate['written_count'] != len(self.manifest['records']):
                raise ValueError('manifest count mismatch')
            for ordinal, record in enumerate(self.manifest['records']):
                binary = self.manifest['format_version'] == 2
                filename = f'frame-{ordinal:012d}.' + ('npz' if binary else 'json')
                if record['file'] != filename:
                    raise ValueError('invalid manifest payload reference')
                path = self.path / filename
                if path.is_symlink():
                    raise ValueError('payload may not be a symlink')
                expected_size = record['size_bytes']
                if type(expected_size) is not int or not 0 < expected_size <= 64 * 1024**2:
                    raise ValueError('payload size exceeds reader bound')
                payload = _read_bounded(path, 64 * 1024**2, expected_size)
                if len(payload) != record['size_bytes'] or _digest(payload) != record['sha256']:
                    raise ValueError('payload checksum mismatch')
                source = decode_binary(payload) if binary else Observation.from_json(payload.decode('utf-8'))
                if not isinstance(source, Observation):
                    raise ValueError('payload is not an Observation')
                if (source.key.episode_id != self.manifest['episode_id']
                        or source.key.to_dict() != record['source_key']
                        or source.capture_monotonic_ns != record['source_capture_monotonic_ns']
                        or source.clock_domain != record['source_clock_domain']
                        or source.geometry_hash != record['source_geometry_hash']):
                    raise ValueError('payload source provenance mismatch')
                if source.key in seen or source.key.frame_index <= last.get(source.key.sensor_id, -1):
                    raise ValueError('duplicate/nonmonotonic payload key')
                previous = last.get(source.key.sensor_id,
                                    self.manifest['first_frame_indices'].get(source.key.sensor_id, 0) - 1)
                if self.certificate.get('complete') and source.key.frame_index != previous + 1:
                    raise ValueError('source frame gap conflicts with completed certificate')
                seen.add(source.key)
                last[source.key.sensor_id] = source.key.frame_index
                yield source
        except (OSError, KeyError, TypeError, UnicodeError, ValueError) as exc:
            self.certificate['complete'] = False
            self.certificate['error'] = str(exc)
            raise ValueError(f'replay payload validation failed: {exc}') from exc

    def source_frames(self) -> Iterator[Observation]:
        """Forensic source bytes with their ORIGINAL domain; never feed control."""
        yield from self._source_frames()

    def frames(self) -> Iterator[Observation]:
        anchor = None
        domain = None
        last_timestamp = -1
        for source in self._source_frames():
            if anchor is None:
                anchor, domain = source.capture_monotonic_ns, source.clock_domain
            delta = source.capture_monotonic_ns - anchor
            if source.clock_domain != domain or delta < last_timestamp:
                self.certificate['complete'] = False
                raise ValueError('source clock domain changed or timestamps regressed')
            last_timestamp = delta
            yield replace(source, capture_monotonic_ns=self.start_ns + delta,
                          clock_domain=self.clock_domain)


class ReplaySession:
    """Persisted replay identity bound to exact input and a virtual clock."""
    def __init__(self,path,state):
        self.path=Path(path);self.state=state
        self.start_ns=state['start_ns'];self.clock_domain='replay:'+state['session_id']

    @classmethod
    def open(cls,path,input_path,*,start_ns=None):
        path=Path(path);digest=_digest((Path(input_path)/'manifest.json').read_bytes())
        if path.exists():
            try:
                state=json.loads(path.read_text())
                if set(state)!={'schema_version','session_id','start_ns','current_ns','input_sha256'} or type(state['schema_version']) is not int or state['schema_version']!=1:
                    raise ValueError('unsupported replay session schema')
                uuid.UUID(state['session_id'])
                if any(type(state[k]) is not int or state[k]<0 for k in ('start_ns','current_ns')) or state['current_ns']<state['start_ns']:
                    raise ValueError('invalid replay virtual clock')
                if state['input_sha256']!=digest:raise ValueError('replay input manifest changed; session input mismatch')
                if start_ns is not None and start_ns!=state['start_ns']:raise ValueError('replay session start mismatch')
            except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:raise ValueError('invalid persisted replay session') from exc
        else:
            start=1_000_000_000 if start_ns is None else start_ns
            if type(start) is not int or start<0:raise ValueError('start_ns must be nonnegative integer')
            state=dict(schema_version=1,session_id=str(uuid.uuid4()),start_ns=start,current_ns=start,input_sha256=digest)
            path.parent.mkdir(parents=True,exist_ok=True);_write_atomic(path,_canonical(state))
        return cls(path,state)

    def validate_input(self,path):
        if _digest((Path(path)/'manifest.json').read_bytes())!=self.state['input_sha256']:
            raise ValueError('replay input manifest changed; session input mismatch')

    def now_ns(self):return self.state['current_ns']

    def advance(self,capture_ns):
        if type(capture_ns) is not int or capture_ns<0:raise ValueError('virtual clock requires nonnegative integer')
        self.state['current_ns']=max(self.state['current_ns'],capture_ns)
        _write_atomic(self.path,_canonical(self.state))
