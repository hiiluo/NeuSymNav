#!/usr/bin/env python3
"""Make the handoff templates from the frozen machine's local files (run once, on the original machine).

    python3 handoff/3dsg-v11/templatize.py --source-root <frozen worktree> --machine-paths <json>

Copies the seven gitignored files of baseline-3dsg-v11 (and the Hydra
workspace dependency locks) into handoff/3dsg-v11/, replacing the original
machine's absolute paths with @REPO@ / @NSN_HOME@ / @HABITAT_DATA@ /
@HABITAT_ENV@. Fails if any absolute home path survives.
"""
import argparse
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATED = [
    'configs/demo-00806.hydra-tour-slm.experimental.local.json',
    'configs/room-label-slm.async-debug.local.json',
    'runs/tours/00806-tour-r30.json',
    'runs/hydra-objectnav/B1-stability-20261107/config-root/stable/datasets/neusymnav.yaml',
    'runs/hydra-objectnav/B1-stability-20261107/config-root/stable/label_spaces/neusymnav_label_space.yaml',
]
HYDRA_WS = ['env.sh', 'dependencies.lock.yaml', 'ros2-deps-https.yaml', 'system-dependencies.lock.json',
            'vendor-lock.json', 'wheelhouse-python/requirements.lock']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root', type=Path, required=True)
    ap.add_argument('--machine-paths', type=Path, required=True,
                    help='JSON {"@REPO@": "/abs/..", "@NSN_HOME@": .., "@HABITAT_DATA@": .., "@HABITAT_ENV@": ..}')
    a = ap.parse_args(argv)
    values = json.loads(a.machine_paths.read_text())
    order = sorted(values.items(), key=lambda kv: -len(kv[1]))            # longest path first
    home = str(Path(values['@HABITAT_ENV@']).parents[2])                  # e.g. /home/<user>
    for rel in TEMPLATED:
        text = (a.source_root / rel).read_text()
        for key, path in order:
            text = text.replace(path, key)
        if home in text:
            raise SystemExit('%s still contains %s' % (rel, home))
        out = HERE / 'templates' / (rel + '.template')
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
        print('template', out.relative_to(HERE))
    for rel in HYDRA_WS:
        out = HERE / 'hydra_ws' / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(a.source_root / '.runtime/hydra_ws' / rel, out)
        print('copied  ', out.relative_to(HERE))


if __name__ == '__main__':
    main()
