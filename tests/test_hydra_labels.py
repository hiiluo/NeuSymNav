from dataclasses import replace

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts import Detection, DetectionBatch, Taxonomy
from neusymnav.backends.hydra.labels import HydraLabelRasterizer


@pytest.fixture
def taxonomy():
    return Taxonomy('taxonomy:v1', ('chair', 'table'), {'seat': 'chair'}, 'test taxonomy')


def detection(detection_id, category, score, pixels, shape=(3, 4)):
    mask = np.zeros(shape, dtype=bool)
    for row, col in pixels:
        mask[row, col] = True
    return Detection(detection_id, category or 'unmapped', category, score, mask)


def test_raster_is_order_independent_and_overlap_uses_score_then_detection_id(taxonomy):
    obs = observation()
    first = detection('z-chair', 'chair', .8, [(0, 0), (0, 1)], shape=(2, 3))
    second = detection('a-table', 'table', .8, [(0, 1), (0, 2)], shape=(2, 3))
    batches = [DetectionBatch.from_observation(obs, items, vocabulary_id='taxonomy:v1')
               for items in ((first, second), (second, first))]
    labels = [HydraLabelRasterizer(taxonomy).rasterize(obs, batch) for batch in batches]
    np.testing.assert_array_equal(labels[0].labels, labels[1].labels)
    assert labels[0].labels[0, 0] == labels[0].class_to_label['chair']
    assert labels[0].labels[0, 1] == labels[0].class_to_label['table']  # a-table wins tie
    assert labels[0].labels[0, 2] == labels[0].class_to_label['table']


def test_unknown_mask_claims_pixels_as_zero_and_invalid_depth_is_one(taxonomy):
    obs = observation(depth_m=np.array([[1., np.nan, 1.], [1., 1., 1.]], np.float32),
                      valid_depth=np.array([[True, False, True], [True]*3]))
    known = detection('known', 'chair', .4, [(0, 0), (0, 1)], shape=(2, 3))
    unknown = detection('unknown', None, .9, [(0, 0), (0, 2)], shape=(2, 3))
    batch = DetectionBatch.from_observation(obs, (known, unknown), vocabulary_id='taxonomy:v1')
    result = HydraLabelRasterizer(taxonomy).rasterize(obs, batch)
    assert result.labels[0, 0] == 0  # unknown high-score mask occludes lower score
    assert result.labels[0, 1] == 1  # invalid depth overrides every detection
    assert result.labels[0, 2] == 0
    assert result.labels[1, 2] == 0  # unmasked measured geometry remains unknown
    assert result.object_labels == frozenset({2, 3})
    assert result.invalid_labels == frozenset({1})
    assert 0 not in result.object_labels and 0 not in result.invalid_labels
    assert result.labelspace_id and len(result.labelspace_hash) == 64


def test_empty_batch_keeps_background_unknown_and_labelspace_is_exportable(taxonomy, tmp_path):
    obs = observation()
    batch = DetectionBatch.from_observation(obs, (), vocabulary_id='taxonomy:v1')
    rasterizer = HydraLabelRasterizer(taxonomy)
    result = rasterizer.rasterize(obs, batch)
    assert np.all(result.labels == 0)
    path = rasterizer.write_labelspace(tmp_path / 'label_space.yaml')
    contents = path.read_text()
    assert 'invalid_labels: [1]' in contents
    assert 'object_labels: [2, 3]' in contents
    assert 'label: 0, name: "unknown_static"' in contents
    assert 'label: 1, name: "invalid"' in contents


def test_rasterizer_rejects_batch_from_different_frame(taxonomy):
    obs = observation()
    from neusymnav.contracts.observations import FrameKey
    wrong = replace(obs, key=FrameKey('episode', 'rgbd', obs.key.frame_index + 1))
    batch = DetectionBatch.from_observation(wrong, (), vocabulary_id='taxonomy:v1')
    with pytest.raises(ValueError, match='mismatch'):
        HydraLabelRasterizer(taxonomy).rasterize(obs, batch)


def test_pinned_neusymnav_hydra_labelspace_matches_taxonomy_file(tmp_path):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    taxonomy = Taxonomy.load(root / 'configs' / 'taxonomy-v1.json')
    rasterizer = HydraLabelRasterizer(taxonomy)
    generated = rasterizer.write_labelspace(tmp_path / 'hydra-labelspace-test.yaml')
    committed = root / 'configs' / 'hydra' / 'config' / 'label_spaces' / 'neusymnav_label_space.yaml'
    assert generated.read_text() == committed.read_text()
    assert f'NeuSymNav labelspace SHA256: {rasterizer.labelspace_hash}' in committed.read_text()
