"""Bounded read-only RGB-D display cloud from committed, content-hashed assets.

This is historical visual evidence, never a NavMap or a control observation.
Only the Qt child creates AsyncCloudReader; disk/projection work runs off its
GUI thread. No new sensor, model, graph writer or IPC payload is introduced.
"""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from queue import Queue, Empty, Full
import sqlite3
from threading import Event, Thread

import numpy as np

from ..contracts import FrameKey, Observation
from ..contracts.serialization import loads
from ..recording.replay import _read_bounded

MAX_POINTS = 80000
MAX_FRAME_POINTS = 12000
MAX_SOURCES = 128
VOXEL_M = .04


def project_rgbd(obs):
    """Metric axial depth and optical K/T from this exact canonical source."""
    if not isinstance(obs, Observation) or obs.modality != 'rgbd':
        raise ValueError('primary RGB-D observation required')
    h, w = obs.depth_m.shape
    stride = max(1, int(np.ceil(np.sqrt(h*w/MAX_FRAME_POINTS))))
    yy, xx = np.mgrid[0:h:stride, 0:w:stride]
    z = obs.depth_m[yy, xx]
    valid = obs.valid_depth[yy, xx] & np.isfinite(z) & (z > 0) & (z < 10.)
    for mask in (obs.no_return, obs.far_plane):
        if mask is not None:
            valid &= ~mask[yy, xx]
    z = z[valid].astype(np.float64)
    rays = np.column_stack((xx[valid], yy[valid], np.ones(len(z)))) @ np.linalg.inv(obs.K).T
    camera = rays*z[:,None]
    points = camera @ obs.T_world_camera[:3,:3].T + obs.T_world_camera[:3,3]
    return points.astype(np.float32), obs.rgb[yy[valid], xx[valid]].copy()


@dataclass(frozen=True)
class CloudSnapshot:
    episode_id: str
    clock_domain: str
    points: np.ndarray
    colors: np.ndarray
    sources: tuple
    last_source: object
    last_capture_ns: int
    revision: int


class CommittedCloudReader:
    def __init__(self, assets_root):
        self.root = Path(assets_root)
        self._episode = None
        self._domain = None
        self._row = 0
        self._voxels = OrderedDict()
        self._sources = OrderedDict()
        self._snapshot = None
        self._revision = 0

    def read(self, envelope):
        episode, domain = envelope.hierarchy.episode_id, envelope.clock_domain
        if (episode, domain) != (self._episode, self._domain):
            self._episode, self._domain = episode, domain
            self._row = 0
            self._voxels.clear(); self._sources.clear(); self._snapshot = None
        database = self.root.parent / 'objects.sqlite3'
        if not database.is_file() or database.is_symlink():
            return self._snapshot
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True, timeout=.05) as conn:
            config = conn.execute("SELECT value FROM metadata WHERE key='config' AND length(value)<=8192").fetchone()
            if config is None:
                raise ValueError('missing cloud ledger provenance')
            config = json.loads(config[0])
            if config.get('episode_id') != episode or config.get('clock_domain') != domain:
                raise ValueError('cloud ledger episode/clock mismatch')
            row = conn.execute('SELECT rowid,source_asset,data FROM batches WHERE rowid>? AND length(data)<=1048576 ORDER BY rowid LIMIT 1', (self._row,)).fetchone()
        if row is None:
            return self._snapshot
        index, ref, record = row
        record = json.loads(record)
        # The cloud has its own historical source provenance; never show future
        # committed evidence against an earlier publication or relabel its age.
        if record['capture_monotonic_ns'] > envelope.published_monotonic_ns:
            return self._snapshot
        if not isinstance(ref, str) or len(ref) != 64 or any(c not in '0123456789abcdef' for c in ref):
            raise ValueError('invalid cloud source reference')
        payload = _read_bounded(self.root/ref, 64*1024**2)
        if hashlib.sha256(payload).hexdigest() != ref:
            raise ValueError('cloud source checksum mismatch')
        obs = loads(payload.decode())
        if (not isinstance(obs, Observation) or obs.key.episode_id != episode or obs.clock_domain != domain
                or obs.key.sensor_id != config.get('primary_sensor_id') or obs.key != FrameKey(**record['source'])
                or obs.capture_monotonic_ns != record['capture_monotonic_ns']
                or obs.clock_domain != record['clock_domain'] or obs.geometry_hash != record['geometry_hash']
                or obs.calibration_id != record['calibration_id'] or obs.pose_version != record['pose_version']):
            raise ValueError('cloud committed source/geometry mismatch')
        points, colors = project_rgbd(obs)
        if not len(points):
            # A newer empty/invalid-depth image cannot refresh the age of
            # older measured geometry that remains in the accumulated cloud.
            self._row = index
            return self._snapshot
        # Keep original measured points/colors, selecting one observation per
        # voxel. Quantization is a display decimation, not reconstructed geometry.
        keys = np.floor(points/VOXEL_M).astype(np.int64)
        for point, color, key in zip(points, colors, keys):
            key = tuple(key)
            self._voxels[key] = (point, color, index)
            self._voxels.move_to_end(key)
        while len(self._voxels) > MAX_POINTS:
            self._voxels.popitem(last=False)
        self._sources[index] = dict(source=dict(episode_id=obs.key.episode_id, sensor_id=obs.key.sensor_id, frame_index=obs.key.frame_index), capture_monotonic_ns=obs.capture_monotonic_ns,
            clock_domain=obs.clock_domain, calibration_id=obs.calibration_id, geometry_hash=obs.geometry_hash, asset_sha256=ref)
        if len(self._sources) > MAX_SOURCES:
            removed, _ = self._sources.popitem(last=False)
            self._voxels = OrderedDict((k,v) for k,v in self._voxels.items() if v[2] != removed)
        used = {v[2] for v in self._voxels.values()}
        xyz = np.asarray([v[0] for v in self._voxels.values()], dtype=np.float32).reshape(-1,3)
        rgb = np.asarray([v[1] for v in self._voxels.values()], dtype=np.uint8).reshape(-1,3)
        xyz.setflags(write=False); rgb.setflags(write=False)
        self._row = index; self._revision += 1
        self._snapshot = CloudSnapshot(episode, domain, xyz, rgb,
            tuple(self._sources[i] for i in self._sources if i in used), obs.key, obs.capture_monotonic_ns, self._revision)
        return self._snapshot


class AsyncCloudReader:
    """One worker, one replaceable pending envelope; GUI never waits for IO."""
    def __init__(self, assets_root):
        self.reader = CommittedCloudReader(assets_root)
        self.pending = Queue(maxsize=1)
        self.stop = Event()
        self.latest = None
        self.error = None
        self.thread = Thread(target=self._run, name='ui-historical-cloud', daemon=True)
        self.thread.start()

    def offer(self, envelope):
        if self.stop.is_set():
            return
        try:
            self.pending.put_nowait(envelope)
        except Full:
            try: self.pending.get_nowait()
            except Empty: pass
            try: self.pending.put_nowait(envelope)
            except Full: pass

    def _run(self):
        while not self.stop.is_set():
            try: envelope = self.pending.get(timeout=.1)
            except Empty: continue
            try:
                self.latest = self.reader.read(envelope)
                self.error = None
            except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
                self.error = str(exc)[:240]

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1.)
