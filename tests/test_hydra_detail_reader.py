from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.contracts.hydra_graph import HydraReadToken, NativeDetailRequest, NativeNodeRef
from neusymnav.backends.hydra.detail_reader import (
    AssetStore, extract_detail, parse_detail, read_asset, SavedHydraDetailReader,
)


TOKEN = HydraReadToken('ep', 'run', 3, 'a' * 64)
OBJ = NativeNodeRef(TOKEN, 'O(0)', 2)


class FakeMesh:
    def num_vertices(self):
        return 4

    def pos(self, index):
        return np.array([index, index + 1, index + 2], dtype=np.float32)


def fixture(*, indices=(0, 2, 3), feature=None, layer=2):
    node = SimpleNamespace(id='O(0)', layer=layer, attributes=SimpleNamespace(
        mesh_connections=indices, position=[1, 2, 3], last_update_time_ns=10,
        is_active=True, is_predicted=False, semantic_feature=(
            np.empty((0, 0), dtype=np.float32) if feature is None else feature)))
    return SimpleNamespace(get_node=lambda key: node, mesh=FakeMesh())


def test_mesh_ref_has_a_bounded_page_and_checksum(tmp_path):
    result = parse_detail(extract_detail(fixture(), NativeDetailRequest(OBJ, 'mesh', 1, 1),
                                        AssetStore(tmp_path), mesh_generation='b' * 64))
    assert result.status == 'available'
    asset = result.value
    assert asset.mesh_generation == 'b' * 64
    assert asset.offset == 1 and asset.total_rows == 3
    assert dict(read_asset(tmp_path, asset, OBJ, expected_mesh_generation='b'*64))['indices'].tolist() == [2]
    assert dict(read_asset(tmp_path, asset, OBJ, expected_mesh_generation='b'*64))['xyz'].tolist() == [[2, 3, 4]]
    with pytest.raises(ValueError, match='identity'):
        read_asset(tmp_path, asset, replace(OBJ, token=replace(TOKEN, episode_id='other')))
    (tmp_path / asset.key).write_bytes(b'bad')
    with pytest.raises(ValueError, match='checksum|size'):
        read_asset(tmp_path, asset, OBJ, expected_mesh_generation='b'*64)


def test_native_defaults_wrong_layer_and_invalid_indices_fail_safely(tmp_path):
    store = AssetStore(tmp_path)
    def extract(graph, kind, **kwargs):
        return parse_detail(extract_detail(graph, NativeDetailRequest(OBJ, kind), store,
                                           mesh_generation='b'*64, **kwargs))
    assert extract(fixture(), 'feature').status == 'missing'
    assert extract(fixture(indices=(4,)), 'mesh').status == 'corrupt'
    assert extract(fixture(layer=3), 'attributes').status == 'unavailable'
    assert extract(fixture(feature=np.zeros((2, 3), dtype=np.float64)),
                   'feature', feature_spec_id='fixture').status == 'corrupt'
    assert extract(fixture(feature=np.ones((2, 3), dtype=np.float32)),
                   'feature').status == 'unavailable'
    feature = extract(fixture(feature=np.ones((2, 3), dtype=np.float32)),
                      'feature', feature_spec_id='fixture').value
    assert feature.shape == (2, 3) and feature.spec_id == 'fixture'


def test_saved_reader_rejects_wrong_pin_unknown_header_and_modified_bytes(tmp_path):
    import hashlib
    import json

    target = tmp_path / 'graph.sparkdsg'
    target.write_bytes(b'not a supported header')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(dict(schema_version=1, complete=True,
        episode_id='ep', run_id='run', graph_revision=3, input_prefix_sha256='a' * 64,
        graph_path=str(target), graph_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        graph_bytes=target.stat().st_size)))
    reader = SavedHydraDetailReader(manifest, TOKEN, AssetStore(tmp_path/'assets'),
                                    graph_loader=lambda path: pytest.fail('loader called without valid header'))
    assert reader.read(NativeDetailRequest(OBJ, 'attributes')).status == 'corrupt'
    assert reader.read(NativeDetailRequest(replace(OBJ, token=replace(TOKEN, graph_revision=4)),
                                           'attributes')).status == 'stale'
    target.write_bytes(b'modified')
    assert reader.read(NativeDetailRequest(OBJ, 'attributes')).status == 'corrupt'


def test_token_accepts_git_sha1_provenance():
    assert replace(TOKEN, source_sha256='2e58a35baea629eee8838409771876acff015daf').source_sha256
    with pytest.raises(ValueError):
        replace(TOKEN, source_sha256='z' * 40)


def test_mesh_generation_must_be_verified_by_the_caller(tmp_path):
    request = NativeDetailRequest(OBJ, 'mesh')
    result = parse_detail(extract_detail(fixture(), request, AssetStore(tmp_path),
                                        mesh_generation='b' * 64), request)
    assert read_asset(tmp_path, result.value, OBJ, expected_mesh_generation='b'*64)['xyz'].shape == (3, 3)
    with pytest.raises(ValueError, match='generation'):
        read_asset(tmp_path, result.value, OBJ, expected_mesh_generation='c'*64)


@pytest.mark.parametrize('kind', ['OBB', 'RAABB'])
def test_rotated_box_preserves_native_dimensions_and_uses_all_corners(tmp_path, kind):
    from itertools import product

    dim = np.array([2., 1., 1.])
    center = np.array([3., 4., 1.])
    c = np.sqrt(.5)
    rotation = np.array([[c, -c, 0.], [c, c, 0.], [0., 0., 1.]])
    corners = (np.array(list(product((-1, 1), repeat=3))) * dim / 2) @ rotation.T + center
    graph = fixture()
    attrs = graph.get_node('O(0)').attributes
    attrs.bounding_box = SimpleNamespace(type=kind, dimensions=dim, world_P_center=center,
        world_R_center=rotation, is_valid=lambda: True, corners=lambda: corners)
    result = parse_detail(extract_detail(graph, NativeDetailRequest(OBJ, 'bbox'),
                                        AssetStore(tmp_path), mesh_generation='b'*64))
    assert result.value['kind'] == kind
    assert result.value['dimensions_m'] == (2., 1., 1.)
    lower, upper = result.value['envelope']
    assert np.allclose(np.subtract(upper, lower), [3 * c, 3 * c, 1.])


def test_asset_quota_eviction_cannot_read_a_stale_binary(tmp_path):
    store = AssetStore(tmp_path, item_cap=1, byte_cap=1024)
    request = NativeDetailRequest(OBJ, 'mesh', limit=1)
    one = parse_detail(extract_detail(fixture(indices=(0,)), request, store, mesh_generation='b'*64))
    two = parse_detail(extract_detail(fixture(indices=(1,)), request, store, mesh_generation='b'*64))
    assert store.evictions == 1 and store.bytes == two.value.nbytes
    assert not (tmp_path / one.value.key).exists()
