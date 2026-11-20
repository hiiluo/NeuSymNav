#!/usr/bin/env python3
"""Run ObjectNav episodes in paper-protocol mode (docs/objectnav/paper-protocol-plan.md).

    .venv/bin/python tools/objectnav/run_paper_episodes.py --set hm3d_v2 --split val \
        --manifest runs/objectnav/<run>/manifest.json --run-id <run> --out-dir runs/objectnav/<run> \
        --policy explore

Then score with the unchanged scorer (Habitat interpreter):
    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/score_trajectories.py \
        runs/objectnav/<run>/trajectories.jsonl --set hm3d_v2 --split val
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, read_manifest, select  # noqa: E402
from neusymnav.objectnav.paper.protocol import PaperProtocol  # noqa: E402
from neusymnav.objectnav.paper.runner import PaperRunner  # noqa: E402


def _git():
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip())
        return commit, dirty
    except OSError:
        return None, None


def policy_factory(a):
    if a.policy == 'explore':
        from neusymnav.objectnav.paper.policies import FrontierExplorePolicy
        return lambda: FrontierExplorePolicy()
    if a.policy in ('b0', 'b1'):
        from neusymnav.objectnav.paper.b0 import make_policy_factory
        return make_policy_factory(a.policy, a.policy_config, evidence_dir=a.out_dir / 'evidence')
    raise SystemExit('unknown policy ' + a.policy)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--set', required=True, dest='episode_set')
    ap.add_argument('--split', required=True)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--out-dir', required=True, type=Path)
    ap.add_argument('--protocol', type=Path, default=ROOT / 'configs/objectnav/paper-hm3d-v1.json')
    ap.add_argument('--policy', choices=('explore', 'b0', 'b1'), default='explore')
    ap.add_argument('--policy-config', type=Path, help='policy JSON (b0 / b1)')
    ap.add_argument('--manifest', type=Path)
    ap.add_argument('--limit', type=int)
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--habitat-python', type=Path, default=Path.home() / 'miniconda3/envs/habitat/bin/python')
    a = ap.parse_args(argv)
    protocol = PaperProtocol.load(a.protocol)
    episodes = load_episode_set(a.episode_set, a.split, a.habitat_data)
    episodes = read_manifest(a.manifest, episodes) if a.manifest else select(episodes, limit=a.limit)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    commit, dirty = _git()
    run = dict(schema_version=1, run_id=a.run_id, mode='paper', protocol=protocol.protocol_id,
               protocol_sha256=protocol.sha256, policy=a.policy,
               policy_config=str(a.policy_config) if a.policy_config else None,
               policy_config_sha256=hashlib.sha256(a.policy_config.read_bytes()).hexdigest() if a.policy_config else None,
               episode_set=a.episode_set, split=a.split, episodes=len(episodes), git_commit=commit, git_dirty=dirty,
               habitat_python=str(a.habitat_python))
    (a.out_dir / 'run.json').write_text(json.dumps(run, indent=1) + '\n')
    if not (a.out_dir / 'manifest.json').exists():
        (a.out_dir / 'manifest.json').write_text(json.dumps(dict(schema_version=1, uids=[e.uid for e in episodes]), indent=1) + '\n')
    runner = PaperRunner(protocol, out_dir=a.out_dir, run_id=a.run_id, policy_factory=policy_factory(a),
                         habitat_python=a.habitat_python)
    print('trajectories:', runner.run(episodes))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
