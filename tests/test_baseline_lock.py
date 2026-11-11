import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    'baseline_lock', Path(__file__).resolve().parents[1] / 'tools' / 'baseline_lock.py')
bl = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bl)


def _tree(tmp_path):
    root = tmp_path / 'wt'
    (root / 'src/hydra').mkdir(parents=True)
    (root / 'src/hydra/a.py').write_text('a = 1\n')
    (root / 'src/hydra/b.py').write_text('b = 2\n')
    (root / 'src/hydra/__pycache__').mkdir()
    (root / 'src/hydra/__pycache__/a.cpython-312.pyc').write_bytes(b'x')
    model = tmp_path / 'model.bin'
    model.write_bytes(b'weights')
    sha = bl.sha256_file(model)
    (root / 'configs').mkdir()
    (root / 'configs/slm.json').write_text(json.dumps(
        {'model_path': str(model), 'model_sha256': sha,
         'runtime_binary_path': str(tmp_path / 'server'), 'runtime_sha256': 'f' * 64,
         'detector': {'checkpoint': {'path': str(model), 'sha256': sha}}}))
    spec = root / 'docs/lock.spec.json'
    spec.parent.mkdir()
    spec.write_text(json.dumps({'name': 't', 'groups': {
        'hydra': ['src/hydra/*.py'], 'slm': ['configs/slm.json']}}))
    return root, spec, model


def test_create_then_verify_passes_and_skips_pycache(tmp_path):
    root, spec, _ = _tree(tmp_path)
    lock = bl.create(spec, root, None)
    data = json.loads(lock.read_text())
    assert [e['path'] for e in data['entries']] == ['src/hydra/a.py', 'src/hydra/b.py', 'configs/slm.json']
    assert len(data['pinned_assets']) == 2
    (tmp_path / 'server').write_bytes(b'srv')
    assert bl.verify(lock, root) == ['CHANGED  asset ' + str(tmp_path / 'server')]
    data['pinned_assets'][str(tmp_path / 'server')]['sha256'] = bl.sha256_file(tmp_path / 'server')
    lock.write_text(json.dumps(data))
    assert bl.verify(lock, root) == []


def test_changed_added_missing_and_asset_are_all_refused(tmp_path):
    root, spec, model = _tree(tmp_path)
    lock = bl.create(spec, root, None)
    (root / 'src/hydra/a.py').write_text('a = 3\n')
    (root / 'src/hydra/c.py').write_text('c = 1\n')
    (root / 'src/hydra/b.py').unlink()
    model.write_bytes(b'other weights')
    problems = bl.verify(lock, root)
    assert 'CHANGED  src/hydra/a.py' in problems
    assert 'ADDED    src/hydra/c.py' in problems
    assert 'MISSING  src/hydra/b.py' in problems
    assert any(p.startswith('CHANGED  asset') for p in problems)
    assert not any('asset' in p for p in bl.verify(lock, root, skip_assets=True))


def test_lock_is_never_overwritten_and_empty_pattern_is_an_error(tmp_path):
    root, spec, _ = _tree(tmp_path)
    bl.create(spec, root, None)
    with pytest.raises(FileExistsError):
        bl.create(spec, root, None)
    bad = root / 'docs/bad.spec.json'
    bad.write_text(json.dumps({'name': 'b', 'groups': {'x': ['nothing/*.py']}}))
    with pytest.raises(ValueError):
        bl.create(bad, root, None)


def test_cli_exit_codes(tmp_path, capsys):
    root, spec, _ = _tree(tmp_path)
    lock = bl.create(spec, root, None)
    assert bl.main(['verify', str(lock), '--root', str(root), '--skip-assets']) == 0
    assert bl.main(['verify', str(lock), '--root', str(root)]) == 1  # runtime binary missing
    (root / 'configs/slm.json').write_text('{}')
    assert bl.main(['verify', str(lock), '--root', str(root), '--skip-assets']) == 1
    assert 'BASELINE LOCK FAILED' in capsys.readouterr().err
