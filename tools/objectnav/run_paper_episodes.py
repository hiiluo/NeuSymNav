#!/usr/bin/env python3
"""Run the discrete ObjectNav paper protocol on the bundled Habitat navmeshes."""
import argparse
import fcntl
import json
import re
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.evaluation.objectnav_metrics import SUCCESS_DISTANCE_M  # noqa: E402
from neusymnav.objectnav.b0.trace import lock_run  # noqa: E402
from neusymnav.objectnav.episodes import load_episode_set, read_manifest, select  # noqa: E402
from neusymnav.objectnav.paper.protocol import PaperProtocol  # noqa: E402
from neusymnav.objectnav.paper.runner import PaperRunner  # noqa: E402
from neusymnav.objectnav.run_lock import dataset_pin, file_pin, interpreter_pin, source_pin  # noqa: E402
from neusymnav.recording.replay import _write_atomic  # noqa: E402

CONFIG = ROOT / 'configs/objectnav'
NATIVE_LOCK = ROOT / 'runs/objectnav/.hierarchical-native.lock'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--set', default='hm3d_v2', dest='episode_set')
    ap.add_argument('--split', default='val')
    ap.add_argument('--run-id')
    ap.add_argument('--out-dir', type=Path)
    ap.add_argument('--protocol', type=Path, default=CONFIG / 'paper-hm3d-v1.json')
    ap.add_argument('--policy', choices=('explore', 'b0'), default='b0')
    ap.add_argument('--policy-config', type=Path, help='override the Paper B0 config (default: paper-b0-v2.json)')
    ap.add_argument('--detector-profile', type=Path)
    subset = ap.add_mutually_exclusive_group()
    subset.add_argument('--manifest', type=Path)
    subset.add_argument('--limit', type=int)
    ap.add_argument('--habitat-data', type=Path, default=ROOT / 'local-assets/datasets/hm3d-val')
    ap.add_argument('--habitat-python', type=Path, default=ROOT / '.runtime/sensor/bin/python')
    ap.add_argument('--preflight', action='store_true', help='validate inputs and print the resolved setup')
    ap.add_argument('--action-audit', action='store_true',
                    help='record ordered simulator dispatch, source pins and pose for parity analysis')
    ap.add_argument('--reasoninggraph-mode', choices=('off', 'shadow'), default='off',
                    help='retain bounded fixed-rig detector inputs for offline ReasoningGraph replay')
    a = ap.parse_args(argv)
    if not a.preflight and (not a.out_dir or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', a.run_id or '')):
        ap.error('run requires --out-dir and --run-id (1–64 letters, digits, dot, underscore or hyphen)')
    if a.limit is not None and a.limit < 1:
        ap.error('--limit must be positive')
    if a.policy == 'explore' and (a.policy_config or a.detector_profile):
        ap.error('--policy-config and --detector-profile require --policy b0')
    if a.policy == 'explore' and a.reasoninggraph_mode == 'shadow':
        ap.error('ReasoningGraph shadow requires a Paper detector policy')
    if a.reasoninggraph_mode == 'shadow':
        a.action_audit = True
    protocol = PaperProtocol.load(a.protocol)
    if protocol.success_distance_m != SUCCESS_DISTANCE_M:
        ap.error(f'current offline scorer requires success_distance_m={SUCCESS_DISTANCE_M}')
    a.habitat_data = a.habitat_data.absolute()
    a.habitat_python = a.habitat_python.absolute()  # retain the virtual environment symlink
    all_episodes = load_episode_set(a.episode_set, a.split, a.habitat_data)
    episodes = read_manifest(a.manifest, all_episodes) if a.manifest else select(all_episodes, limit=a.limit)
    uids = [episode.uid for episode in episodes]
    if not uids or len(uids) != len(set(uids)):
        ap.error('episode selection must be nonempty with unique UIDs')
    for scene in {episode.scene_path for episode in episodes}:
        if not Path(scene).with_suffix('.navmesh').is_file():
            ap.error(f'bundled navmesh is missing for {scene}')
    habitat = interpreter_pin(a.habitat_python, module='habitat_sim')
    detector = None
    if a.policy == 'explore':
        from neusymnav.objectnav.paper.policies import FrontierExplorePolicy

        policy_factory = FrontierExplorePolicy
    else:
        from neusymnav.objectnav.b0.detection import recipe_from_profile, with_taxonomy
        from neusymnav.objectnav.paper.b0 import PaperB0Config, make_policy_factory

        a.policy_config = a.policy_config or CONFIG / 'paper-b0-v2.json'
        cfg = PaperB0Config.load(a.policy_config)
        if a.detector_profile:
            cfg = replace(cfg, detector_profile=str(a.detector_profile.absolute()))
        profile = cfg.resolve('detector_profile')
        evidence_dir = a.out_dir / 'evidence' if a.out_dir and not a.preflight else None
        base_launch = recipe_from_profile(profile)
        plant_launch = with_taxonomy(base_launch, cfg.resolve('plant_taxonomy')) if cfg.plant_taxonomy else None
        detector = {
            'profile': file_pin(profile), 'launch': base_launch,
            'rule': file_pin(cfg.resolve('detection_rule')), 'mapping': file_pin(cfg.resolve('mapping')),
        }
        if plant_launch is not None:
            detector['plant_launch'] = plant_launch
        factory_options = dict(evidence_dir=evidence_dir, base_launch=base_launch, plant_launch=plant_launch)
        if a.reasoninggraph_mode == 'shadow' and not a.preflight:
            factory_options['shadow_root'] = a.out_dir / 'reasoninggraph-shadow'
        policy_factory = make_policy_factory(cfg, **factory_options)
    run = dict(schema_version=1, run_id=a.run_id, mode='paper', protocol=protocol.protocol_id,
               protocol_sha256=protocol.sha256, policy=a.policy,
               episode_set=a.episode_set, split=a.split, episodes=len(uids),
               scenes=len({episode.scene_short for episode in episodes}),
               split_episodes=len(all_episodes), split_scenes=len({episode.scene_short for episode in all_episodes}),
               habitat_data=str(a.habitat_data), habitat_python=str(a.habitat_python),
               detector_backend=detector['launch']['recipe'].get('backend', 'torch') if detector else None)
    if detector is not None and 'plant_launch' in detector:
        run['plant_taxonomy_sha256'] = detector['plant_launch']['recipe']['taxonomy_sha256']
    if a.action_audit:
        run['action_audit'] = True
    if a.reasoninggraph_mode == 'shadow':
        run['reasoninggraph_mode'] = 'shadow'
    if a.preflight:
        print(json.dumps({**run, 'settings': protocol.worker_config(),
                          'success_distance_m': protocol.success_distance_m}, indent=2))
        return 0

    inputs = dict(source=source_pin(ROOT), habitat=habitat, host=interpreter_pin(Path(sys.executable)),
                  dataset=dataset_pin(a.habitat_data, a.episode_set, a.split, episodes),
                  protocol=file_pin(a.protocol), detector=detector, uids=uids,
                  policy_config=file_pin(a.policy_config) if a.policy_config else None)
    NATIVE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with NATIVE_LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            ap.error('another ObjectNav native workload holds the benchmark lock')
        a.out_dir.mkdir(parents=True, exist_ok=True)
        manifest = dict(schema_version=1, uids=uids)
        path = a.out_dir / 'manifest.json'
        if path.exists() and json.loads(path.read_text()) != manifest:
            ap.error('output manifest differs from the selected episodes')
        lock_run(a.out_dir, run, inputs)
        if not path.exists():
            _write_atomic(path, (json.dumps(manifest, indent=2) + '\n').encode())
        runner = PaperRunner(protocol, out_dir=a.out_dir, run_id=a.run_id, policy_factory=policy_factory,
                             habitat_python=a.habitat_python, action_audit=a.action_audit)
        print('trajectories:', runner.run(episodes))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
