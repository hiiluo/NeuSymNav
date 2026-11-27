import json
from pathlib import Path
import subprocess

import pytest

from tools.baseline_lock import sha256_file
from tools.reasoninggraph.freeze_baseline import freeze_baseline, verify_baseline


def write_json(path, value):
    path.write_text(json.dumps(value))
    return path


@pytest.fixture
def inputs(tmp_path):
    root = tmp_path
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    source = root / 'src'
    source.mkdir()
    (source / 'tracked.py').write_text('value = 1\n')
    subprocess.run(['git', '-C', str(root), 'add', 'src'], check=True)
    subprocess.run(['git', '-C', str(root), '-c', 'user.email=test@example.org',
                    '-c', 'user.name=Test', 'commit', '-qm', 'source'], check=True)
    (source / 'new.py').write_text('value = 2\n')
    (root / '.env').write_text('A_SECRET=not locked\n')

    model = root / 'model'
    model.write_bytes(b'model')
    config = write_json(root / 'hydra.json', {'mode': 'live', 'profile': 'baseline',
        'detector': {'checkpoint': {'path': 'model', 'sha256': sha256_file(model)}},
        'sensor_config': {'seed': 0}})
    for name, count, scene in [('dev', 60, 'dev-scene'), ('test', 180, 'test-scene')]:
        write_json(root / f'{name}.json', {'schema_version': 1,
            'uids': [f'hm3d_v2/val/{scene}/{index}' for index in range(count)]})
    split = write_json(root / 'split.json', {'schema_version': 1,
        'episode_set': 'hm3d_v2', 'split': 'val', 'seed': 3,
        'dev_scenes': ['dev-scene'], 'test_scenes': ['test-scene']})
    (root / 'graph').write_bytes(b'graph')
    (root / 'journal').write_bytes(b'journal')
    for binary in ('hydra.so', 'spark.so'):
        (root / binary).write_bytes(binary.encode())
    write_json(root / 'export.json', {'schema_version': 1, 'complete': True,
        'graph_path': 'graph', 'graph_sha256': sha256_file(root / 'graph'),
        'journal_path': 'journal', 'journal_sha256': sha256_file(root / 'journal'),
        'native_binding_sha256': sha256_file(root / 'hydra.so'), 'source_sha256': 'a' * 40,
        'build_sha256': 'b' * 64, 'input_prefix_sha256': 'c' * 64, 'graph_revision': 1,
        'selected_inputs': [{'graph_revision': 1, 'input_prefix_sha256': 'c' * 64,
            'source': {'episode_id': 'example', 'sensor_id': 'rgbd', 'frame_index': 5}}]})
    for name in ('paper-protocol', 'paper-b0', 'navmesh-pins'):
        write_json(root / f'{name}.json', {'schema_version': 1})
    descriptor = write_json(root / 'inputs.json', {'schema_version': 1,
        'dev': 'dev.json', 'test': 'test.json', 'split': split.name,
        'paper_protocol': 'paper-protocol.json', 'paper_b0': 'paper-b0.json',
        'hydra_export': 'export.json',
        'native_binaries': {'hydra_binding': 'hydra.so', 'spark_dsg_binding': 'spark.so'},
        'support': {'navmeshes': 'navmesh-pins.json'}})
    return root, config, descriptor


def test_lock_records_dirty_source_and_rejects_changed_resume(inputs):
    root, config, descriptor = inputs
    output = root / 'baseline.lock.json'
    lock = freeze_baseline(config, descriptor, root, output)
    assert lock['schema_version'] == 1
    assert lock['source']['dirty']
    assert set(lock['source']['files']) == {'src/new.py', 'src/tracked.py'}
    assert len(lock['splits']['dev']) == 60
    assert len(lock['splits']['test']) == 180
    assert lock['hydra']['selected_inputs'][0]['source']['frame_index'] == 5
    assert lock['native_binaries']['spark_dsg_binding']['sha256'] == sha256_file(root / 'spark.so')
    assert 'A_SECRET' not in output.read_text()
    verify_baseline(config, descriptor, root, output)
    write_json(config, {**json.loads(config.read_text()), 'profile': 'changed'})
    with pytest.raises(ValueError, match='baseline differs'):
        verify_baseline(config, descriptor, root, output)


def test_lock_fails_for_missing_or_mismatched_asset_pin(inputs):
    root, config, descriptor = inputs
    original = json.loads(config.read_text())
    write_json(config, {**original, 'detector': {'checkpoint': {'path': 'model'}}})
    with pytest.raises(ValueError, match='checkpoint pin'):
        freeze_baseline(config, descriptor, root, root / 'missing.json')
    write_json(config, original)
    (root / 'model').write_bytes(b'different')
    with pytest.raises(ValueError, match='checksum'):
        freeze_baseline(config, descriptor, root, root / 'mismatch.json')


def test_lock_fails_for_duplicate_split_and_wrong_native_binary(inputs):
    root, config, descriptor = inputs
    dev = root / 'dev.json'
    original = json.loads(dev.read_text())
    write_json(dev, {**original, 'uids': [original['uids'][0]] * 60})
    with pytest.raises(ValueError, match='60 unique'):
        freeze_baseline(config, descriptor, root, root / 'out.json')
    write_json(dev, original)
    (root / 'hydra.so').write_bytes(b'wrong binding')
    with pytest.raises(ValueError, match='checksum'):
        freeze_baseline(config, descriptor, root, root / 'out.json')
