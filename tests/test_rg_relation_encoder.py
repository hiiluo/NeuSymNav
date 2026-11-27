from dataclasses import replace

from test_rg_evidence import inputs
from neusymnav.reasoninggraph.pair_selection import select_pairs


def test_pair_selection_orders_roles_and_clamps_union_crop():
    a, _, _ = inputs()
    a = replace(a, evidence=replace(a.evidence, bbox_xyxy=(0, 0, 2, 2), detection_id='a'))
    b = replace(a, evidence=replace(a.evidence, bbox_xyxy=(3, 2, 5, 4), detection_id='b'), category='table',
                bounds=((1, 0, 0), (2, 1, 1)))
    pairs = select_pairs([b, a], width=5, height=4, max_pairs=2, max_area_fraction=1.)
    assert [(p.subject, p.object) for p in pairs] == [('a','b'), ('b','a')]
    assert all(p.crop_xyxy == (0, 0, 5, 4) for p in pairs)
    assert pairs[0].subject_xyxy == pairs[1].object_xyxy
    assert select_pairs([b, a], width=5, height=4, max_pairs=1, max_area_fraction=1.) == pairs[:1]


def test_pair_selection_excludes_mixed_source_and_unobserved_depth():
    a, _, _ = inputs()
    b = replace(a, evidence=replace(a.evidence, clock_domain='different', detection_id='b'))
    c = replace(a, evidence=replace(a.evidence, detection_id='c'), bounds=((0,0,0),(0,0,0)))
    assert select_pairs([a,b,c], width=5, height=4) == ()


def test_relation_token_roundtrip_rejects_wrong_layout_or_decoder():
    import numpy as np
    import pytest

    from neusymnav.reasoninggraph.relation_encoder import RelFeatureSpec, decode_tokens, pack_tokens

    spec = RelFeatureSpec('1'*64, '2'*64, '3'*64, '4'*64, 'visual_proj/v1', 'grid-1x1', 2, 3)
    array = np.arange(6, dtype='<f2').reshape(2,3)
    asset = pack_tokens(spec, array, subject='a', object_id='b')
    assert not decode_tokens(asset, spec).flags.writeable
    assert np.array_equal(decode_tokens(asset, spec), array)
    with pytest.raises(ValueError, match='decoder'):
        decode_tokens(asset, replace(spec, decoder_sha256='5'*64))
    with pytest.raises(ValueError, match='integrity'):
        decode_tokens(replace(asset, payload=b'X'*len(asset.payload)), spec)
    with pytest.raises(ValueError, match='integrity'):
        decode_tokens(replace(asset, subject='b', object_id='a'), spec)
    with pytest.raises(ValueError, match='shape'):
        pack_tokens(spec, array.reshape(3,2), subject='a', object_id='b')


def test_visual_projector_fixture_keeps_full_pinned_shape_and_byte_limit():
    import numpy as np
    import pytest

    from neusymnav.reasoninggraph.relation_encoder import RelFeatureSpec, decode_tokens, pack_tokens

    spec = RelFeatureSpec('1'*64, '2'*64, '3'*64, '4'*64, 'vision-projector/v1', 'global-local', 392, 2560)
    tokens = np.zeros((392, 2560), dtype='<f2')
    encoded = pack_tokens(spec, tokens, subject='O(0)', object_id='O(1)')
    assert len(encoded.payload) == 2_007_040
    assert decode_tokens(encoded, spec).shape == (392, 2560)
    with pytest.raises(ValueError, match='shape'):
        replace(spec, token_count=8_192)
