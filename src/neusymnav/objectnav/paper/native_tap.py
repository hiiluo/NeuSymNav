"""Run native Paper shadow admission off the policy and control thread."""

from collections import Counter
from hashlib import sha256
import json
from math import cos, isfinite, sin
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
import time
from uuid import uuid4

import numpy as np

from ...contracts.hydra_graph import HydraCalibration, OPTICAL_CAMERA
from ...contracts.observations import Taxonomy
from .semantic_candidates import PaperSemanticTap


class PaperNativeTap(PaperSemanticTap):
    """One waiting observation, one worker and one immutable publication."""

    def __init__(self, owner_factory):
        super().__init__()
        self._owner_factory = owner_factory
        self._inbox = Queue(maxsize=1)
        self._stop = Event()
        self._lock = Lock()
        self._counts = Counter()
        self._shutdown = None
        self._error = None
        self._thread = Thread(target=self._run, name='paper-native-shadow', daemon=True)
        self._thread.start()

    def offer(self, observation, batch, pose):
        with self._lock:
            if self._stop.is_set():
                return False
            try:
                self._inbox.put_nowait((observation, batch, pose))
            except Full:
                self._counts['dropped'] += 1
                return False
            self._counts['offered'] += 1
            return True

    def _run(self):
        owner = None
        try:
            while not self._stop.is_set():
                try:
                    item = self._inbox.get(timeout=.05)
                except Empty:
                    continue
                if self._stop.is_set():
                    break
                if owner is None:
                    owner = self._owner_factory()
                query = owner.consume(*item)
                if query is not None:
                    with self._lock:
                        if not self._stop.is_set():
                            self.publish(query)
                            self._counts['published'] += 1
        except (OSError, ValueError, RuntimeError, TypeError) as exc:
            self._error = str(exc)[:256]
        finally:
            self._stop.set()
            self.publish(None)
            if owner is not None:
                try:
                    self._shutdown = owner.close()
                except (OSError, RuntimeError, ValueError) as exc:
                    self._error = str(exc)[:256]

    def close(self, timeout=6.):
        with self._lock:
            self._stop.set()
            self.publish(None)
            try:
                self._inbox.get_nowait()
            except Empty:
                pass
        self._thread.join(timeout)
        return {'clean_shutdown': not self._thread.is_alive() and self._error is None
                    and (self._shutdown is None or self._shutdown.get('complete', False)),
                'error': self._error, 'counts': dict(self._counts), 'native': self._shutdown}


def body_relative_extrinsics(sensor, pose):
    (x, y, z), yaw, _ = pose
    c, s = cos(yaw), sin(yaw)
    body = np.array(((c, -s, 0., x), (s, c, 0., y), (0., 0., 1., z), (0., 0., 0., 1.)))
    return np.linalg.solve(body, sensor.T_world_camera)


def lockstep_primary_mount(spec):
    """Convert the pinned, forward Habitat sensor mount to body/optical axes."""
    if tuple(spec['orientation_xyz_rad']) != (0., 0., 0.):
        raise ValueError('native lockstep tap requires a forward primary camera')
    x, y, z = spec['position_xyz']
    return np.array(((0., 0., 1., -z), (-1., 0., 0., -x),
                     (0., -1., 0., y), (0., 0., 0., 1.)))


class PaperHydraOwner:
    """Capture exact accepted publications using the existing Hydra subprocess."""

    def __init__(self, root, config_root, command, recipes, *, fixed_mount=None):
        import yaml

        self.root = Path(root) / uuid4().hex
        self.config_root = Path(config_root)
        self.command = command
        self.recipes = recipes
        self._fixed_mount = fixed_mount
        self.runtime = None
        self._rig = None
        self._last_capture = None
        self._source = None
        self._proof_counts = Counter()
        profile = yaml.safe_load((self.config_root / 'datasets/neusymnav.yaml').read_text())
        period = profile['active_window']['full_update_separation_s']
        if type(period) not in (int, float) or not isfinite(period) or not 0 < period <= 5:
            raise ValueError('invalid Hydra full update period for Paper shadow')
        self._cadence_ns = round(period * 1e9)

    def _start(self, sensor, batch, pose, mount):
        from ...backends.hydra.runtime import HydraGraphRuntime
        from ...backends.hydra.session import HydraSession

        recipe = self.recipes[batch.vocabulary_id]
        taxonomy_path = Path(recipe['taxonomy_path'])
        if sha256(taxonomy_path.read_bytes()).hexdigest() != recipe['taxonomy_sha256']:
            raise ValueError('Paper native shadow taxonomy differs from the pinned detector recipe')
        taxonomy = Taxonomy.load(taxonomy_path)
        if taxonomy.vocabulary_id != batch.vocabulary_id:
            raise ValueError('Paper native shadow batch differs from the pinned vocabulary')
        profile_sha = sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        profile = 'paper-native-' + profile_sha + '@sha256:' + recipe['checkpoint_sha256']
        rig_id = 'paper-fixed-rig-v1' if self._fixed_mount is None else 'lockstep-forward-rig-v1'
        provenance = ('Paper measured body pose and fixed optical mount' if self._fixed_mount is None
                      else 'Pinned lockstep optical mount and simulator camera pose')
        calibration = HydraCalibration(sensor.calibration_id, rig_id, sensor.key.sensor_id,
            sensor.key.sensor_id, sensor.K, mount, sensor.pose_version, sensor.coordinate_convention,
            OPTICAL_CAMERA, sensor.depth_convention, provenance)
        native = self.root / 'native'
        session = HydraSession(sensor.key.episode_id, command=(*self.command,
            '--config-root', str(self.config_root), '--artifact-dir', str(native)),
            journal_path=self.root / 'journal.jsonl', worker_timeout_s=4., startup_timeout_s=5.,
            detail_queries=True, detail_asset_root=native / 'detail-assets', object_event_journal=True)
        self.runtime = HydraGraphRuntime(session, calibration=calibration, taxonomy=taxonomy,
            detector_profile_id=profile, reasoninggraph_enabled=True, semantic_memory={'mode': 'shadow'},
            reasoninggraph_confirmation_source=self._confirmation_source)
        from ...reasoninggraph.live_instance_confirmation import LiveInstanceConfirmation
        self._matcher = LiveInstanceConfirmation()
        self.runtime.start_reasoninggraph(self.root, None)
        self._rig = (sensor.key.episode_id, None if pose is None else pose[2], batch.vocabulary_id)

    def _confirmation_source(self, token):
        from ...reasoninggraph.live_instance_confirmation import native_mesh_claims

        current = self._source
        if current is None or current[0].key != token.source:
            return ()
        sensor, batch = current
        session = self.runtime.session
        lineage = session.object_lineage(token.native)
        journal = session.object_event_batch(token.native)
        if lineage is None or journal is None:
            self._matcher.clear()
            return ()
        if any(event.operation in ('merge', 'reconcile') for event in journal.events):
            self._matcher.clear()
        claims = {}
        if batch.detections and batch.allows_negative_evidence and len(batch.detections) <= 16:
            meshes = self._read_meshes(session, token.native, lineage.objects)
            if meshes is not None:
                claims = native_mesh_claims(sensor, batch.detections, meshes)
                self._proof_counts['mesh_complete_frames'] += 1
            else:
                self._proof_counts['mesh_incomplete_frames'] += 1
        proofs = self._matcher.observe(token, sensor, batch, lineage, claims)
        self._proof_counts['native_claims'] += len(claims)
        self._proof_counts['instance_proofs'] += len(proofs)
        return proofs

    @staticmethod
    def _read_meshes(session, token, objects):
        from ...contracts.hydra_graph import NativeDetailRequest, NativeNodeRef

        if len(objects) > 16:
            return None
        result = {}
        budget, deadline = 64, time.monotonic() + .9
        for raw in sorted(objects):
            node = NativeNodeRef(token, raw, 2)
            offset, total, points = 0, 1, []
            while offset < total:
                budget -= 1
                if budget < 0 or time.monotonic() >= deadline:
                    return None
                request = NativeDetailRequest(node, 'mesh', offset=offset, limit=64)
                page = session.read(request)
                while page.status == 'pending' and time.monotonic() < deadline:
                    time.sleep(.005)
                    page = session.read(request)
                if page.status == 'missing' and not offset:
                    break
                if page.status != 'available':
                    return None
                asset = page.value
                total = asset.total_rows
                if asset.offset != offset or total - offset > (budget + 1) * 64:
                    return None
                decoded = session.read_asset(node, asset)
                if decoded.status != 'available':
                    return None
                data = decoded.value['xyz']
                if not len(data):
                    return None
                points.append(data)
                offset += len(data)
            if points:
                result[raw] = np.concatenate(points)
        return result

    def consume(self, sensor, batch, pose):
        if self._last_capture is not None and sensor.capture_monotonic_ns - self._last_capture < self._cadence_ns:
            return None
        if batch.vocabulary_id not in self.recipes:
            raise ValueError('Paper detector vocabulary has no pinned native recipe')
        mount = self._fixed_mount if pose is None else body_relative_extrinsics(sensor, pose)
        if mount is None:
            return None
        if self.runtime is None:
            self._start(sensor, batch, pose, mount)
        if self._rig != (sensor.key.episode_id, None if pose is None else pose[2], batch.vocabulary_id) or not np.allclose(
                mount, self.runtime.calibration.body_T_camera, atol=1e-4, rtol=0):
            return None
        self._last_capture = sensor.capture_monotonic_ns
        self._source = (sensor, batch)
        session = self.runtime.session
        previous = session.stats
        if self.runtime.offer(sensor, batch).status != 'queued':
            return None
        deadline = time.monotonic() + 4.
        while time.monotonic() < deadline:
            stats = session.stats
            if stats['step_rejected'] > previous['step_rejected']:
                return None
            native = session.current_read_token()
            if stats['accepted'] > previous['accepted'] and native is not None:
                view = self.runtime.semantic_belief_view(native)
                if view is not None and view.token.source == sensor.key:
                    return self.runtime.scene_graph_query(pinned_beliefs=True)
            if session.state_token()[1]:
                raise RuntimeError('native Paper shadow worker failed')
            time.sleep(.01)
        raise RuntimeError('native Paper shadow epoch did not publish an exact belief revision')

    def close(self):
        if self.runtime is None:
            return None
        result = self.runtime.close(3.)
        result['instance_confirmation'] = dict(self._proof_counts)
        return result
