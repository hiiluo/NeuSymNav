"""Coordinator-facing Hydra admission adapter; it never imports native bindings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from ...contracts import DetectionBatch, Observation
from ...contracts.hydra_graph import HydraCalibration
from ...contracts.observations import Taxonomy
from .input_adapter import HydraInputAdapter
from .labels import HydraLabelRasterizer
from .graph_adapter import HydraGraphAdapter

HYDRA_JOURNAL_MAX_LINE_BYTES = 32 * 1024 * 1024


class HydraGraphRuntime:
    """Turn an already-produced detector batch into a nonblocking session offer."""

    def __init__(self, session, *, calibration: HydraCalibration, taxonomy: Taxonomy,
                 detector_profile_id: str, display_robot=None):
        if not isinstance(calibration, HydraCalibration):
            raise TypeError('calibration must be HydraCalibration')
        if not isinstance(taxonomy, Taxonomy):
            raise TypeError('taxonomy must be Taxonomy')
        if not isinstance(detector_profile_id, str) or not detector_profile_id:
            raise ValueError('detector_profile_id is required')
        self.session = session
        self.calibration = calibration
        self.taxonomy = taxonomy
        self.detector_profile_id = detector_profile_id
        self.rasterizer = HydraLabelRasterizer(taxonomy)
        self._category_by_label = {label: name for name, label in self.rasterizer.class_to_label.items()}
        self._display_robot = display_robot

    def offer(self, observation: Observation, batch: DetectionBatch):
        semantic = self.rasterizer.rasterize(observation, batch)
        frame = HydraInputAdapter.convert(observation, batch, self.calibration,
            semantic.labels, detector_profile_id=self.detector_profile_id,
            labelspace_id=semantic.labelspace_id, labelspace_hash=semantic.labelspace_hash)
        return self.session.offer(frame)

    def snapshot(self):
        return self.session.snapshot()

    def diagnostics(self):
        return self.session.stats

    def state_token(self):
        token=getattr(self.session,'state_token',None)
        return token() if callable(token) else None

    def projection(self, *, _snapshot=None):
        if _snapshot is not None:return self._project(_snapshot)
        # Immutable display projection reused until the session state changes;
        # avoids a deep copy + re-projection of the whole graph per poll.
        token=self.state_token()
        cached=getattr(self,'_projection_cache',None)
        if token is not None and cached is not None and cached[0]==token:
            return cached[1]
        result=self._project(self.session.snapshot())
        if token is not None:self._projection_cache=(token,result)
        return result

    def _project(self, snapshot):
        summary=snapshot.graph_summary
        if summary is None:return None
        key=snapshot.last_source_key
        last_source=None if key is None else dict(episode_id=key.episode_id,
            sensor_id=key.sensor_id,frame_index=key.frame_index,
            capture_monotonic_ns=snapshot.last_capture_monotonic_ns,
            clock_domain=snapshot.last_clock_domain)
        if last_source is not None:
            last_source.update(getattr(snapshot,'last_semantics',None) or {})
        metadata={name:getattr(snapshot,name) for name in (
            'config_sha256','source_sha256','build_sha256','graph_asset_path',
            'graph_asset_sha256','graph_asset_bytes','node_counts','edge_count','last_transform')}
        if getattr(snapshot, 'room_stability', None) is not None:
            metadata['room_stability'] = snapshot.room_stability
        metadata['object_categories'] = {node['native_id']: self._category_by_label[node['semantic_label']]
            for node in summary['nodes'] if node['layer_id'] == 2
            and node.get('semantic_label') in self._category_by_label}
        if self._display_robot is not None:
            metadata['display_robot'] = {
                name: getattr(self._display_robot, name)
                for name in ('geometry_id', 'radius_m', 'height_m', 'margin_m')
            }
        return HydraGraphAdapter.project(summary,episode_id=self.session.episode_id,
            run_id=self.session.run_id,stale=snapshot.stale,
            replay_required=snapshot.replay_required,failure_reason=snapshot.failure_reason,
            last_source=last_source,native_metadata=metadata)

    def scene_graph_query(self):
        """Return a read-only semantic view of one accepted native generation.

        This reads canonical session data directly. It does not read the GUI,
        contact the child, choose a navigation goal, or certify traversability.
        """
        from .query import HydraSceneGraphQuery
        snapshot=self.session.snapshot()
        projection=self.projection(_snapshot=snapshot)
        if projection is None:return None
        semantic_labels={node['native_id']:node.get('semantic_label')
            for node in snapshot.graph_summary['nodes'] if node['layer_id']==2}
        return HydraSceneGraphQuery(projection,self.taxonomy,
            labelspace_id=self.rasterizer.LABELSPACE_ID,
            labelspace_hash=self.rasterizer.labelspace_hash,
            semantic_labels=semantic_labels,calibration_id=self.calibration.calibration_id)

    def close(self, timeout_s: float):
        result = dict(self.session.close(timeout_s))
        worker = result.get('worker_result') or {}
        asset_path = worker.get('asset_path')
        asset = Path(asset_path) if isinstance(asset_path, str) and asset_path else None
        graph_sha = None
        graph_bytes = None
        asset_ok = False
        if asset is not None:
            try:
                graph_bytes = asset.stat().st_size
                graph_sha = _sha256_file(asset)
                asset_ok = (graph_sha == worker.get('asset_sha256') and
                            graph_bytes == worker.get('asset_bytes') and
                            graph_bytes > 0)
            except OSError:
                pass
        journal = Path(self.session.journal_path)
        selected = _selected_accepted_inputs(journal, self.session.run_id)
        complete = bool(result.get('complete') and asset_ok and selected and
            worker.get('graph_revision') == len(selected) and
            isinstance(worker.get('input_prefix_sha256'), str) and
            selected[-1].get('input_prefix_sha256') == worker.get('input_prefix_sha256'))
        manifest = {
            'schema_version': 1,
            'episode_id': self.session.episode_id,
            'run_id': self.session.run_id,
            'complete': complete,
            'failure_reason': result.get('failure_reason') or
                (None if complete else 'native_export_or_selected_prefix_incomplete'),
            'graph_path': None if asset is None else str(asset.resolve()),
            'graph_sha256': graph_sha,
            'graph_bytes': graph_bytes,
            'graph_revision': worker.get('graph_revision'),
            'input_prefix_sha256': worker.get('input_prefix_sha256'),
            'config_sha256': worker.get('config_sha256'),
            'source_sha256': worker.get('source_sha256'),
            'build_sha256': worker.get('build_sha256'),
            'native_binding_sha256': worker.get('native_binding_sha256'),
            'room_stability': worker.get('room_stability'),
            'selected_inputs': selected,
            'journal_path': str(journal.resolve()),
            'journal_sha256': _sha256_file(journal) if journal.is_file() else None,
        }
        manifest_path = ((asset.parent if asset is not None else journal.parent) /
                         'hydra-export-manifest.json')
        manifest_sha = _atomic_json(manifest_path, manifest)
        result.update(complete=complete, manifest_path=str(manifest_path),
                      manifest_sha256=manifest_sha, graph_asset_verified=asset_ok)
        if not complete and not result.get('failure_reason'):
            result['failure_reason'] = manifest['failure_reason']
        return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _selected_accepted_inputs(path: Path, run_id: str) -> list[dict]:
    if not path.is_file():
        return []
    started: dict[str, dict] = {}
    accepted = []

    def consume_line(raw_line: bytes) -> bool:
        row = json.loads(raw_line.decode('utf-8'))
        if not isinstance(row, dict):
            return False
        if row.get('run_id') != run_id:
            return True
        if row.get('event') == 'batch':
            events = row.get('events', [])
            if not isinstance(events, list):
                return False
        else:
            events = (row,)
        for event in events:
            if not isinstance(event, dict):
                continue
            source = event.get('source')
            if not isinstance(source, dict):
                continue
            source_key = json.dumps(source, sort_keys=True, separators=(',', ':'))
            if event.get('event') == 'started' and isinstance(event.get('selected_frame'), str):
                payload = event['selected_frame'].encode('utf-8')
                started[source_key] = {'source': source,
                    'payload_sha256': hashlib.sha256(payload).hexdigest(),
                    'payload_bytes': len(payload)}
            elif event.get('event') == 'accepted' and event.get('accepted') is True:
                item = started.pop(source_key, None)
                if item is None:
                    continue
                item['graph_revision'] = event.get('graph_revision')
                item['input_prefix_sha256'] = event.get('input_prefix_sha256')
                accepted.append(item)
        return True

    try:
        with path.open('rb') as stream:
            while True:
                # Session protocol limits bytes before LF; allow the delimiter
                # itself in addition to that same 32 MiB cap.
                raw_line = stream.readline(HYDRA_JOURNAL_MAX_LINE_BYTES + 2)
                if not raw_line:
                    break
                content_bytes = len(raw_line) - int(raw_line.endswith(b'\n'))
                if content_bytes > HYDRA_JOURNAL_MAX_LINE_BYTES or not consume_line(raw_line):
                    return []
        accepted.sort(key=lambda item: item.get('graph_revision') or 0)
        return accepted
    except (OSError, ValueError, TypeError, UnicodeError, OverflowError):
        return []


def _atomic_json(path: Path, value: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, sort_keys=True, separators=(',', ':'),
                          allow_nan=False) + '\n').encode('utf-8')
    fd, temp_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
    return hashlib.sha256(encoded).hexdigest()
