"""Revision-scoped reads and bounded binary payloads for native Hydra graphs."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from tempfile import NamedTemporaryFile, TemporaryDirectory
from threading import Lock
from types import MappingProxyType

import numpy as np

from ...contracts.hydra_graph import HydraReadResult, HydraReadToken, NativeDetailRequest, NativeNodeRef


MAX_DETAIL_ASSET = 1024 * 1024
MAX_SAVED_GRAPH = 16 * 1024 * 1024
MAX_DETAIL_RESULT = 32 * 1024
_MESH_DTYPE = np.dtype([('indices', '<u8'), ('xyz', '<f4', (3,))])
_HEX = re.compile(r'[a-f0-9]{64}')
_NATIVE_SYMBOL = re.compile(r'([A-Za-z])\(([0-9]{1,17})\)')


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _wire_identity(node):
    return _digest(json.dumps(asdict(node), sort_keys=True, separators=(',', ':')).encode())


def mesh_generation(token):
    return _digest(json.dumps(asdict(token), sort_keys=True, separators=(',', ':')).encode())


@dataclass(frozen=True, slots=True)
class HydraBinaryRef:
    key: str
    sha256: str
    nbytes: int
    codec: str
    shape: tuple[int, ...]
    dtype: str
    identity_sha256: str
    mesh_generation: str | None
    offset: int
    total_rows: int
    spec_id: str | None = None

    def __post_init__(self):
        if (not isinstance(self.sha256, str) or not _HEX.fullmatch(self.sha256)
                or self.key != f'{self.sha256}.bin'
                or not isinstance(self.identity_sha256, str) or not _HEX.fullmatch(self.identity_sha256)):
            raise ValueError('invalid binary asset identity')
        if (not isinstance(self.shape, tuple) or not self.shape or
                any(type(size) is not int or size <= 0 for size in self.shape)):
            raise ValueError('invalid binary asset shape')
        if self.codec == 'hydra_mesh_xyz_v1':
            if (self.dtype != 'u64_xyz_f32_le' or len(self.shape) != 1 or self.shape[0] > 64
                    or not isinstance(self.mesh_generation, str) or not _HEX.fullmatch(self.mesh_generation)
                    or self.spec_id is not None):
                raise ValueError('invalid mesh payload schema')
            itemsize = _MESH_DTYPE.itemsize
        elif self.codec == 'hydra_feature_f32_v1':
            if (self.dtype != '<f4' or len(self.shape) != 2 or self.mesh_generation is not None
                    or not isinstance(self.spec_id, str) or not 1 <= len(self.spec_id) <= 256):
                raise ValueError('invalid feature payload schema')
            itemsize = 4
        else:
            raise ValueError('unsupported binary codec')
        if (type(self.nbytes) is not int or self.nbytes != math.prod(self.shape) * itemsize
                or not 0 < self.nbytes <= MAX_DETAIL_ASSET or type(self.offset) is not int
                or self.offset < 0 or type(self.total_rows) is not int
                or self.total_rows < self.offset + self.shape[0]):
            raise ValueError('invalid binary asset size or bounds')


class AssetStore:
    """One writer, bounded by bytes and item count. Readers verify the digest."""

    def __init__(self, root, *, byte_cap=8 * 1024 * 1024, item_cap=128):
        if type(byte_cap) is not int or byte_cap <= 0 or type(item_cap) is not int or item_cap <= 0:
            raise ValueError('asset quota must be positive')
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.byte_cap = byte_cap
        self.item_cap = item_cap
        self.entries = OrderedDict()
        for path in self.root.glob('*.bin'):
            if _HEX.fullmatch(path.stem) and not path.is_symlink() and path.is_file():
                self.entries[path.name] = path.stat().st_size
        self.bytes = sum(self.entries.values())
        self.evictions = 0
        self._trim(0, 0)

    def _trim(self, nbytes, items):
        while self.bytes + nbytes > self.byte_cap or len(self.entries) + items > self.item_cap:
            key, size = self.entries.popitem(last=False)
            (self.root / key).unlink(missing_ok=True)
            self.bytes -= size
            self.evictions += 1

    def put(self, data):
        if len(data) > min(self.byte_cap, MAX_DETAIL_ASSET):
            raise ValueError('binary detail asset exceeds quota')
        sha = _digest(data)
        key = f'{sha}.bin'
        if key in self.entries:
            self.entries.move_to_end(key)
            return key, sha
        self._trim(len(data), 1)
        with NamedTemporaryFile(dir=self.root, prefix='.asset-', delete=False) as file:
            temp = Path(file.name)
            try:
                file.write(data)
                file.flush()
                temp.replace(self.root / key)
            finally:
                temp.unlink(missing_ok=True)
        self.entries[key] = len(data)
        self.bytes += len(data)
        return key, sha


def _bounded_bytes(path, cap):
    with path.open('rb') as stream:
        data = stream.read(cap + 1)
    if len(data) > cap:
        raise ValueError('asset exceeds size cap')
    return data


def read_asset(root, ref: HydraBinaryRef, expected_node: NativeNodeRef, *, expected_mesh_generation=None):
    """Decode only the requested asset. Call from the worker/IO lane."""
    if _wire_identity(expected_node) != ref.identity_sha256:
        raise ValueError('asset identity differs from the requested node')
    if ref.codec == 'hydra_mesh_xyz_v1' and ref.mesh_generation != expected_mesh_generation:
        raise ValueError('mesh generation differs from the pinned mesh')
    root = Path(root).resolve()
    path = (root / ref.key).resolve()
    if path.parent != root or path.name != ref.key:
        raise ValueError('asset path escapes its root')
    data = _bounded_bytes(path, ref.nbytes)
    if len(data) != ref.nbytes or _digest(data) != ref.sha256:
        raise ValueError('binary asset size or checksum mismatch')
    if ref.codec == 'hydra_mesh_xyz_v1':
        records = np.frombuffer(data, dtype=_MESH_DTYPE)
        return MappingProxyType({'indices': records['indices'], 'xyz': records['xyz']})
    return np.frombuffer(data, dtype='<f4').reshape(ref.shape)


def decode_asset(root, asset, node, generation):
    try:
        return HydraReadResult('available', read_asset(root, asset, node,
                                                      expected_mesh_generation=generation))
    except FileNotFoundError:
        return HydraReadResult('evicted', reason='detail_asset_missing')
    except (AttributeError, TypeError, ValueError, OSError):
        return HydraReadResult('corrupt', reason='detail_asset_verification_failed')


def _lookup(graph, ref):
    if hasattr(graph, 'get_layer_key'):
        from spark_dsg import NodeSymbol

        match = _NATIVE_SYMBOL.fullmatch(ref.native_id)
        if match is None or int(match[2]) >= 2**56:
            return None
        node = graph.find_node(NodeSymbol(match[1], int(match[2])))
    else:
        node = graph.get_node(ref.native_id)
    if node is not None and str(node.id) == ref.native_id and node.layer == ref.layer_id:
        return node
    return None


def _response(status, value=None, reason=None):
    return dict(status=status, value=value, reason=reason)


def _box(attrs):
    box = getattr(attrs, 'bounding_box', None)
    if box is None or not box.is_valid():
        return None
    corners = np.asarray(box.corners())
    dimensions = np.asarray(box.dimensions)
    center = np.asarray(box.world_P_center)
    rotation = np.asarray(box.world_R_center)
    arrays = (corners, dimensions, center, rotation)
    if (tuple(a.shape for a in arrays) != ((8, 3), (3,), (3,), (3, 3))
            or not all(np.isfinite(a).all() for a in arrays) or np.any(dimensions <= 0)):
        raise ValueError('invalid native bounding box')
    return dict(kind=str(box.type).split('.')[-1], dimensions_m=dimensions.tolist(),
                center_xyz_m=center.tolist(), world_R_box=rotation.tolist(),
                corners_xyz_m=corners.tolist(), envelope=(corners.min(0).tolist(), corners.max(0).tolist()))


def _attributes(node):
    attrs = node.attributes
    stamp = int(attrs.last_update_time_ns)
    values = dict(native_last_update_time_ns=stamp if stamp > 0 else None,
                  native_is_active=bool(attrs.is_active), native_is_predicted=bool(attrs.is_predicted),
                  provenance='native_raw_flags_and_update_time')
    if node.layer == 2:
        values.update(bbox=_box(attrs), mesh_connection_count=len(attrs.mesh_connections))
    elif node.layer == 3:
        distance = float(attrs.distance)
        values.update(gvd_distance_m=distance if attrs.real_place and math.isfinite(distance)
                      and distance > 0 else None, num_basis_points=int(attrs.num_basis_points),
                      real_place=bool(attrs.real_place), active_frontier=bool(attrs.active_frontier),
                      anti_frontier=bool(attrs.anti_frontier),
                      frontier_scale=None, num_frontier_voxels=None, frontier_status='not_recorded')
        if not attrs.real_place and attrs.num_frontier_voxels > 0:
            scale = np.asarray(attrs.frontier_scale)
            if scale.shape != (3,) or not np.isfinite(scale).all():
                raise ValueError('invalid frontier scale')
            values.update(frontier_scale=scale.tolist(), num_frontier_voxels=int(attrs.num_frontier_voxels),
                          frontier_status='native_geometry')
    elif node.layer == 4:
        # Spark-DSG does not carry the producer or calibration for this map.
        values.update(semantic_class_probabilities=None,
                      native_probability_entries=len(attrs.semantic_class_probabilities))
    return values


def extract_detail(graph, request: NativeDetailRequest, store: AssetStore, *, mesh_generation,
                   feature_spec_id=None):
    """Extract a bounded record from the already-pinned graph, without mutating it."""
    try:
        node = _lookup(graph, request.node)
        if node is None:
            return _response('unavailable', reason='node_or_layer_mismatch')
        attrs = node.attributes
        kind = request.kind
        if kind == 'attributes':
            return _response('available', _attributes(node))
        if kind == 'bbox':
            box = _box(attrs)
            return _response('available', box) if box is not None else _response('missing', reason='no_native_bbox')
        if kind == 'edge':
            target = _lookup(graph, request.target)
            if target is None:
                return _response('unavailable', reason='edge_target_or_layer_mismatch')
            edge = graph.find_edge(node.id, target.id)
            if edge is None:
                return _response('missing', reason='no_structural_edge')
            info = edge.info
            weight = float(info.weight) if info.weighted else None
            if weight is not None and not math.isfinite(weight):
                raise ValueError('non-finite native edge weight')
            return _response('available', dict(weighted=bool(info.weighted), weight=weight,
                weight_kind='native_untyped' if info.weighted else 'unweighted'))
        if kind == 'mesh':
            if node.layer != 2:
                return _response('unavailable', reason='not_object_mesh_namespace')
            indices = attrs.mesh_connections
            if not indices or graph.mesh is None or request.offset >= len(indices):
                return _response('missing', reason='no_mesh_page')
            ids = indices[request.offset:request.offset + request.limit]
            mesh = graph.mesh
            if any(type(i) is not int or not 0 <= i < mesh.num_vertices() for i in ids):
                raise ValueError('mesh index outside pinned mesh')
            records = np.empty(len(ids), dtype=_MESH_DTYPE)
            records['indices'] = ids
            records['xyz'] = [mesh.pos(i) for i in ids]
            if not np.isfinite(records['xyz']).all():
                raise ValueError('non-finite mesh position')
            data, shape, codec, dtype = records.tobytes(), records.shape, 'hydra_mesh_xyz_v1', 'u64_xyz_f32_le'
            total, generation, spec_id = len(indices), mesh_generation, None
        else:
            feature = getattr(attrs, 'semantic_feature', None)
            if feature is None or feature.size == 0:
                return _response('missing', reason='no_native_feature')
            if feature.ndim != 2 or feature.dtype != np.float32 or feature.nbytes > MAX_DETAIL_ASSET:
                raise ValueError('invalid native feature shape or dtype')
            if feature_spec_id is None:
                return _response('unavailable', reason='native_feature_spec_unverified')
            if not np.isfinite(feature).all():
                raise ValueError('non-finite native feature')
            data, shape, codec, dtype = feature.astype('<f4', copy=False).tobytes(), feature.shape, 'hydra_feature_f32_v1', '<f4'
            total, generation, spec_id = shape[0], None, feature_spec_id
        key, sha = store.put(data)
        ref = HydraBinaryRef(key, sha, len(data), codec, shape, dtype, _wire_identity(request.node),
                             generation, request.offset, total, spec_id)
        return _response('available', dict(asset=asdict(ref)))
    except (AttributeError, IndexError, KeyError, TypeError, ValueError, OverflowError, RuntimeError):
        return _response('corrupt', reason='invalid_native_detail')
    except OSError:
        return _response('unavailable', reason='detail_asset_io_error')


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def parse_detail(payload, request=None):
    if len(json.dumps(payload, allow_nan=False)) > MAX_DETAIL_RESULT:
        raise ValueError('Hydra detail response exceeds its cap')
    status, raw, reason = payload['status'], payload['value'], payload['reason']
    if isinstance(raw, dict) and 'asset' in raw:
        asset = dict(raw['asset'])
        asset['shape'] = tuple(asset['shape'])
        value = HydraBinaryRef(**asset)
        if request is not None:
            kind = 'mesh' if value.codec == 'hydra_mesh_xyz_v1' else 'feature'
            if (value.identity_sha256 != _wire_identity(request.node) or request.kind != kind
                    or value.offset != request.offset
                    or (kind == 'mesh' and value.shape[0] > request.limit)):
                raise ValueError('detail asset identity or bounds differ from request')
    else:
        if status == 'available' and request is not None and request.kind in ('mesh', 'feature'):
            raise ValueError('binary detail must return an asset reference')
        value = _freeze(raw)
    return HydraReadResult(status, value, reason)


def export_token(manifest):
    return HydraReadToken(manifest['episode_id'], manifest['run_id'], manifest['graph_revision'],
                          manifest['input_prefix_sha256'], manifest.get('world_epoch'),
                          manifest.get('source_sha256'), manifest.get('build_sha256'), manifest.get('config_sha256'))


def _supported_header(data):
    prefix = b'\xdd\x09\x00\x00\x00SPARK_DSG\xdd\x04\x00\x00\x00main'
    if not data.startswith(prefix) or len(data) < len(prefix) + 7:
        return False
    header = data[len(prefix):len(prefix) + 6]
    return header[::2] == b'\xcc\xcc\xcc' and (1, 0, 0) <= tuple(header[1::2]) <= (1, 1, 3)


class SavedHydraDetailReader:
    """Explicit historical reader for one trusted export manifest and one resident graph."""

    historical = True

    def __init__(self, manifest_path, expected_token: HydraReadToken, assets: AssetStore,
                 *, graph_loader=None, feature_spec_id=None):
        self.manifest_path = Path(manifest_path).resolve()
        self.token = expected_token
        self.assets = assets
        self._load = graph_loader
        self._feature_spec_id = feature_spec_id
        self._graph = None
        self._sha = None
        self._lock = Lock()
        self._closed = False

    def _open(self):
        manifest = json.loads(_bounded_bytes(self.manifest_path, 8 * 1024 * 1024))
        if manifest.get('schema_version') != 1 or manifest.get('complete') is not True:
            raise ValueError('unsupported or incomplete export manifest')
        if export_token(manifest) != self.token:
            raise ValueError('export manifest identity mismatch')
        root = self.manifest_path.parent
        path = (root / manifest['graph_path']).resolve()
        if path.parent != root or path.suffix != '.sparkdsg':
            raise ValueError('expected a graph file next to the manifest')
        size = manifest['graph_bytes']
        if type(size) is not int or not 0 < size <= MAX_SAVED_GRAPH:
            raise ValueError('saved graph exceeds the read budget')
        data = _bounded_bytes(path, size)
        sha = _digest(data)
        if len(data) != size or sha != manifest['graph_sha256'] or not _supported_header(data):
            raise ValueError('saved graph size, digest or version mismatch')
        if self._load is None:
            from spark_dsg import DynamicSceneGraph

            load = DynamicSceneGraph.load
        else:
            load = self._load
        # Decode exactly the bytes verified above, even if the original is replaced.
        with TemporaryDirectory(prefix='hna-verified-') as directory:
            staged = Path(directory) / 'graph.sparkdsg'
            staged.write_bytes(data)
            graph = load(str(staged))
        if graph is None or (graph.mesh is not None and graph.mesh.total_bytes() > 64 * 1024 * 1024):
            raise ValueError('invalid or over-budget decoded graph')
        self._graph, self._sha = graph, sha

    def close(self):
        with self._lock:
            self._closed = True
            self._graph = None

    def read_asset(self, node, asset):
        if node.token != self.token:
            return HydraReadResult('stale', reason='export_token_mismatch')
        with self._lock:
            if self._closed or self._graph is None:
                return HydraReadResult('evicted', reason='saved_graph_not_resident')
            return decode_asset(self.assets.root, asset, node, self._sha)

    def read(self, request):
        if request.node.token != self.token:
            return HydraReadResult('stale', reason='export_token_mismatch')
        with self._lock:
            if self._closed:
                return HydraReadResult('evicted', reason='saved_reader_closed')
            try:
                if self._graph is None:
                    self._open()
                return parse_detail(extract_detail(self._graph, request, self.assets,
                    mesh_generation=self._sha, feature_spec_id=self._feature_spec_id), request)
            except FileNotFoundError:
                return HydraReadResult('evicted', reason='saved_graph_missing')
            except (AttributeError, KeyError, OSError, TypeError, ValueError, RuntimeError):
                return HydraReadResult('corrupt', reason='saved_graph_verification_failed')
