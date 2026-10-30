"""GT-free detector replay over real typed fixture ledgers; no GPU required."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from test_quality_export import file_hashes, make_ledger, run_export


def module():
    path = Path(__file__).resolve().parents[1]/'tools/replay_detection_quality.py'
    assert path.is_file(), 'detector replay implementation is missing'
    spec = importlib.util.spec_from_file_location('tools.replay_detection_quality', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def prepared(tmp_path, **kwargs):
    assets = make_ledger(tmp_path, **kwargs)
    exported = run_export(tmp_path, assets)
    checkpoint = tmp_path/'yoloe-26m-seg.pt'
    encoder = tmp_path/'mobileclip2_b.ts'
    checkpoint.write_bytes(b'local test checkpoint')
    encoder.write_bytes(b'local test encoder')
    def ref(path):
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    config = tmp_path/'config.json'
    config.write_text(json.dumps(dict(detector=dict(checkpoint=ref(checkpoint),
        encoder=ref(encoder), taxonomy=ref(assets[2]), checkpoint_license='test-only'))))
    return assets[0], Path(exported['predictions']), config


class FakeModel:
    """Only external inference is fake; source validation/serialization stay real."""
    def __init__(self, fault=None, empty=False):
        self.fault, self.empty = fault, empty
        self.names = {}

    def set_classes(self, names, embeddings):
        # Descriptions must never become output labels.
        self.names = dict(enumerate(names))

    def predict(self, **kwargs):
        source = kwargs['source']
        masks = np.zeros((0 if self.empty else 2, *source.shape[:2]), dtype=np.float32)
        if not self.empty:
            masks[0, 3:8, 2:7] = 1  # second is explicitly empty
        classes = np.zeros(len(masks))
        scores = np.full(len(masks), .3)
        image = source.copy()
        if self.fault == 'source': image = np.zeros((1,1,3), dtype=np.uint8)
        if self.fault == 'mutation':
            source[:] = 255
            image = source
        if self.fault == 'mask': masks = masks[:, :-1]
        if self.fault == 'class': classes[0] = .5
        if self.fault == 'range': classes[0] = 99
        if self.fault == 'score': scores[0] = np.nan
        if self.fault == 'floor': scores[0] = .001
        return [SimpleNamespace(orig_img=image, orig_shape=source.shape[:2], names=self.names,
            boxes=SimpleNamespace(cls=classes, conf=scores),
            masks=SimpleNamespace(data=masks))]


def run(root, predictions, config, out, **kwargs):
    model = kwargs.pop('model', FakeModel())
    return module().replay_detection_quality(root, predictions=predictions, config=config,
        out=out, device='cpu', model_factory=lambda _: model,
        prompt_provider_factory=lambda _: lambda model, prompts: tuple(prompts), **kwargs)


def test_retains_binding_masks_empty_mask_accounting_and_no_identities(tmp_path):
    root, pred, config = prepared(tmp_path)
    prompts = tmp_path/'prompts.json'
    prompts.write_text('{"chair":"a chair with a backrest"}')
    before = file_hashes(root), file_hashes(pred.parent)
    result = run(root, pred, config, tmp_path/'output', prompts=prompts, max_detections=2)
    document = json.loads((tmp_path/'output/predictions.json').read_text())
    original = json.loads(pred.read_text())
    assert result['frames'] == 2 and result['empty_masks_skipped'] == 2
    assert result['cap_reached_frames'] == 2
    assert document['binding'] == original['binding']
    assert document['identity_semantics'] == 'none' and document['final_aliases'] == {}
    for actual, source in zip(document['frames'], original['frames']):
        assert {k:v for k,v in actual.items() if k not in {'objects','status'}} == {
            k:v for k,v in source.items() if k not in {'objects','status'}}
        assert actual['status'] == 'partial'
        obj, = actual['objects']
        assert obj['label'] == 'chair' and 'identity' not in obj
        assert obj['bbox'] == [2,3,7,8]
        mask = np.load(tmp_path/'output'/obj['mask']['path'], allow_pickle=False)
        assert mask.dtype == np.bool_ and mask.shape == (32,32) and mask.sum() == 25
        assert hashlib.sha256((tmp_path/'output'/obj['mask']['path']).read_bytes()).hexdigest() == obj['mask']['sha256']
    assert before == (file_hashes(root), file_hashes(pred.parent))
    assert all(frame['inference_elapsed_ns'] >= 0 for frame in result['per_frame'])
    assert result['prompt_mapping'] == {'chair':'a chair with a backrest'}
    assert json.loads((tmp_path/'output/replay-manifest.json').read_text()) == result


def test_empty_sources_and_empty_inference_are_not_filtered(tmp_path):
    root, pred, config = prepared(tmp_path, empty=True)
    result = run(root, pred, config, tmp_path/'output', model=FakeModel(empty=True))
    document = json.loads((tmp_path/'output/predictions.json').read_text())
    assert result['frames'] == 2 and result['detections'] == 0
    assert all(f['objects'] == [] and f['status'] == 'complete' for f in document['frames'])


@pytest.mark.parametrize('fault', ['source','mask','class','range','score','floor'])
def test_bad_model_result_aborts_without_partial_output(tmp_path, fault):
    root, pred, config = prepared(tmp_path)
    before = file_hashes(root), file_hashes(pred.parent)
    with pytest.raises(ValueError):
        run(root, pred, config, tmp_path/'output', model=FakeModel(fault=fault))
    assert not (tmp_path/'output').exists()
    assert before == (file_hashes(root), file_hashes(pred.parent))


def test_backend_input_mutation_cannot_rebind_source_or_modify_observation(tmp_path, monkeypatch):
    root, pred, config = prepared(tmp_path)
    replay_module = module()
    original_inputs = replay_module._inputs
    sources = []

    def capture_inputs(*args):
        loaded = original_inputs(*args)
        sources.extend(source for source, _, _ in loaded[1])
        return loaded

    monkeypatch.setattr(replay_module, '_inputs', capture_inputs)
    before = file_hashes(root), file_hashes(pred.parent)
    with pytest.raises(ValueError, match='source image mismatch'):
        replay_module.replay_detection_quality(root, predictions=pred, config=config,
            out=tmp_path/'output', device='cpu',
            model_factory=lambda _: FakeModel(fault='mutation'),
            prompt_provider_factory=lambda _: lambda model, prompts: tuple(prompts))
    assert not (tmp_path/'output').exists()
    assert sources and all(np.count_nonzero(source.rgb) == 0 for source in sources)
    assert before == (file_hashes(root), file_hashes(pred.parent))


@pytest.mark.parametrize('value', ['{}','{"chair":""}','{"chair":"a","chair":"b"}',
                                  '{"chair":"a","table":"b"}'])
def test_prompt_mapping_must_exactly_match_taxonomy(tmp_path, value):
    root, pred, config = prepared(tmp_path)
    prompts = tmp_path/'prompts.json'; prompts.write_text(value)
    with pytest.raises(ValueError):
        run(root, pred, config, tmp_path/'output', prompts=prompts)
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('kind', ['source','taxonomy','model','missing'])
def test_rejects_source_or_asset_pin_mismatch(tmp_path, kind):
    root, pred, config = prepared(tmp_path)
    if kind == 'source':
        doc = json.loads(pred.read_text()); doc['frames'][0]['source_sha256'] = '0'*64
        pred.write_text(json.dumps(doc))
    else:
        doc = json.loads(config.read_text())
        key = 'taxonomy' if kind == 'taxonomy' else 'checkpoint'
        if kind == 'missing': Path(doc['detector'][key]['path']).unlink()
        else: doc['detector'][key]['sha256'] = '0'*64; config.write_text(json.dumps(doc))
    with pytest.raises((ValueError, FileNotFoundError)):
        run(root, pred, config, tmp_path/'output')
    assert not (tmp_path/'output').exists()


def test_output_never_overwrites_or_enters_input_tree(tmp_path):
    root, pred, config = prepared(tmp_path)
    for output in (root/'new', pred.parent/'new'):
        with pytest.raises(ValueError): run(root, pred, config, output)
    output = tmp_path/'existing'; output.mkdir(); (output/'keep').write_bytes(b'keep')
    with pytest.raises(FileExistsError): run(root, pred, config, output)
    assert (output/'keep').read_bytes() == b'keep'
