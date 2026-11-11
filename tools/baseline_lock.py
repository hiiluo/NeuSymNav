#!/usr/bin/env python3
"""Create or verify a hash lock that freezes a baseline (Hydra + SLM + perception).

A lock pins every file matched by its glob patterns (sha256 + size) and, in
addition, every asset that a locked JSON config pins by hash (models, runtime
binaries, scenes): ``{"path": p, "sha256": h}`` objects and ``x_path`` /
``x_sha256`` key pairs. An evaluation run must refuse to start when ``verify``
fails, so every A/B comparison uses exactly the same 3DSG stack.

    python3 tools/baseline_lock.py create docs/baselines/<name>.spec.json   # writes <name>.lock.json
    python3 tools/baseline_lock.py verify docs/baselines/<name>.lock.json   # exit 0 = unchanged
    python3 tools/baseline_lock.py verify <lock> --skip-assets               # sources only (fast)

Standard library only. Paths in the spec are relative to the worktree root
(the parent of ``tools/``) unless ``--root`` is given.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
from pathlib import Path

SCHEMA_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def expand(root: Path, patterns: list[str]) -> list[str]:
    """Glob patterns -> sorted relative file paths; a pattern matching nothing is an error."""
    found = set()
    for pattern in patterns:
        hits = [p for p in root.glob(pattern) if p.is_file() and '__pycache__' not in p.parts]
        if not hits:
            raise ValueError(f'pattern matched no file: {pattern}')
        found.update(p.relative_to(root).as_posix() for p in hits)
    return sorted(found)


def pinned_assets(value, out=None):
    """Collect (path, sha256) pairs a JSON config pins by hash."""
    out = {} if out is None else out
    if isinstance(value, dict):
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            out[value['path']] = value['sha256']
        for key, item in value.items():
            if key.endswith('_path') and isinstance(item, str):
                stem = key[:-len('_path')]
                # model_path/model_sha256 and runtime_binary_path/runtime_sha256 both occur.
                pin = value.get(stem + '_sha256') or value.get(stem.rsplit('_', 1)[0] + '_sha256')
                if isinstance(pin, str):
                    out[item] = pin
            pinned_assets(item, out)
    elif isinstance(value, list):
        for item in value:
            pinned_assets(item, out)
    return out


def collect_assets(root: Path, files: list[str]) -> dict:
    assets = {}
    for rel in files:
        if not rel.endswith('.json'):
            continue
        try:
            value = json.loads((root / rel).read_text())
        except ValueError:
            continue
        for path, pin in pinned_assets(value).items():
            assets.setdefault(path, {'sha256': pin, 'pinned_by': []})['pinned_by'].append(rel)
            if assets[path]['sha256'] != pin:
                raise ValueError(f'asset pinned with two different hashes: {path}')
    # An asset that is itself a locked file is already covered.
    locked = {str((root / rel).resolve()) for rel in files}
    return {p: v for p, v in sorted(assets.items())
            if str(Path(p).resolve()) not in locked and not any(p.endswith('/' + rel) for rel in files)}


def create(spec_path: Path, root: Path, out: Path | None) -> Path:
    spec = json.loads(spec_path.read_text())
    groups = spec['groups']
    entries = []
    for group, patterns in groups.items():
        for rel in expand(root, patterns):
            path = root / rel
            entries.append({'group': group, 'path': rel, 'bytes': path.stat().st_size,
                            'sha256': sha256_file(path)})
    seen = [e['path'] for e in entries]
    if len(seen) != len(set(seen)):
        raise ValueError('a file is matched by two groups; make the groups disjoint')
    lock = {
        'schema_version': SCHEMA_VERSION,
        'name': spec['name'],
        'created_utc': _dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'description': spec.get('description', ''),
        'not_locked': spec.get('not_locked', []),
        'groups': groups,
        'entries': entries,
        'pinned_assets': collect_assets(root, seen),
    }
    out = out or spec_path.with_name(spec_path.name.replace('.spec.json', '.lock.json'))
    if out.exists():
        raise FileExistsError(f'{out} exists; a lock is never overwritten (make a new name)')
    out.write_text(json.dumps(lock, indent=2, sort_keys=False) + '\n')
    return out


def verify(lock_path: Path, root: Path, skip_assets: bool = False) -> list[str]:
    """Return a list of problems; empty = the baseline is unchanged."""
    lock = json.loads(lock_path.read_text())
    if lock.get('schema_version') != SCHEMA_VERSION:
        return [f'unsupported lock schema {lock.get("schema_version")}']
    problems = []
    expected = {e['path']: e for e in lock['entries']}
    try:
        current = set()
        for patterns in lock['groups'].values():
            current.update(expand(root, patterns))
    except ValueError as exc:
        problems.append(f'MISSING  {exc}')
        current = set(expected)
    for rel in sorted(current - set(expected)):
        problems.append(f'ADDED    {rel}')
    for rel, entry in sorted(expected.items()):
        path = root / rel
        if not path.is_file():
            problems.append(f'MISSING  {rel}')
        elif path.stat().st_size != entry['bytes'] or sha256_file(path) != entry['sha256']:
            problems.append(f'CHANGED  {rel}')
    if not skip_assets:
        for asset, info in lock.get('pinned_assets', {}).items():
            path = Path(asset)
            if not path.is_file():
                problems.append(f'MISSING  asset {asset}')
            elif sha256_file(path) != info['sha256']:
                problems.append(f'CHANGED  asset {asset}')
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('create')
    c.add_argument('spec', type=Path)
    c.add_argument('--out', type=Path)
    c.add_argument('--root', type=Path, default=ROOT)
    v = sub.add_parser('verify')
    v.add_argument('lock', type=Path)
    v.add_argument('--root', type=Path, default=ROOT)
    v.add_argument('--skip-assets', action='store_true')
    a = ap.parse_args(argv)
    if a.cmd == 'create':
        out = create(a.spec, a.root.resolve(), a.out)
        lock = json.loads(out.read_text())
        print(f'wrote {out}: {len(lock["entries"])} files, {len(lock["pinned_assets"])} pinned assets')
        return 0
    lock = json.loads(a.lock.read_text())
    problems = verify(a.lock, a.root.resolve(), a.skip_assets)
    if problems:
        print(f'BASELINE LOCK FAILED: {lock.get("name")} ({len(problems)} problem(s))', file=sys.stderr)
        for p in problems:
            print('  ' + p, file=sys.stderr)
        return 1
    assets = 0 if a.skip_assets else len(lock.get('pinned_assets', {}))
    print(f'baseline lock OK: {lock["name"]} ({len(lock["entries"])} files, {assets} assets checked)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
