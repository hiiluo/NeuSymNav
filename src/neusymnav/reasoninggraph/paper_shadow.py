"""Bounded, revision-independent capture of the Paper detector's fixed-rig inputs."""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

from ..contracts import DetectionBatch, Observation, from_dict
from ..contracts.observations import validate_detection_batch
from ..recording.replay import _read_bounded, _write_atomic


_MAX_ARCHIVE_BYTES = 128 * 1024**2
_MAX_FRAMES = 32


class PaperShadowCapture:
    """Retain immutable inputs in memory and write after the last policy action."""

    def __init__(self, root, *, max_frames=16, max_bytes=64 * 1024**2, min_interval_ns=0):
        if (type(max_frames) is not int or not 1 <= max_frames <= _MAX_FRAMES
                or type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_ARCHIVE_BYTES
                or type(min_interval_ns) is not int or not 0 <= min_interval_ns <= 5_000_000_000):
            raise ValueError('invalid Paper shadow capture budget')
        self.root = Path(root)
        self._max_frames, self._max_bytes = max_frames, max_bytes
        self._min_interval_ns = min_interval_ns
        self._charged_bytes = 0
        self._rig = None
        self._pending = []
        self._summary = None
        self._counts = Counter()

    def offer(self, observation, batch, *, robot_xyz, yaw_rad, tilt_rad):
        if self._summary is not None:
            return False
        self._counts['offered'] += 1
        if (not isinstance(observation, Observation) or observation.modality != 'rgbd'
                or not isinstance(batch, DetectionBatch) or observation.key != batch.source):
            self._counts['source_mismatch'] += 1
            return False

        rig = (observation.key.episode_id, observation.key.sensor_id, observation.clock_domain,
               observation.calibration_id, observation.K.tobytes(), tilt_rad, batch.vocabulary_id)
        if self._rig is not None and rig != self._rig:
            self._counts['calibration_changed'] += 1
            return False
        if len(self._pending) >= self._max_frames:
            self._counts['frame_budget'] += 1
            return False
        if self._pending and observation.key.frame_index <= self._pending[-1][0].key.frame_index:
            self._counts['source_mismatch'] += 1
            return False
        if (self._pending and observation.capture_monotonic_ns - self._pending[-1][0].capture_monotonic_ns
                < self._min_interval_ns):
            self._counts['cadence'] += 1
            return False
        raster_bytes = sum(array.nbytes for array in (observation.rgb, observation.depth_m, observation.valid_depth,
                            observation.no_return, observation.far_plane) if array is not None)
        mask_bytes = sum(item.mask.nbytes for item in batch.detections)
        # Charge the retained array bytes and their bounded base64 JSON representation.
        charge = 3 * (raster_bytes + mask_bytes) + 4096 + 2048 * len(batch.detections)
        if self._charged_bytes + charge > self._max_bytes:
            self._counts['byte_budget'] += 1
            return False
        self._charged_bytes += charge
        self._rig = rig
        self._pending.append((observation, batch, tuple(robot_xyz), yaw_rad, tilt_rad))
        return True

    def close(self):
        if self._summary is not None:
            return dict(self._summary)
        records, stored_bytes = [], 0
        manifest = self.root / 'manifest.json'
        error = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if manifest.exists():
                raise ValueError('Paper shadow manifest already exists')
            for observation, batch, xyz, yaw, tilt in self._pending:
                validate_detection_batch(observation, batch)
                data = _encode(dict(observation=observation.to_dict(), batch=batch.to_dict(),
                                    robot_xyz=xyz, yaw_rad=yaw, tilt_rad=tilt))
                if stored_bytes + len(data) > self._max_bytes:
                    raise ValueError('Paper shadow archive exceeds byte budget')
                name = f'frame-{observation.key.frame_index:012d}.json'
                _write_atomic(self.root / name, data)
                records.append(dict(name=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                    geometry_sha256=batch.geometry_hash))
                stored_bytes += len(data)
            _write_atomic(manifest, _encode(dict(schema_version=1, records=records)))
        except (OSError, TypeError, ValueError) as exc:
            error = str(exc)[:256]
        finally:
            self._pending.clear()
        self._summary = dict(complete=error is None, error=error, written=len(records),
                             archive_bytes=stored_bytes, counts=dict(self._counts),
                             min_interval_ns=self._min_interval_ns,
                             manifest=str(manifest) if error is None else None)
        return dict(self._summary)


def _encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read_shadow_manifest(root):
    """Read and revalidate only bounded complete paired archives."""
    root = Path(root)
    manifest = json.loads(_read_bounded(root / 'manifest.json', 128 * 1024))
    records = manifest['records']
    if manifest['schema_version'] != 1 or not isinstance(records, list) or len(records) > _MAX_FRAMES:
        raise ValueError('invalid Paper shadow manifest')
    remaining = _MAX_ARCHIVE_BYTES
    previous = -1
    for record in records:
        name, size = record['name'], record['bytes']
        if (not isinstance(name, str) or not re.fullmatch(r'frame-[0-9]{12}\.json', name)
                or type(size) is not int or not 0 < size <= remaining):
            raise ValueError('invalid Paper shadow asset')
        data = _read_bounded(root / name, remaining, size)
        remaining -= size
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError('Paper shadow asset checksum mismatch')
        entry = json.loads(data)
        obs, batch = from_dict(entry['observation']), from_dict(entry['batch'])
        validate_detection_batch(obs, batch)
        if (batch.geometry_hash != record['geometry_sha256'] or obs.key.frame_index <= previous
                or name != f'frame-{obs.key.frame_index:012d}.json'):
            raise ValueError('Paper shadow asset source mismatch')
        xyz, yaw, tilt = entry['robot_xyz'], entry['yaw_rad'], entry['tilt_rad']
        if len(xyz) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in (*xyz, yaw, tilt)):
            raise ValueError('invalid recorded body pose')
        previous = obs.key.frame_index
        yield obs, batch, (tuple(xyz), yaw, tilt)
