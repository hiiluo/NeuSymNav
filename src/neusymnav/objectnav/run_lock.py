"""Preflight identity for deterministic ObjectNav runs."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from .episodes import EPISODE_SETS


def file_pin(path: Path) -> dict:
    with path.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'path': str(path.absolute()), 'sha256': sha}


def source_pin(root: Path) -> dict:
    files = [
        path for base in (root / 'src/neusymnav', root / 'tools/objectnav')
        for path in base.rglob('*.py') if path.is_file()
    ]
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(str(path.relative_to(root)).encode() + b'\0')
        digest.update(bytes.fromhex(file_pin(path)['sha256']))
    return {'tree_sha256': digest.hexdigest(),
            'scorer': file_pin(root / 'tools/objectnav/score_trajectories.py')}


def dataset_pin(root: Path, episode_set: str, split: str, episodes) -> dict:
    dataset, version = EPISODE_SETS[episode_set]
    split_root = root / 'datasets/objectnav' / dataset / version / split
    paths = {split_root / f'{split}.json.gz'}
    for episode in episodes:
        scene = Path(episode.scene_path)
        paths.add(scene)
        paths.add(scene.with_suffix('.navmesh'))
        for cfg in (episode.runtime_dataset_config, episode.eval_dataset_config):
            if cfg:
                paths.add(Path(cfg))
        content = split_root / 'content' / f'{episode.scene_short}.json.gz'
        if content.is_file():
            paths.add(content)
        # Evaluator-only assets are recorded when available.
        stem = scene.name.removesuffix('.basis.glb')
        for suffix in ('.semantic.glb', '.semantic.txt'):
            semantic = scene.with_name(stem + suffix)
            if semantic.is_file():
                paths.add(semantic)
    return {'root': str(root.absolute()), 'files': [file_pin(path) for path in sorted(paths)]}


def interpreter_pin(path: Path, *, module: str | None = None) -> dict:
    result = file_pin(path)
    code = ('import json, sys, importlib.util; '
            f'spec=importlib.util.find_spec({module!r}) if {module!r} else None; '
            'print(json.dumps(dict(python=sys.version, prefix=sys.prefix, '
            'module_path=spec.origin if spec else None)))')
    metadata = json.loads(subprocess.check_output([str(path.absolute()), '-c', code], text=True, timeout=15))
    if module and not metadata['module_path']:
        raise ValueError(f'{module} is missing from {path}')
    module_path = metadata['module_path']
    if module_path and Path(module_path).is_file():
        metadata['module_pin'] = file_pin(Path(module_path))
    return {**result, **metadata}


def build_lock(root: Path, args, config, episodes, b0=None) -> dict:
    detector = None
    if b0:
        from .b0.detection import recipe_from_profile

        profile = b0.resolve('detector_profile')
        launch = recipe_from_profile(profile)
        detector = {
            'profile': file_pin(profile), 'recipe': launch['recipe'],
            'worker': file_pin(Path(launch['worker_script'])),
            'python': interpreter_pin(Path(launch['python'])),
            'rule': file_pin(b0.resolve('detection_rule')), 'mapping': file_pin(b0.resolve('mapping')),
            'base_policy': asdict(b0),
        }
    return {
        'source': source_pin(root),
        'dataset': dataset_pin(args.habitat_data, args.episode_set, args.split, episodes),
        'manifest': file_pin(args.manifest) if args.manifest else None,
        'runner_config': asdict(config),
        'detector': detector,
        'host': {'machine': platform.node(), 'platform': platform.platform(),
                 'python': interpreter_pin(Path(sys.executable)),
                 'renderer_environment': {name: os.environ.get(name) for name in
                    ('DISPLAY', 'EGL_PLATFORM', 'LIBGL_ALWAYS_SOFTWARE', 'CUDA_VISIBLE_DEVICES')}},
        'habitat': interpreter_pin(args.habitat_python, module='habitat_sim'),
        'seeds': {'episode_order': 'manifest_or_source_order', 'worker_rng': 'runtime_defaults'},
    }
