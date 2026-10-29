"""Single-producer bounded recorder: admission never compresses or waits for IO.

A successful append reserves memory/disk capacity, not durable success. Only a
verified, fsynced close certificate can report complete. Every attempted frame
contributes to expected_count, including rejected frames. Gaps are checked per
sensor, starting at zero (or declared first_frame_indices for clipped captures).
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from typing import Mapping
import uuid

from neusymnav.contracts import Observation
from .codec import encode as encode_binary, MAX_DECODED_BYTES, MAX_PAYLOAD_BYTES
from .replay import _canonical, _digest, _manifest_bytes, _write_atomic, _read_bounded, MAX_MANIFEST_BYTES


class ReplayWriter:
    def __init__(self, path: str | Path, *, queue_capacity: int = 8,
                 max_pending_bytes: int = 32 * 1024**2, max_bytes: int = 2 * 1024**3,
                 max_frames: int = 100_000, first_frame_indices: Mapping[str, int] | None = None,
                 source_provenance: Mapping | None = None, payload_format: str = 'json_v1'):
        for name, value in [('queue_capacity', queue_capacity), ('max_pending_bytes', max_pending_bytes),
                            ('max_bytes', max_bytes), ('max_frames', max_frames)]:
            if type(value) is not int or value <= 0:
                raise ValueError(f'{name} must be a positive integer')
        if max_bytes < 4096:
            raise ValueError('max_bytes must leave 4096 bytes for an incomplete certificate')
        if payload_format not in ('json_v1', 'npz_v2'):
            raise ValueError('unsupported recording payload_format')
        self._binary = payload_format == 'npz_v2'
        self._format_version = 2 if self._binary else 1
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        if any(self.path.iterdir()):
            raise FileExistsError(f'recording directory is not empty: {self.path}')
        self._provenance = json.loads(_canonical(dict(source_provenance or {})))
        if self._provenance.get('pose_source', 'simulator_ground_truth') != 'simulator_ground_truth':
            raise ValueError('pose_source must be simulator_ground_truth')
        self._provenance['pose_source'] = 'simulator_ground_truth'
        if len(_canonical(self._provenance)) > 2048:
            raise ValueError('source provenance exceeds metadata budget')
        self._first = dict(first_frame_indices or {})
        if len(self._first) > 16 or any(not isinstance(k, str) or not k or len(k) > 256 or type(v) is not int or v < 0
                                       for k, v in self._first.items()):
            raise ValueError('invalid first_frame_indices')
        self._queue = Queue(maxsize=queue_capacity)
        self._max_pending_bytes = max_pending_bytes
        self._max_bytes, self._max_frames = max_bytes, max_frames
        self._lock, self._stop = Lock(), Event()
        self._closed = False
        self._last = {}
        self._episode = self._domain = None
        self._latest_capture_ns = -1
        self._expected = self._accepted = self._written = self._gaps = 0
        self._pending_bytes = 0
        self._payload_bytes = self._record_metadata_bytes = 0
        self._unconfirmed_payload_bytes = 0
        self._durable_bytes = 0
        self._metadata_headroom = 2048 + len(_canonical(self._provenance)) + len(_canonical(self._first))
        self._reserved_bytes = 4096 + len(_canonical(self._provenance))
        self._rejections = Counter()
        self._error = None
        self._records = []
        self._recording_id = str(uuid.uuid4())
        self._certificate = None
        initial_payload = _manifest_bytes(self._manifest(False))
        if 2 * len(initial_payload) > max_bytes:
            raise ValueError('max_bytes cannot hold atomic initial/final metadata')
        self._initial_manifest_size = len(initial_payload)
        self._reserved_bytes = self._initial_manifest_size + self._metadata_headroom
        if self._reserved_bytes > max_bytes:
            raise ValueError('max_bytes cannot hold metadata headroom')
        _write_atomic(self.path / 'manifest.json', initial_payload)
        self._durable_bytes = self._initial_manifest_size
        self._thread = Thread(target=self._run, name='neusymnav-replay-writer', daemon=True)
        self._thread.start()

    def append(self, obs: Observation) -> bool:
        if not isinstance(obs, Observation):
            raise TypeError('obs must be an Observation')
        with self._lock:
            if self._closed:
                raise RuntimeError('recorder is closed')
            self._expected += 1
            sensor = obs.key.sensor_id
            if self._episode is not None and obs.key.episode_id != self._episode:
                self._error = 'episode changed within recording'
                raise ValueError(self._error)
            metadata_chars = len(sensor) + len(obs.key.episode_id) + len(obs.calibration_id) + len(obs.clock_domain)
            if metadata_chars > 2048:
                self._rejections['metadata_quota'] += 1
                return False
            if sensor not in self._last and len(self._last) >= 16:
                self._rejections['sensor_quota'] += 1
                return False
            previous = self._last.get(sensor, self._first.get(sensor, 0) - 1)
            if obs.key.frame_index <= previous:
                self._error = 'duplicate/nonmonotonic source frame'
                raise ValueError(self._error)
            self._gaps += obs.key.frame_index - previous - 1
            self._last[sensor] = obs.key.frame_index
            self._episode = obs.key.episode_id
            if self._domain is not None and (obs.clock_domain != self._domain or
                                             obs.capture_monotonic_ns < self._latest_capture_ns):
                self._error = 'source clock changed or regressed'
                raise ValueError(self._error)
            self._domain, self._latest_capture_ns = obs.clock_domain, obs.capture_monotonic_ns
            # Deflate worst-case overhead (or legacy base64), NPY headers,
            # escaped source metadata and manifest reserve. Admission only does
            # O(number of arrays) arithmetic; compression stays on the worker.
            size = sum(getattr(obs, name).nbytes for name in
                       ('rgb', 'depth_m', 'valid_depth', 'K', 'T_world_camera', 'no_return', 'far_plane')
                       if getattr(obs, name) is not None)
            # ensure_ascii can expand astral Unicode to 12 bytes/character.
            # Charge source metadata plus final manifest and atomic headroom.
            bound = (size + size // 1000 if self._binary else 2 * size) + 16384 + 36 * metadata_chars
            reason = None
            if size + 16384 > MAX_DECODED_BYTES:
                reason = 'payload_size_quota'
            elif self._error:
                reason = 'writer_failed'
            elif self._expected > self._max_frames:
                reason = 'frame_quota'
            elif self._reserved_bytes + bound > self._max_bytes:
                reason = 'disk_quota'
            elif self._pending_bytes + bound > self._max_pending_bytes:
                reason = 'pending_byte_quota'
            if reason:
                self._rejections[reason] += 1
                return False
            try:
                self._queue.put_nowait((obs, bound))
            except Full:
                self._rejections['queue_full'] += 1
                return False
            self._accepted += 1
            self._pending_bytes += bound
            self._reserved_bytes += bound
            return True

    def _manifest(self, stopped: bool) -> dict:
        certificate = dict(format_version=self._format_version, stopped=stopped,
                           complete=bool(stopped and not self._error and self._written and
                                         self._expected == self._written and self._gaps == 0),
                           expected_count=self._expected, accepted_count=self._accepted,
                           written_count=self._written, missing_count=self._expected - self._written,
                           source_gap_count=self._gaps, rejection_counts=dict(self._rejections),
                           error=self._error, reserved_bytes=self._reserved_bytes,
                           durable_bytes=self._durable_bytes, pending_bytes=self._pending_bytes,
                           unconfirmed_payload_bytes=self._unconfirmed_payload_bytes,
                           max_bytes=self._max_bytes)
        return dict(format_version=self._format_version, recording_id=self._recording_id,
                    episode_id=self._episode, source_provenance=self._provenance,
                    first_frame_indices=self._first, records=list(self._records), certificate=certificate)

    def _run(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                obs, bound = self._queue.get(timeout=.02)
            except Empty:
                continue
            filename = None
            try:
                if self._error:
                    continue
                payload = encode_binary(obs) if self._binary else obs.to_json().encode('utf-8')
                if len(payload) > MAX_PAYLOAD_BYTES:
                    raise OSError('serialized payload exceeds reader bound')
                ordinal = len(self._records)
                filename = f'frame-{ordinal:012d}.' + ('npz' if self._binary else 'json')
                record = dict(file=filename, sha256=_digest(payload), size_bytes=len(payload),
                              source_key=obs.key.to_dict(), source_clock_domain=obs.clock_domain,
                              source_capture_monotonic_ns=obs.capture_monotonic_ns,
                              source_geometry_hash=obs.geometry_hash)
                if len(payload) + 2 * len(_canonical(record)) + 4096 > bound:
                    raise OSError('serialized frame/manifest exceeded reserved disk bound')
                _write_atomic(self.path / filename, payload)
                with self._lock:
                    self._records.append(record)
                    self._written += 1
                    self._payload_bytes += len(payload)
                    self._record_metadata_bytes += 2 * len(_canonical(record)) + 1
                    self._durable_bytes = self._initial_manifest_size + self._payload_bytes
            except Exception as exc:
                # Rename may have succeeded before directory fsync failed.
                # Retain that evidence, charge its actual size, and fail closed.
                unconfirmed = 0
                if filename is not None:
                    try:
                        unconfirmed = (self.path / filename).stat().st_size
                    except OSError:
                        pass
                with self._lock:
                    self._payload_bytes += unconfirmed
                    self._unconfirmed_payload_bytes += unconfirmed
                    self._durable_bytes = self._initial_manifest_size + self._payload_bytes
                    self._error = f'{type(exc).__name__}: {exc}'
            finally:
                with self._lock:
                    self._pending_bytes -= bound
                    self._reserved_bytes = (self._initial_manifest_size + self._payload_bytes
                                            + self._pending_bytes + self._metadata_headroom
                                            + self._record_metadata_bytes)
                self._queue.task_done()
        try:
            # A write returning successfully is insufficient: verify accepted
            # evidence again before producing a completed certificate.
            for record in self._records:
                payload = _read_bounded(self.path / record['file'], MAX_PAYLOAD_BYTES, record['size_bytes'])
                if len(payload) != record['size_bytes'] or _digest(payload) != record['sha256']:
                    raise OSError('payload checksum mismatch at close')
        except Exception as exc:
            self._error = f'{type(exc).__name__}: {exc}'
        # Failed external deletion/truncation must not inflate actual bytes.
        try:
            self._payload_bytes = sum(path.stat().st_size for path in self.path.glob('frame-*') if path.is_file())
        except OSError as exc:
            self._error = f'cannot account payload bytes at close: {exc}'
        self._durable_bytes = self._initial_manifest_size + self._payload_bytes
        manifest = self._manifest(True)
        payload = b''
        try:
            # Final metadata includes its own byte accounting; iterate until its
            # decimal size fields stabilize. Atomic replacement temporarily keeps
            # the initial manifest alongside this final payload.
            for _ in range(16):
                payload = _manifest_bytes(manifest)
                final_size = self._payload_bytes + len(payload)
                certificate = manifest['certificate']
                if certificate['durable_bytes'] == final_size and certificate['reserved_bytes'] == final_size:
                    break
                certificate['durable_bytes'] = certificate['reserved_bytes'] = final_size
            else:
                raise OSError('final byte accounting did not stabilize')
            if len(payload) > MAX_MANIFEST_BYTES:
                raise OSError('manifest exceeds reader bound')
            if self._payload_bytes + self._initial_manifest_size + len(payload) > self._max_bytes:
                raise OSError('manifest exceeds disk quota')
            _write_atomic(self.path / 'manifest.json', payload)
            self._durable_bytes = self._reserved_bytes = final_size
            self._certificate = manifest['certificate']
        except Exception as exc:
            self._error = f'certificate write failed: {type(exc).__name__}: {exc}'
            # If final replacement happened but its directory fsync failed, a
            # visible complete manifest must not survive as a false certificate.
            manifest_path = self.path / 'manifest.json'
            try:
                if manifest_path.stat().st_size == len(payload) and manifest_path.read_bytes() == payload:
                    manifest_path.unlink()
                    directory = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            except OSError:
                pass
            self._durable_bytes = sum(path.stat().st_size for path in self.path.iterdir() if path.is_file())
            self._reserved_bytes = self._durable_bytes
            self._certificate = self._manifest(True)['certificate']

    def close(self, timeout_s: float = 30.) -> dict:
        with self._lock:
            self._closed = True
            self._stop.set()
        self._thread.join(timeout=timeout_s)
        if self._thread.is_alive():
            result = self._manifest(False)['certificate']
            result['error'] = 'writer shutdown timeout; durable completion unconfirmed'
            return result
        return dict(self._certificate)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
