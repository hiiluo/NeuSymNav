"""Read-only, bounded RGB-D display geometry source-bound to a Hydra revision.

The point cloud is presentation geometry only. It is projected from the exact
recorded RGB-D source named by the Hydra graph and never enters NavMap/control.
"""
from collections import OrderedDict
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import hashlib
import os
import re
import time
import numpy as np

from ..backends.hydra.graph_adapter import HydraGraphProjection
from ..contracts import FrameKey
from ..recording.codec import decode, MAX_PAYLOAD_BYTES
from ..recording.replay import _read_bounded
from .point_cloud import CloudSnapshot, MAX_POINTS, MAX_SOURCES, project_rgbd


_RECORDING_FRAME = re.compile(r'^frame-(\d{12})\.npz$')
_MAX_LOOKBACK_FILES = 4096
_MAX_INDEXED_SOURCES = 16384


class HydraAssetReader:
    """Project a small rolling display cloud from exact Hydra input records."""
    def __init__(self, recording_root):
        self.root = Path(recording_root)
        self._voxels = OrderedDict()
        self._sources = OrderedDict()
        self._episode = None
        self._domain = None
        self._last_key = None
        self._indexed_through = -1
        self._source_index = OrderedDict()
        self._revision = 0
        self.latest = None

    def read(self, graph: HydraGraphProjection):
        if not isinstance(graph, HydraGraphProjection):
            raise TypeError('HydraGraphProjection required')
        source = graph.last_source
        if source is None:
            return self.latest
        key = FrameKey(source['episode_id'], source['sensor_id'], source['frame_index'])
        capture_ns = source['capture_monotonic_ns']
        domain = source['clock_domain']
        if key == self._last_key and key.episode_id == self._episode and domain == self._domain:
            return self.latest
        if (key.episode_id, domain) != (graph.episode_id, source['clock_domain']):
            raise ValueError('Hydra asset source episode/clock mismatch')
        if (key.episode_id, domain) != (self._episode, self._domain):
            self._voxels.clear()
            self._sources.clear()
            self.latest = None
            self._episode, self._domain = key.episode_id, domain
        obs, payload = self._find_source(key, capture_ns, domain)
        transform = graph.native_metadata.get('last_transform') or {}
        expected_geometry = transform.get('source_geometry_hash')
        if expected_geometry is not None and expected_geometry != obs.geometry_hash:
            raise ValueError('Hydra asset geometry provenance mismatch')
        points, colors = project_rgbd(obs)
        if not len(points):
            self._last_key = key
            return self.latest
        asset_hash = hashlib.sha256(payload).hexdigest()
        ordinal = int(_RECORDING_FRAME.fullmatch(self._source_path.name).group(1))
        keys = np.floor(points / .04).astype(np.int64)
        for point, color, voxel in zip(points, colors, keys):
            token = tuple(int(v) for v in voxel)
            self._voxels[token] = (point, color, ordinal)
            self._voxels.move_to_end(token)
        while len(self._voxels) > MAX_POINTS:
            self._voxels.popitem(last=False)
        self._sources[ordinal] = dict(source=key.to_dict(), capture_monotonic_ns=capture_ns,
            clock_domain=domain, calibration_id=obs.calibration_id,
            geometry_hash=obs.geometry_hash, asset_sha256=asset_hash)
        if len(self._sources) > MAX_SOURCES:
            removed, _ = self._sources.popitem(last=False)
            self._voxels = OrderedDict((vkey, value) for vkey, value in self._voxels.items()
                                       if value[2] != removed)
        used = {value[2] for value in self._voxels.values()}
        xyz = np.asarray([value[0] for value in self._voxels.values()], dtype=np.float32).reshape(-1,3)
        rgb = np.asarray([value[1] for value in self._voxels.values()], dtype=np.uint8).reshape(-1,3)
        xyz.setflags(write=False); rgb.setflags(write=False)
        sources = tuple(self._sources[index] for index in self._sources if index in used)
        self._revision += 1
        self._last_key = key
        self.latest = CloudSnapshot(key.episode_id, domain, xyz, rgb, sources, key,
                                    capture_ns, self._revision)
        return self.latest

    def _find_source(self, key, capture_ns, domain):
        if self.root.is_symlink() or not self.root.is_dir():
            raise ValueError('Hydra recording root is missing or unsafe')
        self._index_new_sources()
        item=self._source_index.get((key.episode_id,key.sensor_id,key.frame_index))
        if item is None:
            raise ValueError('exact Hydra RGB-D source is not present in bounded recording lookback')
        path,expected_capture,expected_domain,expected_geometry,expected_modality=item
        if expected_capture!=capture_ns or expected_domain!=domain:
            raise ValueError('Hydra asset indexed source timestamp/clock mismatch')
        payload=_read_bounded(path,MAX_PAYLOAD_BYTES)
        try:
            obs=decode(payload)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            raise ValueError('indexed Hydra display source is corrupt') from exc
        if (obs.key!=key or obs.capture_monotonic_ns!=capture_ns or obs.clock_domain!=domain
                or obs.geometry_hash!=expected_geometry or obs.modality!=expected_modality):
            raise ValueError('Hydra asset source changed after bounded index')
        if obs.modality!='rgbd':
            raise ValueError('Hydra display cloud requires RGB-D source')
        self._source_path=path
        return obs,payload

    def _index_new_sources(self):
        """Decode each newly atomically-published recording file at most once."""
        candidates = []
        with os.scandir(self.root) as entries:
            for entry in entries:
                match = _RECORDING_FRAME.fullmatch(entry.name)
                if match and entry.is_file(follow_symlinks=False):
                    ordinal=int(match.group(1))
                    if ordinal>self._indexed_through:candidates.append((ordinal,Path(entry.path)))
        candidates.sort()
        if len(candidates)>_MAX_LOOKBACK_FILES:
            candidates=candidates[-_MAX_LOOKBACK_FILES:]
            self._indexed_through=candidates[0][0]-1
        for ordinal,path in candidates:
            payload = _read_bounded(path, MAX_PAYLOAD_BYTES)
            try:
                obs = decode(payload)
            except (ValueError, OSError, KeyError, TypeError):
                self._indexed_through=ordinal
                continue
            self._source_index[(obs.key.episode_id,obs.key.sensor_id,obs.key.frame_index)]=(
                path,obs.capture_monotonic_ns,obs.clock_domain,obs.geometry_hash,obs.modality)
            self._source_index.move_to_end((obs.key.episode_id,obs.key.sensor_id,obs.key.frame_index))
            while len(self._source_index)>_MAX_INDEXED_SOURCES:self._source_index.popitem(last=False)
            self._indexed_through=ordinal


class AsyncHydraAssetReader:
    """Single background reader with one replaceable pending graph snapshot."""
    def __init__(self, recording_root):
        self.reader = HydraAssetReader(recording_root)
        root = self.reader.root
        self.object_journal = (root.parent.parent / 'hydra' / 'journal.jsonl'
                               if (root.parent.name, root.name) == ('keyframes', 'recording')
                               else None)
        self.pending = Queue(maxsize=1)
        self.stop = Event()
        self.idle = Event();self.idle.set()
        self._state_lock=Lock()
        self.latest = None
        self.error = None
        self.requested_source = None
        self.completed_source = None
        self.completed_graph_revision = None
        self.read_count = 0
        self.last_read_ms = None
        self.replaced_pending = 0
        self.shutdown = None
        self.thread = Thread(target=self._run, name='ui-hydra-display-cloud', daemon=True)
        self.thread.start()

    def offer(self, envelope):
        if self.stop.is_set():
            return
        graph = envelope.sources.hydra_graph
        if graph is None:
            return
        with self._state_lock:
            self.requested_source = graph.last_source
            self.idle.clear()
            try:
                self.pending.put_nowait(graph)
            except Full:
                try:
                    self.pending.get_nowait()
                except Empty:
                    pass
                self.replaced_pending += 1
                try:self.pending.put_nowait(graph)
                except Full:pass

    def _run(self):
        while not self.stop.is_set():
            try:
                graph = self.pending.get(timeout=.1)
            except Empty:
                continue
            started=time.monotonic_ns()
            try:
                self.latest = self.reader.read(graph)
                self.error = None
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.error = str(exc)[:240]
            finally:
                self.last_read_ms=(time.monotonic_ns()-started)/1e6
                self.read_count+=1
                self.completed_source=graph.last_source
                self.completed_graph_revision=graph.graph_revision
                with self._state_lock:
                    if self.pending.empty() and self.completed_source==self.requested_source:self.idle.set()

    def flush(self,envelope,timeout_s=1.):
        """Offer and boundedly wait for the final displayed graph's cloud."""
        self.offer(envelope)
        completed=self.idle.wait(max(0.,float(timeout_s)))
        graph=envelope.sources.hydra_graph
        return completed and (graph is None or self.completed_source==graph.last_source or self.error is not None)

    def close(self, timeout_s=1.):
        deadline=time.monotonic()+max(0.,float(timeout_s))
        self.idle.wait(max(0.,deadline-time.monotonic()))
        self.stop.set()
        self.thread.join(timeout=max(0.,deadline-time.monotonic()))
        self.shutdown={'clean_shutdown': not self.thread.is_alive(),
                       'pending': self.pending.qsize()}
        return dict(self.shutdown)

    def report(self):
        return dict(requested_source=self.requested_source,
            completed_source=self.completed_source,
            completed_graph_revision=self.completed_graph_revision,
            read_count=self.read_count,last_read_ms=self.last_read_ms,
            replaced_pending=self.replaced_pending,pending=self.pending.qsize(),
            shutdown=self.shutdown,error=self.error)
