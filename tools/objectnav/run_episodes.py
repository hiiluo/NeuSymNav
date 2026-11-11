#!/usr/bin/env python3
"""Run ObjectNav episodes with the deterministic lockstep runner.

Run with the project venv (host side); the Habitat worker is started with the
Habitat interpreter through the simulated-clock entry:

    PYTHONPATH=src .venv/bin/python tools/objectnav/run_episodes.py \
        --set hm3d_v2 --split val_mini --limit 2 --run-id smoke1 \
        --out-dir runs/objectnav/smoke1

Writes <out-dir>/trajectories.jsonl (resumable: finished episodes are skipped)
and <out-dir>/run.json (inputs). Score with tools/objectnav/score_trajectories.py.
Phase 1 only has the validation policy ``explore`` (frontier exploration, STOP
after a cycle budget); it is not an ObjectNav agent.
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
from neusymnav.objectnav.runner import ExplorePolicy, LockstepRunner, RunnerConfig  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--set', required=True, dest='episode_set')
    ap.add_argument('--split', required=True)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--out-dir', required=True, type=Path)
    ap.add_argument('--config', type=Path, default=ROOT / 'configs/objectnav/lockstep-b0.json')
    ap.add_argument('--policy', choices=('explore',), default='explore')
    ap.add_argument('--stop-after-cycles', type=int, default=400)
    ap.add_argument('--scenes', nargs='*')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--manifest', type=Path, help='frozen episode list (uids)')
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--habitat-python', type=Path, default=Path.home() / 'miniconda3/envs/habitat/bin/python')
    a = ap.parse_args(argv)
    episodes = load_episode_set(a.episode_set, a.split, a.habitat_data, scenes=a.scenes)
    episodes = read_manifest(a.manifest, episodes) if a.manifest else select(episodes, limit=a.limit)
    config = RunnerConfig.load(a.config)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    except OSError:
        commit, dirty = None, None
    run_info = dict(schema_version=1, run_id=a.run_id, episode_set=a.episode_set, split=a.split,
                    episodes=[e.uid for e in episodes], policy=a.policy, stop_after_cycles=a.stop_after_cycles,
                    config=str(a.config), config_sha256=hashlib.sha256(a.config.read_bytes()).hexdigest(),
                    git_commit=commit, git_dirty=dirty, habitat_python=str(a.habitat_python))
    info_path = a.out_dir / 'run.json'
    if info_path.exists():
        previous = json.loads(info_path.read_text())
        same = {k: previous.get(k) for k in ('run_id', 'config_sha256', 'policy', 'stop_after_cycles')}
        if same != {k: run_info[k] for k in same}:
            raise SystemExit('out-dir holds a different run (%s); use a new --out-dir' % info_path)
    else:
        info_path.write_text(json.dumps(run_info, indent=2) + '\n')
    runner = LockstepRunner(config, habitat_python=a.habitat_python, out_dir=a.out_dir, run_id=a.run_id,
                            policy_factory=lambda: ExplorePolicy(stop_after_cycles=a.stop_after_cycles),
                            log=lambda msg: print(msg, flush=True))
    out = runner.run(episodes)
    print('trajectories:', out)


if __name__ == '__main__':
    main()
