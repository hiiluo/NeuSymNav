#!/usr/bin/env python3
"""Re-detect sealed RGB-D frames and probe revision-scoped links in native Hydra."""
import argparse
from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))

from neusymnav.backends.hydra.runtime import HydraGraphRuntime
from neusymnav.backends.hydra.session import HydraSession
from neusymnav.contracts import Taxonomy
from neusymnav.contracts.hydra_evidence import ObservationEvidence
from neusymnav.contracts.hydra_graph import HydraCalibration
from neusymnav.contracts.reasoninggraph import DetectionGeometry
from neusymnav.perception.detector_client import DetectorClient, RECIPE_CONFIG_ASSETS
from neusymnav.perception.projector import Projector
from neusymnav.reasoninggraph.evidence import link_frame
from neusymnav.reasoninggraph.store import RevisionStore
from neusymnav.recording.replay import ReplayReader
from neusymnav.runtime.launcher import _checked
from tools.probe_hydra_detail import selected_prefix


def sha(data):
    return hashlib.sha256(data).hexdigest()


def geometry(observation, detection, projected, token, pose_version, detector_hash, root):
    y, x = np.nonzero(detection.mask)
    x0, y0, x1, y1 = map(int, (x.min(), y.min(), x.max()+1, y.max()+1))
    pixels = np.s_[y0:y1, x0:x1]
    rgb, mask, depth = observation.rgb[pixels], detection.mask[pixels], observation.depth_m[pixels]
    name = 'evidence/' + sha(repr((observation.key, detection.detection_id)).encode()) + '.npz'
    np.savez_compressed(root/name, rgb=rgb, mask=mask, depth_m=depth,
                        valid=observation.valid_depth[pixels])
    ref = ObservationEvidence(token.source, token.capture_monotonic_ns, token.clock_domain,
        detection.detection_id, name, sha(rgb.tobytes()), sha(mask.tobytes()), sha(depth.tobytes()),
        (x0, y0, x1, y1), token.calibration_id, token.calibration_hash, pose_version,
        token.detector_profile_id, detector_hash, token.vocabulary_id, token.native.input_prefix_sha256,
        'rgbd_aabb_overlap_v1', 'unavailable')
    points = projected.points_world
    return DetectionGeometry(ref, detection.category, observation.geometry_hash,
                             (points.min(axis=0), points.max(axis=0)), token.labelspace_hash)


def probe(args):
    cfg, assets = _checked(args.config)
    data = cfg.data
    frames = selected_prefix(args.journal, args.frames)
    first = frames[0][0]
    parent = args.out
    (parent/'evidence').mkdir(parents=True, exist_ok=False)
    (parent/'sidecars').mkdir()
    command = (sys.executable, str(ROOT/'src/neusymnav/backends/hydra/entry.py'),
        '--config-root', data['scene_graph']['hydra']['config_root'],
        '--artifact-dir', str(parent/'native'))
    recipe = {k: v for k, v in data['detector'].items() if k not in RECIPE_CONFIG_ASSETS}
    for name in ('checkpoint', 'encoder', 'taxonomy'):
        recipe[name+'_path'] = str(assets[name])
        recipe[name+'_sha256'] = data['detector'][name]['sha256']
    python, script = assets['detector']
    detector = DetectorClient(python=python, worker_script=script, recipe=recipe,
                              timeout_s=8.0, startup_timeout_s=60.)
    calibration = HydraCalibration(first.calibration_id, first.calibration_version,
        first.source_key.sensor_id, 'replay_rgbd', first.K, first.body_T_camera, first.pose_version,
        first.coordinate_convention, first.camera_convention, first.depth_convention, 'M1 sealed RGB-D replay')
    session = HydraSession(first.source_key.episode_id, command=command, journal_path=parent/'journal.jsonl')
    runtime = HydraGraphRuntime(session, calibration=calibration, taxonomy=Taxonomy.load(assets['taxonomy']),
                                detector_profile_id=first.detector_profile_id)
    reader = ReplayReader(args.recording)
    source_frames = zip(reader.source_frames(), reader.frames())
    projector, store, records = Projector(), RevisionStore(session.has_detail_token), []
    try:
        for revision, (frame, prefix) in enumerate(frames, 1):
            observation, replay = next(pair for pair in source_frames if pair[0].key == frame.source_key)
            assert replay.key == observation.key
            assert (observation.geometry_hash, observation.capture_monotonic_ns, observation.clock_domain) == (
                frame.source_geometry_hash, frame.capture_monotonic_ns, frame.clock_domain)
            assert session.offer(frame).status == 'queued'
            assert session.wait_for_revision(revision, 30.)
            result = runtime.reasoninggraph_snapshot()
            assert result is not None
            token, endpoints = result
            assert token.source == observation.key and token.native.input_prefix_sha256 == prefix
            # Re-detection is an offline operation. Keep the recorded clock on
            # the Hydra frame and evidence, and use the private clock for IPC.
            batch = detector.infer(replay)
            raster = runtime.rasterizer.rasterize(replay, batch)
            exact = np.array_equal(raster.labels, frame.labels)
            evidence = []
            if exact:
                detections = {d.detection_id: d for d in batch.detections if d.category is not None}
                for projected in projector.project(replay, batch):
                    detection = detections.get(projected.detection_id)
                    if detection is not None:
                        evidence.append(geometry(observation, detection, projected, token,
                                                 frame.pose_version, recipe['checkpoint_sha256'], parent))
            links = link_frame(evidence, endpoints, token)
            assert store.publish(token, links)
            view = store.read(token)
            assert view is not None
            manifest = parent/'sidecars'/f'revision-{revision:06d}.json'
            manifest_sha256 = store.seal(manifest, token)
            restored = RevisionStore(session.has_detail_token)
            assert restored.restore(manifest, token, manifest_sha256)
            assert restored.read(token) == view
            records.append(dict(revision=revision, exact_class_raster=bool(exact),
                re_detection_capture_monotonic_ns=replay.capture_monotonic_ns,
                detector_instances=len(batch.detections), native_objects=len(endpoints),
                native_endpoints=[item.ref.native_id for item in endpoints],
                native_geometry=[dict(native_id=item.ref.native_id, category=item.category, bounds=item.bounds)
                                 for item in endpoints],
                manifest=str(manifest.relative_to(parent)), manifest_sha256=manifest_sha256,
                token=asdict(token), evidence=[asdict(item) for item in evidence],
                links=[asdict(link) for link in links]))
    finally:
        detector.close(3.)
        closed = runtime.close(10.)
    assert closed['complete'] and closed['returncode'] == 0, closed
    counts = Counter(link['status'] for row in records for link in row['links'])
    report = dict(schema_version=1, accepted_prefixes=len(records),
                  exact_class_rasters=sum(row['exact_class_raster'] for row in records),
                  candidate_links=dict(counts), records=records,
                  re_detection_clock_domain=reader.clock_domain,
                  annotated_ground_truth=False, native_lifecycle_proof=False)
    (parent/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='records'}))
    return 0 if report['exact_class_rasters'] and counts['geometric_candidate'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'journal', 'recording', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--frames', type=int, default=12, choices=range(1, 65), metavar='1..64')
    return probe(parser.parse_args())


if __name__ == '__main__':
    raise SystemExit(main())
