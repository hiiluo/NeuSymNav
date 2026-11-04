import importlib.util
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location('prepare_hypersim_training', Path(__file__).parents[1] / 'tools/prepare_hypersim_training.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_conflicts_and_unmapped_are_ignored_with_lossless_instance_masks():
    sem = np.array([[5, 5, 5, -1], [5, 7, 1, 5], [7, 7, 5, 5]], dtype=np.int16)
    ins = np.array([[1, 1, 2, 2], [3, 3, 4, -1], [5, 5, 6, 6]], dtype=np.int16)
    mask, ignore, background, objects, cross = module.convert_frame(sem, ins, {5: ('chair', 16), 7: ('table', 50)})
    assert [(x['raw_instance_id'], x['class_id']) for x in objects] == [(1, 16), (5, 50), (6, 16)]
    assert np.array_equal(mask, [[1, 1, 0, 0], [0, 0, 0, 0], [2, 2, 3, 3]])
    assert np.array_equal(background, [[0, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 0]])
    assert np.array_equal(ignore, (mask == 0) & ~background)
    assert cross[2] == {-1: 1, 5: 1}
    assert cross[3] == {5: 1, 7: 1}


def test_scene_split_is_disjoint_and_order_independent():
    scenes = ['ai_001_002', 'ai_002_001', 'ai_003_001', 'ai_004_003', 'ai_005_001', 'ai_006_002', 'ai_006_010', 'ai_007_001', 'ai_007_008', 'ai_008_005', 'ai_010_007', 'ai_015_001', 'ai_016_009', 'ai_044_001']
    split = module.freeze_split(scenes)
    assert split == module.freeze_split(list(reversed(scenes)))
    assert sorted(map(len, split.values())) == [2, 3, 9]
    assert len(set().union(*map(set, split.values()))) == 14


def test_scene_conflict_overrides_background_and_positive_supervision():
    sem = np.array([[1, 5, 2, 22, -1]], dtype=np.int16)
    ins = np.array([[7, 7, -1, -1, 8]], dtype=np.int16)
    mask, ignore, background, objects, cross = module.convert_frame(sem, ins, {5: ('chair', 16)}, {7})
    assert not objects
    assert not mask.any()
    assert np.array_equal(background, [[0, 0, 1, 1, 0]])
    assert np.array_equal(ignore, [[1, 1, 0, 0, 1]])
