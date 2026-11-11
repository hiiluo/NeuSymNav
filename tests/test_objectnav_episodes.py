import gzip
import json
from pathlib import Path

import pytest

from neusymnav.objectnav.episodes import (load_episode_set, read_manifest, resolve_scene, select,
                                          write_manifest)


def _gz(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt') as stream:
        json.dump(data, stream)


def _ep(eid, scene_id, cat, geo=3.0):
    return {'episode_id': eid, 'scene_id': scene_id, 'start_position': [1.0, 0.1, 2.0],
            'start_rotation': [0.0, 0.7071, 0.0, 0.7071], 'object_category': cat,
            'info': {'geodesic_distance': geo}}


def _goal(cat, vps):
    return {'object_id': 7, 'object_category': cat, 'position': [3.0, 0.5, 4.0],
            'view_points': [{'agent_state': {'position': v, 'rotation': [0, 0, 0, 1]}, 'iou': 0.5} for v in vps]}


@pytest.fixture
def habitat_data(tmp_path):
    root = tmp_path / 'habitat_data'
    hm3d = root / 'versioned_data/hm3d-0.2/hm3d'
    for part, scene in (('val', '00877-4ok3usBNeis'), ('minival', '00800-TEEsavR23oF')):
        short = scene.split('-')[1]
        (hm3d / part / scene).mkdir(parents=True)
        (hm3d / part / scene / ('%s.basis.glb' % short)).write_bytes(b'g')
        (hm3d / part / ('hm3d_%s_basis.scene_dataset_config.json' % part)).write_text('{}')
        (hm3d / part / ('hm3d_annotated_%s_basis.scene_dataset_config.json' % part)).write_text('{}')
    (root / 'scene_datasets/mp3d/2azQ1b91cZZ').mkdir(parents=True)
    (root / 'scene_datasets/mp3d/2azQ1b91cZZ/2azQ1b91cZZ.glb').write_bytes(b'g')
    # HM3D v2 val: empty top file + per-scene content
    v2 = root / 'datasets/objectnav/hm3d/v2'
    _gz(v2 / 'val/val.json.gz', {'episodes': [], 'category_to_task_category_id': {'chair': 0, 'bed': 1}})
    sid = 'hm3d_v0.2/val/00877-4ok3usBNeis/4ok3usBNeis.basis.glb'
    _gz(v2 / 'val/content/4ok3usBNeis.json.gz', {
        'episodes': [_ep('0', sid, 'chair'), _ep('1', sid, 'bed', 5.0)],
        'goals_by_category': {'4ok3usBNeis.basis.glb_chair': [_goal('chair', [[2, 0.1, 3], [2.5, 0.1, 3]])],
                              '4ok3usBNeis.basis.glb_bed': [_goal('bed', [[4, 0.1, 1]])]}})
    sid_mini = 'hm3d_v0.2/minival/00800-TEEsavR23oF/TEEsavR23oF.basis.glb'
    _gz(v2 / 'val_mini/val_mini.json.gz', {'episodes': []})
    _gz(v2 / 'val_mini/content/TEEsavR23oF.json.gz', {
        'episodes': [_ep('0', sid_mini, 'chair')],
        'goals_by_category': {'TEEsavR23oF.basis.glb_chair': [_goal('chair', [[1, 0.1, 1]])]}})
    # MP3D val_mini: episodes and goals in the top file, no content dir
    _gz(root / 'datasets/objectnav/mp3d/v1/val_mini/val_mini.json.gz', {
        'episodes': [_ep('5', 'mp3d/2azQ1b91cZZ/2azQ1b91cZZ.glb', 'sink')],
        'goals_by_category': {'2azQ1b91cZZ.glb_sink': [_goal('sink', [[0, 0, 0]])]}})
    return root


def test_hm3d_v2_content_files_resolve_scene_configs_and_goals(habitat_data):
    eps = load_episode_set('hm3d_v2', 'val', habitat_data)
    assert [e.uid for e in eps] == ['hm3d_v2/val/4ok3usBNeis/0', 'hm3d_v2/val/4ok3usBNeis/1']
    chair = eps[0]
    assert chair.scene_path.endswith('versioned_data/hm3d-0.2/hm3d/val/00877-4ok3usBNeis/4ok3usBNeis.basis.glb')
    assert chair.runtime_dataset_config.endswith('val/hm3d_val_basis.scene_dataset_config.json')
    assert chair.eval_dataset_config.endswith('val/hm3d_annotated_val_basis.scene_dataset_config.json')
    assert 'annotated' not in chair.runtime_dataset_config
    assert len(chair.view_points) == 2 and eps[1].view_points == ((4.0, 0.1, 1.0),)
    assert chair.start_rotation_xyzw == (0.0, 0.7071, 0.0, 0.7071)
    assert chair.stored_geodesic_m == 3.0


def test_minival_prefix_and_mp3d_top_file_layout(habitat_data):
    mini = load_episode_set('hm3d_v2', 'val_mini', habitat_data)
    assert mini[0].scene_path.endswith('minival/00800-TEEsavR23oF/TEEsavR23oF.basis.glb')
    assert mini[0].runtime_dataset_config.endswith('minival/hm3d_minival_basis.scene_dataset_config.json')
    mp3d = load_episode_set('mp3d_v1', 'val_mini', habitat_data)
    assert mp3d[0].uid == 'mp3d_v1/val_mini/2azQ1b91cZZ/5'
    assert mp3d[0].runtime_dataset_config is None and mp3d[0].eval_dataset_config is None


def test_scene_filter_selection_and_manifest_roundtrip(habitat_data, tmp_path):
    eps = load_episode_set('hm3d_v2', 'val', habitat_data, scenes=['nothing'])
    assert eps == []
    eps = load_episode_set('hm3d_v2', 'val', habitat_data)
    assert [e.object_category for e in select(eps, categories=['bed'])] == ['bed']
    a = select(eps, seed=3)
    assert a == select(eps, seed=3) and len(select(eps, per_scene=1)) == 1
    write_manifest(a, tmp_path / 'm.json')
    assert read_manifest(tmp_path / 'm.json', eps) == a


def test_missing_scene_and_unknown_set_fail_closed(habitat_data):
    with pytest.raises(FileNotFoundError):
        resolve_scene(habitat_data, 'hm3d_v0.2/val/00999-x/x.basis.glb')
    with pytest.raises(ValueError):
        load_episode_set('gibson', 'val', habitat_data)


def test_dev_test_split_is_disjoint_deterministic_and_frozen(habitat_data, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location('make_split', Path(__file__).resolve().parents[1] / 'tools/objectnav/make_split.py')
    ms = importlib.util.module_from_spec(spec); spec.loader.exec_module(ms)
    out = tmp_path / 'splits'
    args = ['--set', 'hm3d_v2', '--split', 'val', '--dev-scenes', '4ok3usBNeis', '--extra-dev-scenes', '0',
            '--seed', '7', '--out-dir', str(out), '--habitat-data', str(habitat_data)]
    ms.main(args)
    summary = json.loads((out / 'hm3d_v2-val-split.json').read_text())
    assert summary['dev_scenes'] == ['4ok3usBNeis'] and summary['test_scenes'] == []
    assert summary['dev_episodes'] == 2 and summary['test_episodes'] == 0
    with pytest.raises(SystemExit):
        ms.main(args)                                   # a frozen split is never overwritten
    with pytest.raises(ValueError):
        ms.make_split(load_episode_set('hm3d_v2', 'val', habitat_data), dev_scenes=['nope'],
                      extra_dev_scenes=0, seed=1, dev_per_scene=1, test_per_scene=1)


def test_repeated_episode_ids_within_a_scene_get_stable_unique_uids(habitat_data):
    sid = 'hm3d_v0.2/val/00877-4ok3usBNeis/4ok3usBNeis.basis.glb'
    path = habitat_data / 'datasets/objectnav/hm3d/v2/val/content/4ok3usBNeis.json.gz'
    with gzip.open(path, 'rt') as stream:
        data = json.load(stream)
    data['episodes'] += [_ep('0', sid, 'bed'), _ep('0', sid, 'chair')]
    _gz(path, data)
    uids = [e.uid for e in load_episode_set('hm3d_v2', 'val', habitat_data)]
    assert uids == ['hm3d_v2/val/4ok3usBNeis/0', 'hm3d_v2/val/4ok3usBNeis/1',
                    'hm3d_v2/val/4ok3usBNeis/0#2', 'hm3d_v2/val/4ok3usBNeis/0#3']
    assert uids == [e.uid for e in load_episode_set('hm3d_v2', 'val', habitat_data)]
