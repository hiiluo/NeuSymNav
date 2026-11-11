"""Child-process Hydra pipeline loop; native bindings are imported only here."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import traceback

import numpy as np

from ...contracts import HydraFrame, dumps, loads


PROTOCOL_VERSION = 1
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_GRAPH_SUMMARY_BYTES = 16 * 1024 * 1024
MAX_GRAPH_NODES = 100_000
MAX_GRAPH_EDGES = 300_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _emit(message: dict):
    sys.stdout.write(json.dumps(message, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n')
    sys.stdout.flush()


def _graph_summary(graph, *, graph_revision: int, input_prefix_sha256: str) -> dict:
    """Return a bounded complete ID/position/edge snapshot from Spark-DSG."""
    nodes=[];native_ids=set();native_values={};parents=[];layer_counts={};raw_edges=[]
    for layer in graph.layers:
        layer_id=int(layer.id);key=str(layer_id);layer_nodes=list(layer.nodes)
        layer_counts[key]=len(layer_nodes)
        for node in layer_nodes:
            symbol=node.id
            native_id=str(symbol)
            if native_id in native_ids:raise ValueError('Spark-DSG summary has duplicate native IDs')
            native_ids.add(native_id)
            value=getattr(symbol,'value',None)
            if type(value) is int:
                if value in native_values and native_values[value]!=native_id:
                    raise ValueError('Spark-DSG summary has duplicate native symbol values')
                native_values[value]=native_id
            attributes=node.attributes
            position=getattr(attributes,'position',None)
            position=None if position is None else np.asarray(position,dtype=np.float64).reshape(-1).tolist()
            if position is not None and (len(position)!=3 or not np.isfinite(position).all()):position=None
            label=getattr(attributes,'name',None)
            if not isinstance(label,str) or not label:label=str(getattr(attributes,'semantic_label','')) or None
            semantic_label=getattr(attributes,'semantic_label',None)
            semantic_label=(int(semantic_label)
                if isinstance(semantic_label,(int,np.integer)) and not isinstance(semantic_label,(bool,np.bool_))
                and 0<=int(semantic_label)<2**32 else None)
            parent=node.get_parent() if callable(getattr(node,'get_parent',None)) else None
            nodes.append(dict(native_id=native_id,layer_id=layer_id,name=label,semantic_label=semantic_label,position=position,
                              parent_native_id=None))
            parents.append(parent)
            if len(nodes)>MAX_GRAPH_NODES:raise ValueError('Spark-DSG node summary exceeds 100000 nodes')
        for edge in layer.edges:
            raw_edges.append((native_values.get(edge.source,str(edge.source)),
                              native_values.get(edge.target,str(edge.target)),'intralayer'))
    for node,parent in zip(nodes,parents):
        if parent is None:continue
        # Spark-DSG Node.get_parent() exposes the NodeSymbol's packed uint64
        # value, while node.id stringifies to its display symbol (for example,
        # ``R(0)``). Resolve through the complete snapshot so endpoints share
        # the same canonical ID representation.
        node['parent_native_id']=(native_values.get(parent,str(parent))
                                  if type(parent) is int else str(parent))
    for edge in graph.interlayer_edges:
        raw_edges.append((native_values.get(edge.source,str(edge.source)),
                          native_values.get(edge.target,str(edge.target)),'interlayer'))
    edges=[dict(source_native_id=source,target_native_id=target,kind=kind)
           for source,target,kind in raw_edges if source in native_ids and target in native_ids]
    if len(edges)>MAX_GRAPH_EDGES:raise ValueError('Spark-DSG edge summary exceeds 300000 edges')
    result=dict(schema_version=1,graph_revision=graph_revision,
        input_prefix_sha256=input_prefix_sha256,layer_counts=layer_counts,nodes=nodes,edges=edges)
    if len(json.dumps(result,separators=(',',':'),allow_nan=False).encode('utf-8'))>MAX_GRAPH_SUMMARY_BYTES:
        raise ValueError('Spark-DSG summary exceeds 16 MiB')
    return result


class _PipelineOwner:
    def __init__(self, config_root: Path, artifact_dir: Path):
        self.config_root = config_root.resolve()
        self.artifact_dir = artifact_dir.resolve()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.pipeline = None
        self.sensor_id = None
        self.calibration_hash = None
        self.labelspace_hash = None
        self.labelspace_id = None
        self.capture_clock_domain = None
        self.last_source = None
        self.graph_revision = 0
        self.input_prefix = None
        self.config_hash = _sha256(self.config_root / 'datasets' / 'neusymnav.yaml')
        prefix = os.environ.get('CMAKE_PREFIX_PATH', '').split(os.pathsep)[0]
        hydra_root = Path(prefix).parents[1] / 'src' / 'hydra' if prefix else Path('.')
        try:
            self.source_revision = subprocess.check_output(
                ['git', '-C', str(hydra_root), 'rev-parse', 'HEAD'], text=True,
                stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.SubprocessError):
            self.source_revision = None
        self.binding_hash = None
        self.native_binding_hash = None
        self.room_stability_bridge = None
        labelspace_file = self.config_root / 'label_spaces' / 'neusymnav_label_space.yaml'
        self.labelspace_config_hash = _sha256(labelspace_file)
        comment = labelspace_file.read_text(encoding='utf-8')
        self.labelspace_id = 'neusymnav:hydra-labelspace:v1'
        marker = '# NeuSymNav labelspace SHA256: '
        self.labelspace_hash = next((line[len(marker):].strip() for line in comment.splitlines()
                                     if line.startswith(marker)), None)
        if not self.labelspace_hash:
            raise ValueError('custom labelspace config is missing its content hash')

    def _initialize(self, frame: HydraFrame):
        # These imports intentionally occur inside the worker process.
        import yaml
        from scipy.spatial.transform import Rotation
        from .room_stability import create_room_stability_bridge
        self.room_stability_bridge = create_room_stability_bridge(self.config_root)
        import hydra_python._hydra_bindings as hydra_bindings
        if self.room_stability_bridge is not None:
            self.room_stability_bridge.validate_loaded_library()
        ExtrinsicsConfig, HydraPipeline = hydra_bindings.ExtrinsicsConfig, hydra_bindings.HydraPipeline
        from hydra_python.pipeline import load_configs, make_camera

        config = load_configs('neusymnav', labelspace='neusymnav', config_path=self.config_root)
        if config is None:
            raise ValueError('Hydra config loader rejected the NeuSymNav profile')
        config.pop('neusymnav_room_stability', None)
        config['default_num_threads'] = 2
        extrinsics = ExtrinsicsConfig()
        x, y, z, w = Rotation.from_matrix(frame.body_T_camera[:3, :3]).as_quat()
        q = extrinsics.body_R_sensor
        q.w, q.x, q.y, q.z = float(w), float(x), float(y), float(z)
        extrinsics.body_R_sensor = q
        extrinsics.body_p_sensor = frame.body_T_camera[:3, 3]
        h, w_img = frame.depth_m.shape
        sensor = make_camera(fx=float(frame.K[0, 0]), fy=float(frame.K[1, 1]),
            cx=float(frame.K[0, 2]), cy=float(frame.K[1, 2]), width=w_img,
            height=h, min_range=.1, max_range=5., name='primary_rgbd', extrinsics=extrinsics)
        self.pipeline = HydraPipeline.from_config(yaml.safe_dump(config), sensor,
            robot_id=0, config_verbosity=0, use_step_mode=True, zmq_url='')
        self.native_binding_hash = _sha256(Path(hydra_bindings.__file__).resolve())
        self.binding_hash = (self.room_stability_bridge.build_sha256(self.native_binding_hash)
            if self.room_stability_bridge is not None else self.native_binding_hash)
        self.sensor_id = frame.source_key.sensor_id
        self.calibration_hash = frame.calibration_hash
        self.capture_clock_domain = frame.clock_domain

    def process_frame(self, frame: HydraFrame) -> dict:
        if frame.labelspace_id != self.labelspace_id or frame.labelspace_hash != self.labelspace_hash:
            raise ValueError('frame labelspace id/hash disagrees with loaded custom labelspace')
        if self.pipeline is None:
            self._initialize(frame)
        if frame.source_key.sensor_id != self.sensor_id or frame.calibration_hash != self.calibration_hash:
            raise ValueError('worker frame sensor or calibration changed within episode')
        if frame.clock_domain != self.capture_clock_domain:
            raise ValueError('worker capture clock domain changed within episode')
        if self.last_source is not None:
            from ...contracts.hydra_graph import validate_hydra_frame_order
            validate_hydra_frame_order(self.last_source, frame)
        accepted = bool(self.pipeline.step(frame.capture_monotonic_ns,
            frame.world_t_body, frame.world_R_body_wxyz, frame.depth_m, frame.labels, frame.rgb))
        if accepted:
            self.graph_revision += 1
            previous = bytes.fromhex(self.input_prefix) if self.input_prefix else b''
            self.input_prefix = hashlib.sha256(previous + dumps(frame).encode('utf-8')).hexdigest()
            self.last_source = frame
        result={'accepted': accepted, 'graph_revision': self.graph_revision,
            'input_prefix_sha256': self.input_prefix,
            'last_source': None if self.last_source is None else {
                'episode_id': self.last_source.source_key.episode_id,
                'sensor_id': self.last_source.source_key.sensor_id,
                'frame_index': self.last_source.source_key.frame_index,
                'capture_monotonic_ns': self.last_source.capture_monotonic_ns,
                'clock_domain': self.last_source.clock_domain}}
        if accepted:
            result['graph_summary']=_graph_summary(self.pipeline.graph,
                graph_revision=self.graph_revision,input_prefix_sha256=self.input_prefix)
        if accepted and getattr(self, 'binding_hash', None):
            result['native_metadata'] = self._native_metadata()
            bridge = getattr(self, 'room_stability_bridge', None)
            if bridge is not None:
                result['room_stability_diagnostics'] = bridge.diagnostics()
        return result

    def _native_metadata(self) -> dict:
        bridge = self.room_stability_bridge
        return {'config_sha256': self.config_hash, 'source_sha256': self.source_revision,
            'build_sha256': self.binding_hash, 'native_binding_sha256': self.native_binding_hash,
            'room_stability': None if bridge is None else bridge.metadata}

    def save(self) -> dict:
        if self.pipeline is None:
            return {'asset_path': None, 'asset_sha256': None, 'asset_bytes': 0,
                    'graph_revision': 0}
        target = self.artifact_dir / 'hydra-graph.sparkdsg'
        self.pipeline.save_graph(str(target), True)
        size = target.stat().st_size
        if size > MAX_ASSET_BYTES:
            target.unlink(missing_ok=True)
            raise RuntimeError('Hydra graph asset exceeds 128 MiB')
        graph = self.pipeline.graph
        layer_counts = {str(layer.id): len(list(layer.nodes)) for layer in graph.layers}
        return {'asset_path': str(target), 'asset_sha256': _sha256(target),
            'asset_bytes': size, 'graph_revision': self.graph_revision,
            'input_prefix_sha256': self.input_prefix, 'layer_counts': layer_counts,
            'edge_count': sum(len(list(layer.edges)) for layer in graph.layers),
            'config_sha256': self.config_hash,
            'source_sha256': self.source_revision, 'build_sha256': self.binding_hash,
            'labelspace_config_sha256': self.labelspace_config_hash,
            **self._native_metadata()}

    def close(self) -> dict:
        result = self.save()
        self.pipeline = None
        gc.collect()
        return result


def serve(config_root: Path, artifact_dir: Path) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    # Native work stays in this child; cap numerical library fan-out as well.
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    owner = _PipelineOwner(config_root, artifact_dir)
    _emit({'type': 'ready', 'protocol': PROTOCOL_VERSION,
           'config_sha256': owner.config_hash,
           'labelspace_config_sha256': owner.labelspace_config_hash,
           'labelspace_id': owner.labelspace_id,
           'labelspace_hash': owner.labelspace_hash,
           'source_sha256': owner.source_revision,
           'hydra_num_threads': 2, 'blas_openmp_threads': 1})
    for line in sys.stdin.buffer:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError('request must be a JSON object')
            if request.get('type') == 'close':
                result = owner.close()
                _emit({'type': 'closed', **result})
                return 0
            if request.get('type') != 'frame' or not isinstance(request.get('request_id'), str):
                raise ValueError('unsupported worker request')
            frame = loads(request.get('frame', ''))
            if not isinstance(frame, HydraFrame):
                raise ValueError('frame wire payload is not HydraFrame')
            result = owner.process_frame(frame)
            _emit({'type': 'result', 'request_id': request['request_id'], **result})
        except BaseException as exc:
            _emit({'type': 'error', 'request_id': request.get('request_id') if 'request' in locals() else None,
                   'error': f'{type(exc).__name__}: {exc}'})
            traceback.print_exc(file=sys.stderr)
    owner.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--config-root', required=True, type=Path)
    parser.add_argument('--artifact-dir', required=True, type=Path)
    args = parser.parse_args(argv)
    return serve(args.config_root, args.artifact_dir)


if __name__ == '__main__':
    raise SystemExit(main())
