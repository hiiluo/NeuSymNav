from dataclasses import replace

import numpy as np
import pytest

from test_rg_evidence import inputs
from neusymnav.contracts.reasoninggraph import FeatureSpec, NativeObjectGeometry
from neusymnav.reasoninggraph.object_features import ObjectFeatureStore, rank_objects
from neusymnav.reasoninggraph.semantic_encoder import ObjectEncoder, ObjectRecipe


def spec():
    return FeatureSpec('clip-test', '1' * 64, '2' * 64, 2, 'object')


def test_encode_mask_bbox_and_reuse_exact_prompt():
    images = []
    prompts = []

    def image(value):
        images.append(value.copy())
        return [1., 0.] if value.any() else [0., 1.]

    def text(prompt):
        prompts.append(prompt)
        return [0., 2.]

    encoder = ObjectEncoder(spec(), image, text)
    rgb = np.full((2, 3, 3), 255, dtype=np.uint8)
    mask = np.array([[True, False, False], [False, False, False]])
    a = encoder.encode_object(rgb, mask, 'chair')
    b = encoder.encode_object(rgb, mask, 'chair')
    assert prompts == ['a photo of a chair']
    assert np.array_equal(images[0], rgb) and not images[1][~mask].any()
    assert a == b and a.text == (0., 1.)


def test_revision_pooling_deduplicates_and_ranks_without_confidence():
    evidence, node, token = inputs()
    encoder = ObjectEncoder(spec(), lambda _: [1., 0.], lambda _: [0., 1.])
    rgb = np.ones((2, 2, 3), dtype=np.uint8)
    channels = encoder.encode_object(rgb, np.ones((2, 2), dtype=bool), 'chair')
    store = ObjectFeatureStore(token, spec(), ObjectRecipe(mask_weight=.1, text_weight=.9))
    assert store.add(node.ref, evidence.evidence.detection_id, channels)
    assert not store.add(node.ref, evidence.evidence.detection_id, channels)
    with pytest.raises(ValueError, match='different feature space'):
        store.add(node.ref, 'other', replace(channels, spec=replace(spec(), dimension=3)))
    foreign = replace(node.ref, token=replace(node.ref.token, graph_revision=9))
    with pytest.raises(ValueError, match='exact object'):
        store.add(foreign, 'late', channels)
    result = rank_objects(store.view(), [0., 1.], spec(), top_k=1)
    assert result[0].ref == node.ref and result[0].support == 1
    assert result[0].cosine == pytest.approx(.9 / np.linalg.norm([.1, .9]))


def test_zero_and_nan_images_are_missing_and_do_not_mint_support():
    _, node, token = inputs()
    encoder = ObjectEncoder(spec(), lambda _: [float('nan'), 0.], lambda _: [0., 0.])
    channels = encoder.encode_object(np.ones((2, 2, 3), dtype=np.uint8), np.ones((2, 2), dtype=bool), 'chair')
    assert channels.missing == ('bbox', 'mask', 'text')
    store = ObjectFeatureStore(token, spec(), ObjectRecipe())
    assert not store.add(node.ref, 'missing', channels)
    assert not rank_objects(store.view(), [0., 1.], spec(), top_k=2)
