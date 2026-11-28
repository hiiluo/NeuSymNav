"""Coordinator-facing Hydra admission adapter; it never imports native bindings."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

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
                 detector_profile_id: str, display_robot=None, reasoninggraph_enabled=False,
                 reasoninggraph_confirmation_source=None, semantic_memory=None):
        if not isinstance(calibration, HydraCalibration):
            raise TypeError('calibration must be HydraCalibration')
        if not isinstance(taxonomy, Taxonomy):
            raise TypeError('taxonomy must be Taxonomy')
        if not isinstance(detector_profile_id, str) or not detector_profile_id:
            raise ValueError('detector_profile_id is required')
        if reasoninggraph_confirmation_source is not None and not callable(reasoninggraph_confirmation_source):
            raise TypeError('reasoninggraph_confirmation_source must be callable')
        self.session = session
        self.calibration = calibration
        self.taxonomy = taxonomy
        self.detector_profile_id = detector_profile_id
        self.rasterizer = HydraLabelRasterizer(taxonomy)
        self._category_by_label = {label: name for name, label in self.rasterizer.class_to_label.items()}
        self._display_robot = display_robot
        self._reasoninggraph_enabled = reasoninggraph_enabled
        self._confirmation_source = reasoninggraph_confirmation_source
        self._reasoninggraph = None
        self._reasoninggraph_start_error = None
        self._semantic_memory = None
        if semantic_memory is not None and semantic_memory.get('mode', 'off') == 'shadow':
            if not (reasoninggraph_enabled and getattr(session, 'detail_queries', False)
                    and getattr(session, 'object_event_journal', False)):
                raise ValueError('semantic memory needs evidence, exact detail tokens and the native journal')
            from ...reasoninggraph.semantic_belief_store import SemanticBeliefStore
            limits = {k: semantic_memory[k] for k in ('max_receipts', 'max_payload_bytes') if k in semantic_memory}
            self._semantic_memory = SemanticBeliefStore(taxonomy, native_is_current=session.has_detail_token, **limits)

    def start_reasoninggraph(self, root, quota):
        if not self._reasoninggraph_enabled:
            return
        from ...reasoninggraph.producer import EvidenceProducer
        try:
            self._reasoninggraph = EvidenceProducer(root, self.session.run_id,
                accepted=self._reasoninggraph_source, native_is_current=self.session.has_detail_token, quota=quota,
                confirmation_source=self._confirmation_source,
                lineage_reader=self.reasoninggraph_lineage if self._confirmation_source is not None else None,
                receipt_commit=self._commit_belief_revision if self._semantic_memory is not None else None)
            self._reasoninggraph.start()
        except (OSError, ValueError, RuntimeError) as exc:
            self._reasoninggraph_start_error = str(exc)
            if self._reasoninggraph is not None:
                self._reasoninggraph.close(0.)
                self._reasoninggraph = None

    def _commit_belief_revision(self, token, receipts):
        return self._semantic_memory.apply_revision(token, self.reasoninggraph_lineage(token), receipts,
            revision_complete=True, journal=self.session.object_event_batch(token.native))

    def semantic_belief_view(self, token):
        return None if self._semantic_memory is None else self._semantic_memory.read(token)

    def _reasoninggraph_source(self):
        state = self.state_token()
        cached = getattr(self, '_reasoninggraph_cached_source', None)
        if cached is not None and cached[0] == state:
            return cached[1]
        snapshot = self.reasoninggraph_snapshot()
        self._reasoninggraph_cached_source = (state, snapshot)
        return snapshot

    def offer(self, observation: Observation, batch: DetectionBatch):
        semantic = self.rasterizer.rasterize(observation, batch)
        frame = HydraInputAdapter.convert(observation, batch, self.calibration,
            semantic.labels, detector_profile_id=self.detector_profile_id,
            labelspace_id=semantic.labelspace_id, labelspace_hash=semantic.labelspace_hash)
        offered = self.session.offer(frame)
        if self._reasoninggraph is not None and offered.status in {'queued', 'replaced'}:
            self._reasoninggraph.stage(observation, batch)
        return offered

    def snapshot(self):
        return self.session.snapshot()

    def diagnostics(self):
        stats = self.session.stats
        if self._reasoninggraph_start_error is not None:
            return {**stats, 'reasoninggraph': {'startup_error': self._reasoninggraph_start_error}}
        if self._reasoninggraph is not None:
            return {**stats, 'reasoninggraph': self._reasoninggraph.diagnostics()}
        return stats

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
        metadata['published_monotonic_ns'] = getattr(snapshot, 'published_monotonic_ns', None)
        metadata['published_clock_domain'] = getattr(snapshot, 'published_clock_domain', None)
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

    def scene_graph_query(self, *, pinned_beliefs=False):
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
        evidence = None
        if self._reasoninggraph is not None:
            evidence = self._reasoninggraph.index(self._native_read_token(snapshot))
        reader = self.semantic_belief_view if self._semantic_memory is not None else None
        live_token = getattr(self.session, 'has_detail_token', None)
        if pinned_beliefs:
            view = self.semantic_belief_view(self._native_read_token(snapshot))
            if view is None:
                return None
            reader = lambda token: view if token == view.token.native else None
            live_token = self.session.try_has_detail_token
        query = HydraSceneGraphQuery(projection,self.taxonomy,
            labelspace_id=self.rasterizer.LABELSPACE_ID,
            labelspace_hash=self.rasterizer.labelspace_hash,
            semantic_labels=semantic_labels, calibration_id=self.calibration.calibration_id,
            evidence_index=evidence,
            belief_reader=reader,
            detail_reader=self.session if not pinned_beliefs and getattr(self.session, 'detail_queries', False) else None,
            live_token=live_token)
        if pinned_beliefs:
            query._index()
        return query

    def _native_read_token(self, state):
        from ...contracts.hydra_graph import HydraReadToken
        return HydraReadToken(self.session.episode_id, self.session.run_id, state.graph_revision,
            state.input_prefix_sha256, source_sha256=state.source_sha256,
            build_sha256=state.build_sha256, config_sha256=state.config_sha256)

    def reasoninggraph_snapshot(self):
        """Read candidate object geometry from one accepted native revision."""
        from ...contracts.hydra_graph import NativeNodeRef
        from ...contracts.reasoninggraph import GraphReadToken, NativeObjectGeometry

        state = self.session.snapshot()
        summary, transform, semantics = state.graph_summary, state.last_transform, state.last_semantics
        if (state.stale or state.replay_required or state.failure_reason or not summary
                or not transform or not semantics or state.last_source_key is None
                or summary.get('graph_revision') != state.graph_revision
                or summary.get('input_prefix_sha256') != state.input_prefix_sha256):
            return None
        try:
            native = self._native_read_token(state)
            if (transform['source_geometry_hash'] != semantics['source_geometry_hash']
                    or self.detector_profile_id != state.last_detector_profile_id):
                return None
            token = GraphReadToken(native, state.last_source_key, state.last_capture_monotonic_ns,
                state.last_clock_domain, transform['calibration_id'], transform['calibration_hash'],
                transform['source_geometry_hash'], semantics['vocabulary_id'], semantics['labelspace_hash'],
                state.last_detector_profile_id, transform['pose_version'],
                coordinate_convention=transform['coordinate_convention'])
            geometry = []
            for node in summary['nodes']:
                category = self._category_by_label.get(node.get('semantic_label'))
                if node['layer_id'] == 2 and category is not None and node.get('object_bounds') is not None:
                    ref = NativeNodeRef(native, node['native_id'], 2)
                    geometry.append(NativeObjectGeometry(ref, category, node['object_bounds']))
        except (KeyError, TypeError, ValueError):
            return None
        if not self.session.has_detail_token(native):
            return None
        return token, tuple(geometry)

    def reasoninggraph_lineage(self, token):
        """Read the optional native identity view pinned by a graph read token."""
        from ...contracts.reasoninggraph import GraphReadToken

        if not isinstance(token, GraphReadToken):
            raise TypeError('expected GraphReadToken')
        return self.session.object_lineage(token.native)

    def close(self, timeout_s: float):
        evidence_shutdown = None
        if self._reasoninggraph is not None:
            started = time.monotonic()
            evidence_shutdown = self._reasoninggraph.close(min(timeout_s, 1.))
            timeout_s = max(0., timeout_s - (time.monotonic() - started))
        result = dict(self.session.close(timeout_s))
        if evidence_shutdown is not None:
            result['reasoninggraph'] = evidence_shutdown
            result['clean_shutdown'] = not evidence_shutdown['worker_pending']
        elif self._reasoninggraph_start_error is not None:
            result['reasoninggraph'] = {'startup_error': self._reasoninggraph_start_error,
                                        'clean_shutdown': False, 'worker_pending': False}
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
