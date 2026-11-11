#!/usr/bin/env python3
"""Freeze the ObjectNav dev/test split as episode manifests (run once, commit the output).

    PYTHONPATH=src .venv/bin/python tools/objectnav/make_split.py --set hm3d_v2 --split val \
        --dev-scenes TEEsavR23oF wcojb4TFT35 --extra-dev-scenes 4 --seed 20261111 \
        --dev-per-scene 10 --test-per-scene 6 --out-dir configs/objectnav/splits

Dev scenes are for tuning; test scenes are only for reporting and never used to
choose parameters. Writes <set>-<split>-dev.json / -test.json (uids) and a
README-style summary json with the scene lists and the seed.
"""
import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav.episodes import DEFAULT_HABITAT_DATA, load_episode_set, select, write_manifest  # noqa: E402


def make_split(episodes, *, dev_scenes, extra_dev_scenes, seed, dev_per_scene, test_per_scene):
    scenes = sorted({e.scene_short for e in episodes})
    unknown = sorted(set(dev_scenes) - set(scenes))
    if unknown:
        raise ValueError('dev scenes not in the episode set: %s' % unknown)
    pool = [s for s in scenes if s not in dev_scenes]
    extra = sorted(random.Random(seed).sample(pool, extra_dev_scenes)) if extra_dev_scenes else []
    dev_set = sorted(set(dev_scenes) | set(extra))
    test_set = [s for s in scenes if s not in dev_set]
    dev = select([e for e in episodes if e.scene_short in dev_set], per_scene=dev_per_scene, seed=seed)
    test = select([e for e in episodes if e.scene_short in test_set], per_scene=test_per_scene, seed=seed + 1)
    dev.sort(key=lambda e: e.uid)
    test.sort(key=lambda e: e.uid)
    return dev, test, dev_set, test_set


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--set', required=True, dest='episode_set')
    ap.add_argument('--split', required=True)
    ap.add_argument('--dev-scenes', nargs='+', required=True)
    ap.add_argument('--extra-dev-scenes', type=int, default=4)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--dev-per-scene', type=int, default=10)
    ap.add_argument('--test-per-scene', type=int, default=6)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--habitat-data', type=Path, default=DEFAULT_HABITAT_DATA)
    a = ap.parse_args(argv)
    episodes = load_episode_set(a.episode_set, a.split, a.habitat_data)
    dev, test, dev_set, test_set = make_split(episodes, dev_scenes=a.dev_scenes, extra_dev_scenes=a.extra_dev_scenes,
                                              seed=a.seed, dev_per_scene=a.dev_per_scene,
                                              test_per_scene=a.test_per_scene)
    a.out_dir.mkdir(parents=True, exist_ok=True)
    stem = '%s-%s' % (a.episode_set, a.split)
    paths = [a.out_dir / (stem + '-dev.json'), a.out_dir / (stem + '-test.json'), a.out_dir / (stem + '-split.json')]
    for path in paths:
        if path.exists():
            raise SystemExit('refusing to overwrite frozen split %s' % path)
    write_manifest(dev, paths[0])
    write_manifest(test, paths[1])
    summary = dict(schema_version=1, episode_set=a.episode_set, split=a.split, seed=a.seed,
                   dev_scenes=dev_set, test_scenes=test_set, dev_episodes=len(dev), test_episodes=len(test),
                   dev_per_scene=a.dev_per_scene, test_per_scene=a.test_per_scene,
                   dev_categories=dict(Counter(e.object_category for e in dev)),
                   test_categories=dict(Counter(e.object_category for e in test)))
    paths[2].write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
