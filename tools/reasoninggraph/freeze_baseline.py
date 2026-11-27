#!/usr/bin/env python3
"""Freeze and verify a local ReasoningGraph M0 baseline without starting workers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from tempfile import NamedTemporaryFile

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ''):
    sys.path.insert(0, str(ROOT))

from tools.baseline_lock import pinned_assets, sha256_file

ROLES = ('dev', 'test', 'split', 'paper_protocol', 'paper_b0', 'hydra_export')
BINDINGS = ('hydra_binding', 'spark_dsg_binding')


def _object(path):
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f'expected JSON object: {path}')
    return data


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False)


def _pin(root, value, expected=None):
    if not isinstance(value, (str, Path)) or not str(value):
        raise ValueError('expected a local file path')
    path = (root / value).absolute()
    digest = sha256_file(path)
    if expected is not None and digest != expected:
        raise ValueError(f'checksum mismatch: {path}')
    name = path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)
    return dict(path=name, sha256=digest, bytes=path.stat().st_size)


def _git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def _source(root):
    source_paths = _git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard',
                        '--', 'src', 'tools', 'pyproject.toml').decode().split('\0')
    files = {}
    for name in sorted(set(source_paths) - {''}):
        path = root / name
        if path.suffix not in {'.py', '.toml', '.sh'}:
            continue
        if path.is_symlink():
            raise ValueError(f'source symlink cannot be frozen: {name}')
        if path.is_file():
            files[name] = _pin(root, path)['sha256']
    return dict(head=_git(root, 'rev-parse', 'HEAD').decode().strip(),
                tree=_git(root, 'rev-parse', 'HEAD^{tree}').decode().strip(),
                dirty=bool(_git(root, 'status', '--porcelain', '--untracked-files=all',
                                '--', 'src', 'tools', 'pyproject.toml')),
                files=files, digest=hashlib.sha256(_json(files).encode()).hexdigest())


def _split(path, policy, scope, count):
    data = _object(path)
    uids = data.get('uids')
    if (data.get('schema_version') != 1 or not isinstance(uids, list) or len(uids) != count
            or not all(isinstance(uid, str) for uid in uids) or len(set(uids)) != count):
        raise ValueError(f'{scope} manifest must have {count} unique UIDs')
    scenes = set()
    for uid in uids:
        fields = uid.split('/')
        if len(fields) != 4 or fields[:2] != [policy['episode_set'], policy['split']] or not fields[3]:
            raise ValueError(f'{scope} UID outside locked split: {uid}')
        scenes.add(fields[2])
    if scenes != set(policy[scope + '_scenes']):
        raise ValueError(f'{scope} UID scenes differ from split definition')
    return uids


def _export(root, data):
    if data.get('schema_version') != 1 or data.get('complete') is not True:
        raise ValueError('complete native export v1 is required')
    for key in ('graph_sha256', 'journal_sha256', 'build_sha256', 'native_binding_sha256',
                'input_prefix_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(data.get(key, ''))):
            raise ValueError(f'invalid native export pin: {key}')
    source = data.get('source_sha256')
    if not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', str(source)):
        raise ValueError('invalid native source pin')
    selected = data.get('selected_inputs')
    revision = data.get('graph_revision')
    if (not isinstance(selected, list) or not selected or type(revision) is not int
            or revision != len(selected)
            or any(row['graph_revision'] != i for i, row in enumerate(selected, 1))
            or selected[-1]['input_prefix_sha256'] != data['input_prefix_sha256']):
        raise ValueError('incomplete native selected-input prefix')
    return dict(graph=_pin(root, data['graph_path'], data['graph_sha256']),
                journal=_pin(root, data['journal_path'], data['journal_sha256']),
                graph_revision=revision, input_prefix_sha256=data['input_prefix_sha256'],
                source_revision=source, build_sha256=data['build_sha256'], selected_inputs=selected)


def _build(config, manifest, root):
    root = Path(root).resolve()
    config, manifest = Path(config).resolve(), Path(manifest).resolve()
    profile = _object(config)
    inputs = _object(manifest)
    if (inputs.get('schema_version') != 1 or not set(ROLES) <= inputs.keys()
            or set(inputs.get('native_binaries', {})) != set(BINDINGS)
            or inputs.keys() - {*ROLES, 'schema_version', 'native_binaries', 'support', 'native_sources'}):
        raise ValueError('invalid M0 input manifest v1')
    checkpoint = profile.get('detector', {}).get('checkpoint', {})
    if not isinstance(checkpoint, dict) or not re.fullmatch('[0-9a-f]{64}', str(checkpoint.get('sha256', ''))):
        raise ValueError('missing detector checkpoint pin')
    assets = {name: _pin(root, name, digest) for name, digest in sorted(pinned_assets(profile).items())}
    if checkpoint.get('path') not in assets or assets[checkpoint['path']]['sha256'] != checkpoint['sha256']:
        raise ValueError('missing or inconsistent detector checkpoint pin')

    paths = {role: root / inputs[role] for role in ROLES}
    split = _object(paths['split'])
    dev = _split(paths['dev'], split, 'dev', 60)
    test = _split(paths['test'], split, 'test', 180)
    if set(split['dev_scenes']) & set(split['test_scenes']):
        raise ValueError('development and test scenes overlap')

    export = _object(paths['hydra_export'])
    hydra = _export(root, export)
    binaries = {role: _pin(root, inputs['native_binaries'][role],
                           export['native_binding_sha256'] if role == 'hydra_binding' else None)
                for role in BINDINGS}
    native_sources = {}
    for role, directory in sorted(inputs.get('native_sources', {}).items()):
        native_sources[role] = _git(root / directory, 'rev-parse', 'HEAD').decode().strip()
    if native_sources.get('hydra', hydra['source_revision']) != hydra['source_revision']:
        raise ValueError('Hydra source checkout differs from export pin')
    support = {role: _pin(root, name) for role, name in sorted(inputs.get('support', {}).items())}
    return dict(schema_version=1, source=_source(root), config=_pin(root, config),
                input_manifest=_pin(root, manifest), inputs={name: _pin(root, path) for name, path in paths.items()},
                assets=list(assets.values()), native_binaries=binaries, native_sources=native_sources, hydra=hydra,
                splits=dict(seed=split['seed'], dev=dev, test=test), support=support,
                profile=dict(mode=profile.get('mode'), name=profile.get('profile'),
                             seed=profile.get('sensor_config', {}).get('seed')))


def freeze_baseline(config, manifest, source_root, output):
    lock = _build(config, manifest, source_root)
    output = Path(output)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent) as staged:
        json.dump(lock, staged, indent=2, sort_keys=True, allow_nan=False)
        staged.write('\n')
        staged.flush()
        # An existing lock is immutable, including when two runs race.
        import os
        os.link(staged.name, output)
    return lock


def verify_baseline(config, manifest, source_root, output):
    expected = _object(Path(output))
    actual = _build(config, manifest, source_root)
    changed = sorted(key for key in expected.keys() | actual.keys() if expected.get(key) != actual.get(key))
    if changed:
        raise ValueError('baseline differs in ' + ', '.join(changed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze', 'verify'))
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--source-root', default=ROOT, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    action = freeze_baseline if args.command == 'freeze' else verify_baseline
    try:
        action(args.config, args.manifest, args.source_root, args.output)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'{error}\n')
    print(f'{args.command}: {args.output}')


if __name__ == '__main__':
    main()
