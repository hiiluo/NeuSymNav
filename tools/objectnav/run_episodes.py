#!/usr/bin/env python3
"""Run ObjectNav episodes with the deterministic lockstep runner.

Run with the project venv (host side); the Habitat worker is started with the
Habitat interpreter through the simulated-clock entry:

    PYTHONPATH=src .venv/bin/python tools/objectnav/run_episodes.py \
        --set hm3d_v2 --split val_mini --limit 2 --run-id smoke1 \
        --out-dir runs/objectnav/smoke1

Writes <out-dir>/trajectories.jsonl (resumable: finished episodes are skipped)
and <out-dir>/run.json (inputs). Score with tools/objectnav/score_trajectories.py.
Policies: ``explore`` (phase-1 validation: frontier exploration, STOP after a
cycle budget; not an ObjectNav agent) and ``b0`` (phase 3: the non-privileged
ObjectNav baseline, configured by --b0-config; its simulated time budget
replaces the runner's max_sim_s, and per-episode detection evidence goes to
<out-dir>/evidence/ for the offline failure analysis).
"""
import argparse
import fcntl
import hashlib
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav.b0.trace import lock_run  # noqa: E402
from neusymnav.objectnav.run_lock import build_lock, file_pin, interpreter_pin  # noqa: E402
from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, read_manifest, select  # noqa: E402
from neusymnav.objectnav.runner import ExplorePolicy, LockstepRunner, RunnerConfig  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--set', required=True, dest='episode_set')
    ap.add_argument('--split', required=True)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--out-dir', required=True, type=Path)
    ap.add_argument('--config', type=Path)
    ap.add_argument('--policy', choices=('explore', 'b0'), default='explore')
    ap.add_argument('--b0-config', type=Path)
    ap.add_argument('--stop-after-cycles', type=int, default=400)
    ap.add_argument('--scenes', nargs='*')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--manifest', type=Path, help='frozen episode list (uids)')
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    ap.add_argument('--habitat-python', type=Path, default=Path.home() / 'miniconda3/envs/habitat/bin/python')
    ap.add_argument('--trace', action='store_true', help='write bounded per-episode decision traces')
    ap.add_argument('--semantic-candidate-mode', choices=('off', 'shadow', 'probabilistic'), default='off')
    ap.add_argument('--semantic-native-config', type=Path)
    ap.add_argument('--semantic-native-python', type=Path, default=ROOT / '.runtime/hydra_ws/.venv/bin/python')
    a = ap.parse_args(argv)
    if a.semantic_candidate_mode != 'off' and (a.policy != 'b0' or not a.trace or a.semantic_native_config is None):
        ap.error('semantic candidates require B0, --trace and --semantic-native-config')
    if a.semantic_candidate_mode == 'off' and a.semantic_native_config is not None:
        ap.error('--semantic-native-config requires a semantic candidate mode')
    a.habitat_python = a.habitat_python.absolute()
    if a.b0_config is None:
        a.b0_config = ROOT / 'configs/objectnav/b0-policy-v1.json'
    if a.config is None:
        a.config = ROOT / 'configs/objectnav/lockstep-b0.json'
    episodes = load_episode_set(a.episode_set, a.split, a.habitat_data, scenes=a.scenes)
    episodes = read_manifest(a.manifest, episodes) if a.manifest else select(episodes, limit=a.limit)
    config = RunnerConfig.load(a.config)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    policy_factory = lambda: ExplorePolicy(stop_after_cycles=a.stop_after_cycles)
    b0_sha = None
    b0 = None
    semantic_pins = None
    if a.policy == 'b0':
        from neusymnav.objectnav.b0.policy import B0Config, B0Policy
        from neusymnav.objectnav.b0.detection import client_factory
        from neusymnav.objectnav.detector_eval.categories import GoalCategories
        b0 = B0Config.load(a.b0_config)
        b0_sha = hashlib.sha256(a.b0_config.read_bytes()).hexdigest()
        config = replace(config, max_sim_s=b0.max_sim_s)
        categories = GoalCategories.load(b0.resolve('mapping'))
        profile = b0.resolve('detector_profile')
        make_client = client_factory(profile)
        semantic_options = {}
        if a.semantic_candidate_mode != 'off':
            from neusymnav.contracts.observations import Taxonomy
            from neusymnav.objectnav.b0.detection import recipe_from_profile
            from neusymnav.objectnav.paper.native_tap import PaperHydraOwner, PaperNativeTap, lockstep_primary_mount
            from neusymnav.objectnav.paper.semantic_candidates import SemanticCandidateConfig

            config_root = a.semantic_native_config.resolve()
            native_python = a.semantic_native_python.absolute()
            semantic_pins = dict(
                mode=a.semantic_candidate_mode,
                config=[file_pin(path) for path in sorted(config_root.rglob('*.yaml'))],
                interpreter=interpreter_pin(native_python, module='hydra_python'))
            recipe = recipe_from_profile(profile)['recipe']
            taxonomy = Taxonomy.load(Path(recipe['taxonomy_path']))
            command = (str(native_python), str(ROOT / 'src/neusymnav/backends/hydra/entry.py'))
            mount = lockstep_primary_mount(config.sensor['primary'])
            semantic_options = dict(
                semantic_candidates=SemanticCandidateConfig(mode=a.semantic_candidate_mode),
                semantic_tap_factory=lambda: PaperNativeTap(lambda: PaperHydraOwner(
                    a.out_dir / 'native-shadow', config_root, command, {taxonomy.vocabulary_id: recipe},
                    fixed_mount=mount)))
        policy_factory = lambda: B0Policy(b0, categories=categories, detector_factory=make_client,
                                          robot_height_m=config.robot['height_m'],
                                          robot_radius_m=config.robot['radius_m'],
                                          robot_margin_m=config.robot['margin_m'],
                                          evidence_dir=a.out_dir / 'evidence', **semantic_options)
    if not episodes or len({episode.uid for episode in episodes}) != len(episodes):
        raise SystemExit('manifest must contain at least one episode and unique episode UIDs')
    try:
        commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip())
    except OSError:
        commit, dirty = None, None
    run_info = dict(schema_version=1, run_id=a.run_id, episode_set=a.episode_set, split=a.split,
                    episodes=[e.uid for e in episodes], policy=a.policy, stop_after_cycles=a.stop_after_cycles,
                    config=str(a.config), config_sha256=hashlib.sha256(a.config.read_bytes()).hexdigest(),
                    b0_config=str(a.b0_config) if b0 is not None else None, b0_config_sha256=b0_sha,
                    max_sim_s=config.max_sim_s,
                    git_commit=commit, git_dirty=dirty, habitat_python=str(a.habitat_python),
                    trace_enabled=a.trace)
    inputs = build_lock(ROOT, a, config, episodes, b0)
    if semantic_pins is not None:
        inputs['semantic_candidates'] = semantic_pins
        run_info['semantic_candidate_mode'] = a.semantic_candidate_mode
    with (a.out_dir / '.run.lock').open('a') as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit('another process holds the run output directory') from exc
        lock_run(a.out_dir, run_info, inputs)
        runner = LockstepRunner(config, habitat_python=a.habitat_python, out_dir=a.out_dir, run_id=a.run_id,
                                policy_factory=policy_factory, trace_enabled=a.trace,
                                log=lambda msg: print(msg, flush=True))
        out = runner.run(episodes)
    print('trajectories:', out)


if __name__ == '__main__':
    main()
