#!/usr/bin/env python3
"""Replay the exact RGB-D and detector batches retained by Paper shadow into Hydra."""
import argparse
from hashlib import file_digest, sha256
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

from neusymnav.backends.hydra.runtime import HydraGraphRuntime
from neusymnav.backends.hydra.session import HydraSession
from neusymnav.contracts import HydraCalibration, Taxonomy
from neusymnav.contracts.hydra_graph import OPTICAL_CAMERA
from neusymnav.reasoninggraph.paper_shadow import read_shadow_manifest


RIG_ATOL = 1e-4


def digest(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def body_relative_extrinsics(sensor, body_pose):
    (x, y, z), yaw, _ = body_pose
    cosine, sine = math.cos(yaw), math.sin(yaw)
    world_T_body = np.array(((cosine, -sine, 0., x), (sine, cosine, 0., y),
                             (0., 0., 1., z), (0., 0., 0., 1.)))
    return np.linalg.solve(world_T_body, sensor.T_world_camera)


def verify_recorded_pose(sensor, body, audited):
    row = audited.get(sensor.geometry_hash)
    if row is None:
        raise ValueError('replay RGB-D does not match the Paper action audit')
    expected = row['input_pose']
    expected_body = ((*expected['robot_xy'], expected['z_m']), expected['yaw_rad'], expected['tilt_rad'])
    if body != expected_body:
        raise ValueError('archived body pose does not match the Paper action audit')


def attempt(session, previous_revision, attempts):
    deadline = time.monotonic() + 30.
    while time.monotonic() < deadline:
        revision, failure, *_ = session.state_token()
        if failure:
            raise RuntimeError(f'native replay failed: {failure}')
        if revision == previous_revision + 1:
            return True
        stats = session.stats
        if stats['step_rejected'] + stats['accepted'] == attempts:
            return stats['accepted'] > previous_revision
        time.sleep(.01)
    raise TimeoutError('native Paper replay attempt did not complete')


def replay(args):
    run = args.run.resolve()
    trajectory = run / 'trajectories.jsonl'
    rows = [json.loads(line) for line in trajectory.read_text().splitlines() if line.strip()]
    record, = (row for row in rows if row['uid'] == args.uid)
    policy = record['diagnostics']['policy']
    summary = policy['reasoninggraph_shadow']
    manifest = Path(summary['manifest']).resolve()
    if not summary['complete'] or not manifest.is_relative_to(run):
        raise ValueError('incomplete or foreign Paper shadow manifest')
    audit = record['diagnostics']['action_audit']
    audited_frames = list(audit['steps'])
    if 'terminal_observation' in audit:
        audited_frames.append(audit['terminal_observation'])
    pinned_sources = {row['input_source']['geometry_sha256']: row for row in audited_frames
                      if row['input_source'] is not None}
    recorded = iter(read_shadow_manifest(manifest.parent))
    first = next(recorded, None)
    if first is None:
        raise ValueError('Paper shadow retained no fixed-rig observations')
    obs, _, pose = first
    verify_recorded_pose(obs, pose, pinned_sources)
    mount = body_relative_extrinsics(obs, pose)
    calibration = HydraCalibration(obs.calibration_id, 'paper-fixed-rig-v1', obs.key.sensor_id,
        'paper-rgbd', obs.K, mount, obs.pose_version, obs.coordinate_convention,
        OPTICAL_CAMERA, obs.depth_convention, 'Paper measured body pose and camera extrinsics from frozen shadow sample')

    lock = run / 'baseline-lock.json'
    inputs = json.loads(lock.read_bytes())['inputs']
    detector = inputs['detector']
    launch = detector.get('plant_launch') if policy['target'] == 'plant' else None
    recipe = (launch or detector['launch'])['recipe']
    taxonomy_path = Path(recipe['taxonomy_path'])
    if digest(taxonomy_path) != recipe['taxonomy_sha256']:
        raise ValueError('Paper detector taxonomy differs from the locked recipe')
    taxonomy = Taxonomy.load(taxonomy_path)
    recipe_sha = sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    profile = 'paper-shadow-' + recipe_sha + '@sha256:' + recipe['checkpoint_sha256']

    args.out.mkdir(parents=True, exist_ok=False)
    command = (sys.executable, 'src/neusymnav/backends/hydra/entry.py',
               '--config-root', str(args.config_root), '--artifact-dir', str(args.out / 'native'))
    session = HydraSession(obs.key.episode_id, command=command, journal_path=args.out / 'journal.jsonl')
    runtime = HydraGraphRuntime(session, calibration=calibration, taxonomy=taxonomy, detector_profile_id=profile)
    revisions, rejected_frames = [], []
    sampled_frames = 0
    max_mount_error = 0.
    try:
        from itertools import chain

        for sensor, batch, body in chain((first,), recorded):
            verify_recorded_pose(sensor, body, pinned_sources)
            sampled_frames += 1
            if (body[2] != pose[2] or sensor.calibration_id != obs.calibration_id
                    or sensor.clock_domain != obs.clock_domain):
                raise ValueError('fixed-rig source or tilt changed in the replay archive')
            error = float(np.max(np.abs(body_relative_extrinsics(sensor, body) - mount)))
            if error > RIG_ATOL:
                raise ValueError('body-to-camera mount changed despite the fixed-rig metadata')
            max_mount_error = max(error, max_mount_error)
            revision = len(revisions) + 1
            if runtime.offer(sensor, batch).status != 'queued':
                raise RuntimeError(f'Hydra did not queue archived Paper frame {sensor.key.frame_index}')
            if not attempt(session, revision - 1, sampled_frames):
                rejected_frames.append(sensor.key.frame_index)
                continue
            view = runtime.reasoninggraph_snapshot()
            if view is None or view[0].source_geometry_hash != sensor.geometry_hash:
                raise RuntimeError('published native revision does not match the archived frame')
            token, objects = view
            revisions.append(dict(revision=revision, source_frame=token.source.frame_index,
                                  prefix=token.native.input_prefix_sha256, objects=len(objects),
                                  capture_sha256=token.source_geometry_hash, mount_error=error,
                                  build_sha256=token.native.build_sha256,
                                  config_sha256=token.native.config_sha256,
                                  calibration_hash=token.calibration_hash))
    finally:
        shutdown = runtime.close(5)
    if (not shutdown['complete'] or shutdown['returncode'] != 0 or not revisions
            or sampled_frames != summary['written'] or len(revisions) + len(rejected_frames) != sampled_frames):
        raise RuntimeError('incomplete fixed-rig native replay')
    report = dict(uid=args.uid, trajectory_sha256=digest(trajectory), run_lock_sha256=digest(lock),
                  manifest_sha256=digest(manifest), recipe_sha256=recipe_sha,
                  frames=sampled_frames, accepted=len(revisions), step_rejected_frames=rejected_frames,
                  mount_tolerance=RIG_ATOL,
                  max_mount_error=max_mount_error,
                  graph_revisions=revisions)
    (args.out / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'graph_revisions'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run', 'config-root', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--uid', required=True)
    replay(parser.parse_args())


if __name__ == '__main__':
    main()
