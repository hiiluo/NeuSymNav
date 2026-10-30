"""Read-only committed-ledger evidence export for independent offline annotation.

The exporter never opens a runtime owner or asset writer. A shared owner lock
requires a closed, checkpointed ledger; SQLite is opened immutable and read-only
with one transaction covering the checkpoint and selected rows. It exports the
first bounded source-ordered committed batches,
including empty batches and detections that could not be projected into memory.
Ledger identity endpoints reflect final canonical memory, not online identity.
"""

from __future__ import annotations

import hashlib
from contextlib import contextmanager
import fcntl
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile

import numpy as np
from PIL import Image, ImageDraw

from ..contracts.graphs import ObjectSnapshot
from ..contracts.observations import Observation, DetectionBatch, Taxonomy, validate_detection_batch
from ..contracts.serialization import loads


_MAX_BYTES = 64 * 1024**2


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite JSON value')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def _read(path):
    """Bound the actual read and disallow symlinks, FIFOs and devices."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_BYTES:
            raise ValueError('input exceeds 64 MiB bound or is not a regular file')
        raw = stream.read(min(info.st_size, _MAX_BYTES) + 1)
        if len(raw) != info.st_size:
            raise ValueError('input size changed during bounded read')
        return raw


def _asset(root, connection, ref):
    if not isinstance(ref, str) or not re.fullmatch('[0-9a-f]{64}', ref):
        raise ValueError('invalid SHA-256 asset reference')
    if connection.execute('SELECT 1 FROM assets WHERE ref=?', (ref,)).fetchone() is None:
        raise ValueError('unregistered committed asset')
    raw = _read(root / 'assets' / ref)
    if _sha(raw) != ref:
        raise ValueError('asset checksum mismatch')
    return raw


def _metadata(connection, key):
    row = connection.execute('SELECT length(value) FROM metadata WHERE key=?', (key,)).fetchone()
    if row is None or row[0] > _MAX_BYTES:
        raise ValueError(f'missing or oversized ledger {key}')
    return connection.execute('SELECT value FROM metadata WHERE key=?', (key,)).fetchone()[0]


@contextmanager
def _snapshot_connection(root):
    """Read a quiescent checkpoint without SQLite creating WAL/SHM files.

    Immutable SQLite ignores WAL, so explicitly reject nonempty WAL and hold the
    same owner lock used by the writer for the entire transaction. Recovery of a
    crash-left WAL belongs to the owner, never this offline extraction path.
    """
    database = root / 'objects.sqlite3'
    if not database.is_file() or database.is_symlink():
        raise ValueError('existing regular objects.sqlite3 required')
    descriptor = os.open(root/'owner.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as owner_lock:
        if not stat.S_ISREG(os.fstat(owner_lock.fileno()).st_mode):
            raise ValueError('regular owner lock required')
        try:
            fcntl.flock(owner_lock.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('active ledger must be closed before offline export') from exc
        wal = root/'objects.sqlite3-wal'
        if wal.is_symlink() or (wal.exists() and (not wal.is_file() or wal.stat().st_size)):
            raise ValueError('ledger must be checkpointed before offline export')
        connection = sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1', uri=True, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            yield connection
        finally:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            connection.close()


def _recording(raw):
    manifest = _json(raw)
    if not isinstance(manifest, dict):
        raise ValueError('invalid recording manifest')
    checksum = manifest.pop('manifest_sha256', None)
    if checksum != _sha(_canonical(manifest).encode()) or manifest.get('format_version') not in (1, 2):
        raise ValueError('recording manifest checksum/version mismatch')
    if not isinstance(manifest.get('records'), list):
        raise ValueError('recording manifest requires source records')
    records = {}
    for record in manifest['records']:
        if not isinstance(record, dict) or 'source_key' not in record:
            raise ValueError('invalid recording source record')
        key = _canonical(record['source_key'])
        if key in records:
            raise ValueError('duplicate recording source key')
        records[key] = record
    return manifest, records


def _preview(directory, ordinal, source, batch):
    image = Image.fromarray(source.rgb)
    image.save(directory / f'{ordinal:06d}-rgb.png')
    pixels = source.rgb.copy()
    for detection in batch.detections:
        pixels[detection.mask] = (pixels[detection.mask].astype(float)*.65 + np.array([255, 120, 0])*.35).astype(np.uint8)
    overlay = Image.fromarray(pixels)
    draw = ImageDraw.Draw(overlay)
    for detection in batch.detections:
        y, x = np.nonzero(detection.mask)
        draw.rectangle((int(x.min()),int(y.min()),int(x.max()),int(y.max())), outline='orange', width=1)
        label = f'{detection.detection_id}: {detection.raw_label} {detection.score:.3f}'
        draw.text((int(x.min()), max(0, int(y.min())-11)), label.encode('ascii','replace').decode(), fill='white')
    overlay.save(directory / f'{ordinal:06d}-predictions.png')


def _export_rows(connection, root, stage, config, snapshot, rows, records):
    frames, source_metadata = [], []
    identities = 0
    last_index, last_capture = -1, -1
    for ordinal, row in enumerate(rows):
        data = _json(row['data'])
        source_raw = _asset(root, connection, row['source_asset'])
        batch_raw = _asset(root, connection, row['batch_asset'])
        source, batch = loads(source_raw), loads(batch_raw)
        if not isinstance(source, Observation) or not isinstance(batch, DetectionBatch):
            raise ValueError('ledger assets must be Observation and DetectionBatch')
        validate_detection_batch(source, batch)
        if (source.key.episode_id != config['episode_id'] or source.key.sensor_id != config['primary_sensor_id']
                or source.clock_domain != config['clock_domain'] or batch.vocabulary_id != config['vocabulary_id']):
            raise ValueError('ledger source/profile/vocabulary binding mismatch')
        key = [source.key.episode_id, source.key.sensor_id, source.key.frame_index,
               config['detector_profile_id'], batch.vocabulary_id]
        if row['batch_key'] != _canonical(key):
            raise ValueError('committed batch key mismatch')
        expected = dict(source=dict(episode_id=source.key.episode_id, sensor_id=source.key.sensor_id,
                                   frame_index=source.key.frame_index),
                        capture_monotonic_ns=source.capture_monotonic_ns, clock_domain=source.clock_domain,
                        geometry_hash=source.geometry_hash, calibration_id=source.calibration_id,
                        pose_version=source.pose_version, detector_profile_id=config['detector_profile_id'],
                        vocabulary_id=batch.vocabulary_id, source_asset=row['source_asset'], batch_asset=row['batch_asset'])
        if any(data.get(name) != value for name, value in expected.items()):
            raise ValueError('committed source geometry/calibration/time binding mismatch')
        if data.get('completion') != batch.completion or data.get('cap_reached') != batch.cap_reached:
            raise ValueError('committed batch completion mismatch')
        record = records.get(_canonical(source.key.to_dict()))
        if (record is None or record.get('source_geometry_hash') != source.geometry_hash
                or record.get('source_clock_domain') != source.clock_domain
                or record.get('source_capture_monotonic_ns') != source.capture_monotonic_ns):
            raise ValueError('recording does not bind committed source')
        if source.key.frame_index <= last_index or source.capture_monotonic_ns <= last_capture:
            raise ValueError('committed sources must increase in index and capture time')
        last_index, last_capture = source.key.frame_index, source.capture_monotonic_ns
        height, width = source.rgb.shape[:2]
        if width * height > 16_777_216 or len(batch.detections) > 4096:
            raise ValueError('quality frame bound exceeded')
        views = connection.execute(
            'SELECT v.event_id,v.object_id,v.data FROM views v JOIN events e ON e.event_id=v.event_id '
            'WHERE e.batch_key=? ORDER BY v.event_id', (row['batch_key'],)).fetchall()
        if {view['event_id'] for view in views} != set(data.get('projected_event_ids', [])):
            raise ValueError('projected detection view support mismatch')
        detection_ids = {d.detection_id for d in batch.detections}
        if set(data.get('detections', {})) != detection_ids:
            raise ValueError('committed detection asset support mismatch')
        endpoint = {}
        for view in views:
            view_data = _json(view['data'])
            if any(view_data.get(name) != value for name, value in expected.items()):
                raise ValueError('view source binding mismatch')
            detection_id = view_data.get('detection_id')
            if detection_id not in detection_ids or detection_id in endpoint:
                raise ValueError('invalid or duplicate projected detection view')
            identity = view['object_id']
            if identity is not None:
                try:
                    identity = snapshot.resolve_id(identity)
                except KeyError as exc:
                    raise ValueError('dangling final canonical identity') from exc
            endpoint[detection_id] = identity
        objects = []
        details = []
        for detection in batch.detections:
            refs = data['detections'][detection.detection_id]
            mask_raw = _asset(root, connection, refs['mask_asset'])
            mask = np.load(io.BytesIO(mask_raw), allow_pickle=False)
            if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or not np.array_equal(mask, detection.mask):
                raise ValueError('committed mask does not match detection batch')
            y, x = np.nonzero(mask)
            box = [int(x.min()),int(y.min()),int(x.max())+1,int(y.max())+1]
            if refs.get('crop_bbox_xyxy') != box:
                raise ValueError('committed detection bbox mismatch')
            relative = f'masks/{ordinal:06d}-{len(objects):04d}.npy'
            (stage / relative).write_bytes(mask_raw)
            output = dict(id=detection.detection_id, label=detection.category or detection.raw_label,
                          score=float(detection.score), bbox=box,
                          mask=dict(path=relative,sha256=_sha(mask_raw)))
            identity = endpoint.get(detection.detection_id)
            if identity is not None:
                output['identity'] = identity
                identities += 1
            objects.append(output)
            details.append(dict(id=detection.detection_id, raw_label=detection.raw_label, category=detection.category))
        status = batch.completion
        if status == 'unknown' or batch.cap_reached or (status == 'failed' and objects):
            status = 'partial'
        frame_id = f'{source.key.sensor_id}:{source.key.frame_index}'
        frames.append(dict(frame_id=frame_id,frame_index=source.key.frame_index,
            capture_monotonic_ns=source.capture_monotonic_ns, source_sha256=row['source_asset'],
            geometry_hash=source.geometry_hash,width=width,height=height,status=status,objects=objects))
        source_metadata.append(dict(frame_id=frame_id, **expected,
            completion=batch.completion,cap_reached=batch.cap_reached,sim_time_s=source.sim_time_s,
            depth_convention=source.depth_convention, coordinate_convention=source.coordinate_convention,
            raw_detection_labels=details))
        _preview(stage/'previews', ordinal, source, batch)
    return frames, source_metadata, identities


def export_quality(ledger_root, *, scene_id, recording_manifest, taxonomy_path, out,
                   max_frames=100, source_kind='recorded') -> dict:
    """Create predictions, unannotated GT template, masks, and PNG previews.

    ``source_kind='synthetic'`` is required for artificial fixtures/replay clocks;
    real retained native observations use the default ``recorded``. Unknown score
    floor and detection cap stay null. Source recording payloads are not reread;
    selected ledger assets and their matching recording manifest records are
    verified. The ledger must be closed and checkpointed. The output never
    asserts raw recording completeness or GT quality. ``scene_id`` is a caller
    supplied scope label, not verified semantic ground truth.
    """
    if type(max_frames) is not int or not 1 <= max_frames <= 1000:
        raise ValueError('max_frames must be an integer from 1 to 1000')
    if not isinstance(scene_id, str) or not scene_id.strip():
        raise ValueError('scene_id must be nonempty')
    if source_kind not in ('recorded', 'synthetic'):
        raise ValueError('source_kind must be recorded or synthetic')
    root, output = Path(ledger_root).resolve(), Path(out).absolute()
    if output.resolve().is_relative_to(root):
        raise ValueError('output must be outside the source ledger')
    if output.is_symlink() or output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError('export output must be absent or an empty directory')
    recording_raw, taxonomy_raw = _read(recording_manifest), _read(taxonomy_path)
    recording, records = _recording(recording_raw)
    taxonomy_data = _json(taxonomy_raw)
    if not isinstance(taxonomy_data, dict) or taxonomy_data.pop('schema_version', None) != 1:
        raise ValueError('invalid taxonomy schema')
    taxonomy = Taxonomy(**taxonomy_data)
    with _snapshot_connection(root) as connection:
        if connection.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('unsupported ledger schema')
        config_raw, checkpoint_raw = _metadata(connection,'config'), _metadata(connection,'checkpoint')
        config, checkpoint = _json(config_raw), _json(checkpoint_raw)
        if checkpoint.get('schema_version') != 1:
            raise ValueError('unsupported checkpoint schema')
        snapshot = loads(checkpoint['snapshot'])
        if not isinstance(snapshot, ObjectSnapshot) or snapshot.episode_id != config['episode_id']:
            raise ValueError('checkpoint episode/type mismatch')
        if recording.get('episode_id') != config['episode_id']:
            raise ValueError('recording episode mismatch')
        if taxonomy.vocabulary_id != config['vocabulary_id']:
            raise ValueError('taxonomy vocabulary mismatch')
        if config['clock_domain'].startswith('replay:') and source_kind != 'synthetic':
            raise ValueError('replay fixture requires explicit synthetic provenance')
        count = connection.execute('SELECT count(*) FROM batches').fetchone()[0]
        rows = connection.execute(
            'SELECT * FROM batches ORDER BY json_extract(data, \'$.source.frame_index\'),batch_key LIMIT ?',
            (max_frames,)).fetchall()
        if any(len(row['data']) > _MAX_BYTES for row in rows):
            raise ValueError('oversized committed batch metadata')
        logical_digest = _sha(_canonical(dict(config=config_raw, checkpoint=checkpoint_raw,
                                      batches=[dict(row) for row in rows])).encode())
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='quality-export-',dir=output.parent) as temporary:
            stage = Path(temporary)
            (stage/'masks').mkdir(); (stage/'previews').mkdir()
            frames, metadata, identities = _export_rows(connection,root,stage,config,snapshot,rows,records)
            binding = dict(scene_id=scene_id,episode_id=config['episode_id'],
                recording_sha256=_sha(recording_raw), taxonomy_sha256=_sha(taxonomy_raw),
                coordinate_convention='canonical_z_up_m_v1')
            provenance = dict(kind=source_kind,
                description='Read-only first source-ordered committed batches; final canonical ledger identities; GT annotation required.',
                ledger_logical_sha256=logical_digest,source_metadata=metadata,
                selection=dict(policy='first_committed_batches_in_source_order',limit=max_frames,
                               total_committed_batches=count, selected_batches=len(frames)),
                final_snapshot_revision=snapshot.revision,
                scene_id_verified=False,
                recording_payloads_verified=False,
                recording_certificate=recording.get('certificate'))
            common = dict(schema_version=1,binding=binding,provenance=provenance)
            predictions = dict(common,identity_semantics='final_canonical_only',score_floor=None,
                max_detections=None,final_aliases=dict(snapshot.aliases),frames=frames)
            gt_frames = [dict({key:value for key,value in frame.items() if key not in ('objects','status')},
                              annotated=False,objects=[]) for frame in frames]
            ground_truth = dict(common, frames=gt_frames)
            for name, value in [('predictions.json',predictions),('ground-truth-template.json',ground_truth)]:
                raw = (_canonical(value)+'\n').encode()
                if len(raw) > _MAX_BYTES:
                    raise ValueError('export JSON exceeds 64 MiB')
                (stage/name).write_bytes(raw)
            files = {str(path.relative_to(stage)):_sha(path.read_bytes())
                     for path in sorted(stage.rglob('*')) if path.is_file()}
            export_manifest = dict(schema_version=1,ledger_root=str(root),
                recording_manifest=str(Path(recording_manifest).resolve()),
                taxonomy_path=str(Path(taxonomy_path).resolve()),binding=binding,
                ledger_logical_sha256=logical_digest,files=files,frames=len(frames),
                detections=sum(len(frame['objects']) for frame in frames),identity_observations=identities,
                total_committed_batches=count,gt_annotated=False)
            (stage/'export-manifest.json').write_text(_canonical(export_manifest)+'\n')
            if output.exists() and any(output.iterdir()):
                raise FileExistsError('export output changed during preparation')
            output.mkdir(exist_ok=True)
            for path in stage.iterdir():
                path.rename(output/path.name)
        return dict(predictions=str(output/'predictions.json'),
            ground_truth_template=str(output/'ground-truth-template.json'),previews=str(output/'previews'),
            export_manifest=str(output/'export-manifest.json'), frames=len(frames),
            detections=sum(len(frame['objects']) for frame in frames),identity_observations=identities,
            total_committed_batches=count)
