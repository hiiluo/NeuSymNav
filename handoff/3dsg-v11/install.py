#!/usr/bin/env python3
"""Install the baseline-3dsg-v11 local files on a new machine (stdlib only, Python >= 3.9).

The Hydra + SLM 00806 demo needs seven machine-local files that .gitignore keeps
out of git (profiles under configs/*.local.json, Hydra config root and tour
under runs/, the Hydra workspace env). This tool renders them from
handoff/3dsg-v11/templates/, replacing the original machine's absolute paths,
then RE-PINS every sha256 the runtime checks against the files on THIS machine
and reports which pins changed:

  same      file identical to the one the baseline was frozen with
  changed   file exists but differs (expected for Python interpreters and a
            locally built libhydra.so; NOT expected for models, scene, taxonomy)
  MISSING   file not found: install/build it, then run this tool again

    python3 handoff/3dsg-v11/install.py --habitat-data /path/to/habitat_data
    python3 handoff/3dsg-v11/install.py --habitat-data ... --detector-backend torch   # no Intel GPU

Exit 0 when nothing is missing, 1 otherwise. Existing files are only
overwritten with --force.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / 'templates'
PLACEHOLDERS = ('@REPO@', '@NSN_HOME@', '@HABITAT_DATA@', '@HABITAT_ENV@')
PROFILE = 'configs/demo-00806.hydra-tour-slm.experimental.local.json'
SLM = 'configs/room-label-slm.async-debug.local.json'
TOUR = 'runs/tours/00806-tour-r30.json'
HYDRA_ROOT = 'runs/hydra-objectnav/B1-stability-20261107/config-root/stable'
HYDRA_DATASET = HYDRA_ROOT + '/datasets/neusymnav.yaml'
HYDRA_LABELS = HYDRA_ROOT + '/label_spaces/neusymnav_label_space.yaml'
ORDER = [HYDRA_LABELS, HYDRA_DATASET, SLM, TOUR, PROFILE]       # later files pin earlier ones


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


class Report:
    def __init__(self):
        self.rows = []

    def pin(self, where, path, old):
        p = Path(path)
        if not p.is_file():
            self.rows.append((where, path, 'MISSING'))
            return old
        new = sha256(p)
        self.rows.append((where, path, 'same' if new == old else 'changed'))
        return new

    @property
    def missing(self):
        return [r for r in self.rows if r[2] == 'MISSING']

    def print(self):
        width = max([len(r[0]) for r in self.rows] + [10])
        for where, path, status in self.rows:
            print('  %-8s %-*s %s' % (status, width, where, path))


def render(text, values):
    for key in PLACEHOLDERS:
        text = text.replace(key, values[key])
    left = re.findall(r'@[A-Z_]+@', text)
    if left:
        raise SystemExit('unresolved placeholders %s' % sorted(set(left)))
    return text


def pin_profile(data, report, values, backend):
    def walk(node, where):
        if isinstance(node, dict):
            if set(node) >= {'path', 'sha256'} and isinstance(node['path'], str):
                node['sha256'] = report.pin(where, node['path'], node['sha256'])
            for key, value in node.items():
                walk(value, where + '.' + key if where else key)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, '%s[%d]' % (where, i))
    if backend == 'torch':
        det = data['detector']
        for key in ('openvino_model', 'openvino_bin', 'openvino_metadata'):
            det.pop(key, None)
        det.update(backend='torch', fallback_policy='none', device='cpu')
    walk(data, '')
    ui = data.get('ui', {}).get('room_label_debug')
    if ui:
        ui['config_sha256'] = report.pin('ui.room_label_debug.config', ui['config_path'], ui['config_sha256'])
        ui['taxonomy_sha256'] = report.pin('ui.room_label_debug.taxonomy', ui['taxonomy_path'], ui['taxonomy_sha256'])
    hydra = data.get('scene_graph', {}).get('hydra')
    if hydra:
        root = Path(hydra['config_root'])
        hydra['dataset_sha256'] = report.pin('scene_graph.hydra.dataset', str(root / 'datasets/neusymnav.yaml'),
                                             hydra['dataset_sha256'])
        hydra['labelspace_sha256'] = report.pin('scene_graph.hydra.labelspace',
                                                str(root / 'label_spaces/neusymnav_label_space.yaml'),
                                                hydra['labelspace_sha256'])
    return data


def install(values, out_root, *, backend='openvino_gpu', force=False, report=None):
    report = report or Report()
    out_root = Path(out_root)
    written = []
    for rel in ORDER:
        src = TEMPLATES / (rel + '.template')
        text = render(src.read_text(), values)
        if rel == HYDRA_DATASET:
            m = re.search(r'^(\s*library_path:\s*)(\S+)\s*$', text, re.M)
            s = re.search(r'^(\s*library_sha256:\s*)([0-9a-f]{64})\s*$', text, re.M)
            if m and s:
                new = report.pin('hydra.room_stability.library', m.group(2), s.group(2))
                text = text[:s.start(2)] + new + text[s.end(2):]
        elif rel == SLM:
            data = json.loads(text)
            data['model_sha256'] = report.pin('slm.model', data['model_path'], data['model_sha256'])
            data['runtime_sha256'] = report.pin('slm.runtime', data['runtime_binary_path'], data['runtime_sha256'])
            text = json.dumps(data, indent=2) + '\n'
        elif rel == TOUR:
            data = json.loads(text)
            data['scene']['sha256'] = report.pin('tour.scene', data['scene']['path'], data['scene']['sha256'])
            text = json.dumps(data, indent=2) + '\n'
        elif rel == PROFILE:
            text = json.dumps(pin_profile(json.loads(text), report, values, backend), indent=2) + '\n'
        target = out_root / rel
        if target.exists() and not force and target.read_text() != text:
            raise SystemExit('%s exists and differs; rerun with --force to replace it' % target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        written.append(str(target))
    return written, report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, cwd=HERE).stdout.strip()
    ap.add_argument('--repo', type=Path, default=Path(top or HERE.parents[1]),
                    help='this checkout (default: git top level)')
    ap.add_argument('--nsn-home', type=Path, help='holds .runtime/detector26 and local-assets/models (default: --repo)')
    ap.add_argument('--habitat-data', type=Path, required=True,
                    help='habitat_data root holding versioned_data/hm3d-0.2/hm3d/minival/00806-tQ5s4ShP627')
    ap.add_argument('--habitat-env', type=Path, default=Path.home() / 'miniconda3/envs/habitat',
                    help='conda env with habitat_sim 0.3.3 (bin/python is pinned)')
    ap.add_argument('--out-root', type=Path, help='write here instead of --repo (checks only)')
    ap.add_argument('--detector-backend', choices=('openvino_gpu', 'torch'), default='openvino_gpu')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args(argv)
    repo = a.repo.resolve()
    values = {'@REPO@': str(repo), '@NSN_HOME@': str((a.nsn_home or repo).resolve()),
              '@HABITAT_DATA@': str(a.habitat_data.resolve()), '@HABITAT_ENV@': str(a.habitat_env)}
    out_root = (a.out_root or repo).resolve()
    written, report = install(values, out_root, backend=a.detector_backend, force=a.force)
    if out_root == repo:
        ws = repo / '.runtime/hydra_ws'
        for src in (HERE / 'hydra_ws').rglob('*'):
            if src.is_file():
                dst = ws / src.relative_to(HERE / 'hydra_ws')
                if not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    written.append(str(dst))
    print('wrote:')
    for w in written:
        print('  ' + w)
    print('pins (same = identical to the frozen baseline file):')
    report.print()
    if report.missing:
        print('\n%d file(s) missing: install/build them (see handoff/3dsg-v11/README.md), then rerun with --force.'
              % len(report.missing))
        return 1
    print('\nall pinned files present. Next: the preflight command in handoff/3dsg-v11/README.md')
    return 0


if __name__ == '__main__':
    sys.exit(main())
