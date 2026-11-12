import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from contract_helpers import observation
from neusymnav.contracts.observations import Taxonomy
from neusymnav.perception.detector_client import validate_recipe
from neusymnav.perception.yoloe import YOLOEDetector


def _asset(path, data):
    path.write_bytes(data)
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(data).hexdigest())


def _recipe(tmp_path, *, taxonomy=None):
    tax = taxonomy or Taxonomy('v1', ('chair',), {}, 'fixture vocabulary')
    checkpoint = _asset(tmp_path/'yoloe-26m-seg.pt', b'checkpoint')
    encoder = _asset(tmp_path/'mobileclip2_b.ts', b'encoder')
    taxonomy_path = tmp_path/'taxonomy.json'
    taxonomy_path.write_text(json.dumps(dict(schema_version=1, vocabulary_id=tax.vocabulary_id,
        categories=list(tax.categories), aliases=dict(tax.aliases), provenance=tax.provenance)))
    taxonomy_asset = dict(path=str(taxonomy_path.resolve()),
                          sha256=hashlib.sha256(taxonomy_path.read_bytes()).hexdigest())
    xml = _asset(tmp_path/'model.xml', b'<net/>')
    binary = _asset(tmp_path/'model.bin', b'weights')
    metadata = dict(checkpoint_sha256=checkpoint['sha256'], encoder_sha256=encoder['sha256'],
        taxonomy_sha256=taxonomy_asset['sha256'], prompt_count=len(tax.categories),
        end2end_preserved=True, export_format='OpenVINO IR')
    meta_path = tmp_path/'model-metadata.json'
    meta_path.write_text(json.dumps(metadata))
    meta = dict(path=str(meta_path.resolve()), sha256=hashlib.sha256(meta_path.read_bytes()).hexdigest())
    return dict(checkpoint_path=checkpoint['path'], checkpoint_sha256=checkpoint['sha256'],
        encoder_path=encoder['path'], encoder_sha256=encoder['sha256'],
        taxonomy_path=taxonomy_asset['path'], taxonomy_sha256=taxonomy_asset['sha256'],
        checkpoint_license='fixture', imgsz=640, max_detections=30,
        confidence_threshold=.25, device='intel:gpu', backend='openvino_gpu',
        openvino_model_path=xml['path'], openvino_model_sha256=xml['sha256'],
        openvino_bin_path=binary['path'], openvino_bin_sha256=binary['sha256'],
        openvino_metadata_path=meta['path'], openvino_metadata_sha256=meta['sha256']), tax


def test_openvino_recipe_requires_hash_pinned_ir_and_matching_provenance(tmp_path):
    recipe, _ = _recipe(tmp_path)
    validated = validate_recipe(recipe)
    assert validated['backend'] == 'openvino_gpu'
    assert validated['openvino_model_path'].endswith('model.xml')
    assert validated['openvino_bin_path'].endswith('model.bin')


def test_openvino_recipe_rejects_static_prompt_model_for_another_taxonomy(tmp_path):
    recipe, _ = _recipe(tmp_path)
    metadata_path = recipe['openvino_metadata_path']
    metadata = json.loads(open(metadata_path).read())
    metadata['taxonomy_sha256'] = '0'*64
    open(metadata_path, 'w').write(json.dumps(metadata))
    recipe['openvino_metadata_sha256'] = hashlib.sha256(open(metadata_path, 'rb').read()).hexdigest()
    with pytest.raises(ValueError, match='taxonomy'):
        validate_recipe(recipe)


def test_openvino_gpu_backend_rejects_cpu_only_runtime_before_loading_ir(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sys
    recipe,taxonomy=_recipe(tmp_path)
    class Core:
        available_devices=['CPU']
    monkeypatch.setitem(sys.modules,'openvino',SimpleNamespace(Core=Core))
    class Model:
        names={0:'chair'}
    detector=YOLOEDetector(recipe['checkpoint_path'],recipe['encoder_path'],taxonomy,
        checkpoint_license='fixture',backend='openvino_gpu',device='intel:gpu',
        openvino_model_path=recipe['openvino_model_path'],openvino_model_sha256=recipe['openvino_model_sha256'],
        openvino_bin_path=recipe['openvino_bin_path'],openvino_bin_sha256=recipe['openvino_bin_sha256'],
        model_factory=lambda *args,**kwargs:Model())
    with pytest.raises(RuntimeError,match='OpenVINO GPU requested but runtime exposes no GPU'):
        detector._load()


def test_openvino_detector_warms_static_ir_and_returns_source_bound_masks(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sys
    recipe, taxonomy = _recipe(tmp_path)
    class Core:
        available_devices=['CPU','GPU']
        def get_property(self,device,key):return 'Intel(R) UHD Graphics (iGPU)'
    monkeypatch.setitem(sys.modules,'openvino',SimpleNamespace(Core=Core))
    calls = []

    class Model:
        names = {0: 'chair'}

        def predict(self, **options):
            calls.append(options)
            height,width=options['source'].shape[:2]
            mask = np.ones((1, height, width), dtype=np.float32)
            return [SimpleNamespace(orig_img=options['source'], orig_shape=(height,width),
                boxes=SimpleNamespace(cls=np.array([0.]), conf=np.array([.9])),
                masks=SimpleNamespace(data=mask), names=self.names)]

    model = Model()
    detector = YOLOEDetector(recipe['checkpoint_path'], recipe['encoder_path'], taxonomy,
        checkpoint_license='fixture', imgsz=640, backend='openvino_gpu',
        device='intel:gpu',
        openvino_model_path=recipe['openvino_model_path'],
        openvino_model_sha256=recipe['openvino_model_sha256'],
        openvino_bin_path=recipe['openvino_bin_path'],
        openvino_bin_sha256=recipe['openvino_bin_sha256'],
        model_factory=lambda path, **kwargs: calls.append(('load', path, kwargs)) or model)
    detector.warmup()
    assert calls[0][0] == 'load'
    assert calls[1]['device'] == 'intel:gpu'
    assert calls[1]['source'].shape == (480, 640, 3)

    obs = observation()
    batch = detector.infer(obs)
    assert batch.source == obs.key and batch.geometry_hash == obs.geometry_hash
    assert batch.detections[0].raw_label == 'chair'
    assert batch.detections[0].mask.shape == obs.depth_m.shape
    assert calls[-1]['imgsz'] == 640 and calls[-1]['retina_masks'] is True


def test_openvino_detector_rejects_ir_class_names_that_do_not_match_taxonomy(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sys
    recipe, taxonomy = _recipe(tmp_path)
    class Core:
        available_devices=['GPU']
        def get_property(self,device,key):return 'Intel(R) UHD Graphics (iGPU)'
    monkeypatch.setitem(sys.modules,'openvino',SimpleNamespace(Core=Core))

    class Model:
        names = {0: 'table'}

    with pytest.raises(ValueError, match='class names'):
        detector = YOLOEDetector(recipe['checkpoint_path'], recipe['encoder_path'], taxonomy,
            checkpoint_license='fixture', backend='openvino_gpu',
            device='intel:gpu',
            openvino_model_path=recipe['openvino_model_path'],
            openvino_model_sha256=recipe['openvino_model_sha256'],
            openvino_bin_path=recipe['openvino_bin_path'],
            openvino_bin_sha256=recipe['openvino_bin_sha256'],
            model_factory=lambda path, **kwargs: Model())
        detector._load()


def test_detector_worker_falls_back_to_torch_cpu_only_during_gpu_initialization():
    from neusymnav.perception.detector_worker import _initialize_detector

    recipe=dict(backend='openvino_gpu',device='intel:gpu',fallback_policy='torch_cpu',
        checkpoint_path='checkpoint',encoder_path='encoder',checkpoint_license='fixture',
        imgsz=640,max_detections=30,confidence_threshold=.25,
        openvino_model_path='model.xml',openvino_model_sha256='a'*64,
        openvino_bin_path='model.bin',openvino_bin_sha256='b'*64)
    calls=[]

    class Backend:
        def __init__(self, *args, backend, device, **kwargs):
            self.backend=backend;calls.append((backend,device))

        def _load(self):
            if self.backend=='openvino_gpu':raise RuntimeError('GPU compile failed')

        def warmup(self):return 7_000_000

    detector,runtime=_initialize_detector(recipe,object(),Backend)
    assert detector.backend=='torch'
    assert calls==[('openvino_gpu','intel:gpu'),('torch','cpu')]
    assert runtime['backend_requested']=='openvino_gpu'
    assert runtime['backend_active']=='torch'
    assert runtime['fallback_reason']=='RuntimeError: GPU compile failed'


def test_detector_worker_can_fail_closed_when_gpu_fallback_is_disabled():
    from neusymnav.perception.detector_worker import _initialize_detector

    recipe=dict(backend='openvino_gpu',device='intel:gpu',fallback_policy='fail',
        checkpoint_path='checkpoint',encoder_path='encoder',checkpoint_license='fixture',
        imgsz=640,max_detections=30,confidence_threshold=.25,
        openvino_model_path='model.xml',openvino_model_sha256='a'*64,
        openvino_bin_path='model.bin',openvino_bin_sha256='b'*64)

    class Backend:
        def __init__(self, *args, backend, **kwargs):self.backend=backend
        def _load(self):raise RuntimeError('GPU unavailable')

    with pytest.raises(RuntimeError,match='GPU unavailable'):
        _initialize_detector(recipe,object(),Backend)
