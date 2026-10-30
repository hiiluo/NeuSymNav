#!/usr/bin/env python3
"""GT-free offline YOLOE replay of every original source-bound exported frame.

No ground-truth inlet, identity assignment, download, or production adapter
changes. Larger image sizes and candidate caps are offline experiments only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import stat
import tempfile
import time

import numpy as np

from neusymnav.contracts.observations import Taxonomy
from neusymnav.evaluation.quality_dataset import FRAME_FIELDS, _validate_document
from neusymnav.evaluation.quality_export import _canonical, _json, _read, _sha, _snapshot_connection
from neusymnav.perception.yoloe import LocalMobileCLIPPromptProvider, _numpy

# A direct script invocation has tools/ on sys.path; importlib-based tests load
# this module as tools.replay_detection_quality without changing sys.path.
if __package__:
    from .replay_association_quality import _inputs
else:
    from replay_association_quality import _inputs


def _file_sha(path):
    """Stream large existing model files without loading them into host RAM."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise ValueError('existing nonempty regular model asset required')
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('local asset changed during checksum read')
        return digest.hexdigest()


def _pinned_asset(config_path, detector, name, override=None):
    record = detector.get(name)
    if not isinstance(record, dict) or set(record) != {'path','sha256'}:
        raise ValueError(f'checked runtime config {name} path/sha256 required')
    selected = Path(override if override is not None else record['path']).expanduser()
    if override is None and not selected.is_absolute():
        selected = config_path.parent/selected
    selected = selected.resolve(strict=True)
    digest = _file_sha(selected)
    if override is None and digest != record['sha256']:
        raise ValueError(f'local {name} checksum differs from runtime config')
    return selected, digest


def _result(result, bgr, categories, confidence, cap):
    """Reject ambiguous coordinates/results; explicitly count empty masks."""
    if (tuple(getattr(result, 'orig_shape', ())) != bgr.shape[:2]
            or not np.array_equal(getattr(result, 'orig_img', None), bgr)):
        raise ValueError('YOLOE result source image mismatch')
    if getattr(result, 'names', None) != dict(enumerate(categories)):
        raise ValueError('YOLOE result class names differ from canonical taxonomy order')
    boxes = getattr(result, 'boxes', None)
    classes = _numpy(getattr(boxes, 'cls', None), 'classes')
    scores = _numpy(getattr(boxes, 'conf', None), 'scores')
    if (classes.ndim != 1 or scores.shape != classes.shape
            or np.any(classes != np.floor(classes))):
        raise ValueError('YOLOE classes/scores must be aligned vectors with integer classes')
    if (np.any(classes < 0) or np.any(classes >= len(categories))
            or np.any((scores < confidence) | (scores > 1)) or len(classes) > cap):
        raise ValueError('YOLOE class/score/candidate count outside requested range')
    container = getattr(result, 'masks', None)
    if len(classes):
        masks = _numpy(getattr(container, 'data', None), 'masks')
        if masks.shape != (len(classes), *bgr.shape[:2]) or np.any((masks < 0) | (masks > 1)):
            raise ValueError('YOLOE retina masks must match the exact original source image')
    else:
        if container is not None:
            masks = _numpy(getattr(container, 'data', None), 'masks')
            if masks.shape != (0, *bgr.shape[:2]):
                raise ValueError('YOLOE empty masks must match source dimensions')
        return [], dict(raw_candidates=0, empty_masks_skipped=0, cap_reached=False)
    kept, empty = [], 0
    for index, class_id in enumerate(classes):
        mask = masks[index] >= .5
        if not mask.any():
            empty += 1
            continue
        y, x = np.nonzero(mask)
        kept.append((dict(id=str(index), label=categories[int(class_id)], score=float(scores[index]),
            bbox=[int(x.min()), int(y.min()), int(x.max())+1, int(y.max())+1]), mask))
    return kept, dict(raw_candidates=len(classes), empty_masks_skipped=empty,
                     cap_reached=len(classes) >= cap)


def replay_detection_quality(objects, *, predictions, config, out, imgsz=640,
                             confidence=.01, max_detections=100, checkpoint=None,
                             encoder=None, prompts=None, device='cuda:0',
                             model_factory=None, prompt_provider_factory=None):
    """Replay the exact selection. Factories inject only external CPU-test I/O."""
    if imgsz not in (640,960,1280) or type(imgsz) is not int:
        raise ValueError('offline imgsz must be 640, 960, or 1280')
    if type(max_detections) is not int or not 1 <= max_detections <= 4096:
        raise ValueError('offline max_detections must be in 1..4096')
    if type(confidence) not in (int,float) or not np.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError('confidence must be finite in [0,1]')
    if not isinstance(device, str) or not device.strip():
        raise ValueError('explicit inference device required')
    if (model_factory is None) != (prompt_provider_factory is None):
        raise ValueError('model and prompt provider factories must be injected together')
    root, prediction_path = Path(objects).resolve(strict=True), Path(predictions).absolute()
    config_path, output = Path(config).absolute(), Path(out).absolute()
    if (output.resolve().is_relative_to(root)
            or output.resolve().is_relative_to(prediction_path.parent.resolve())):
        raise ValueError('output must be outside both source inputs')
    if output.exists() or output.is_symlink():
        raise FileExistsError('detector replay output must be a new directory')
    prediction_raw, config_raw = _read(prediction_path), _read(config_path)
    document, runtime = _json(prediction_raw), _json(config_raw)
    _validate_document(document, prediction=True)
    with _snapshot_connection(root) as connection:
        source_config, inputs, assets, _, logical_digest = _inputs(root, prediction_path, document, connection)
    detector = runtime['detector']
    checkpoint_path, checkpoint_sha = _pinned_asset(config_path, detector, 'checkpoint', checkpoint)
    encoder_path, encoder_sha = _pinned_asset(config_path, detector, 'encoder', encoder)
    taxonomy_path, taxonomy_sha = _pinned_asset(config_path, detector, 'taxonomy')
    if not checkpoint_path.name.endswith('.pt'):
        raise ValueError('YOLOE replay requires an existing local .pt checkpoint')
    family_encoder = 'mobileclip2_b.ts' if 'yoloe-26' in checkpoint_path.name else 'mobileclip_blt.ts'
    if encoder_path.name != family_encoder:
        raise ValueError('checkpoint must have its compatible paired MobileCLIP encoder')
    taxonomy_data = _json(_read(taxonomy_path))
    if taxonomy_data.pop('schema_version', None) != 1:
        raise ValueError('unsupported taxonomy schema')
    taxonomy = Taxonomy(**taxonomy_data)
    if (taxonomy_sha != document['binding']['taxonomy_sha256']
            or taxonomy.vocabulary_id != source_config['vocabulary_id']):
        raise ValueError('replay taxonomy differs from original source binding')
    license_text = detector.get('checkpoint_license')
    if not isinstance(license_text, str) or not license_text.strip():
        raise ValueError('checkpoint license provenance required')
    prompt_raw = None if prompts is None else _read(Path(prompts))
    mapping = {category:category for category in taxonomy.categories} if prompts is None else _json(prompt_raw)
    if (not isinstance(mapping, dict) or set(mapping) != set(taxonomy.categories)
            or any(not isinstance(value, str) or not value.strip() for value in mapping.values())):
        raise ValueError('prompt mapping must contain exactly one nonempty text per taxonomy category')
    descriptions = [mapping[category] for category in taxonomy.categories]
    recipe = dict(imgsz=imgsz, confidence=confidence, max_detections=max_detections,
        retina_masks=True, device=device, class_order=list(taxonomy.categories),
        checkpoint_sha256=checkpoint_sha, encoder_sha256=encoder_sha, taxonomy_sha256=taxonomy_sha,
        prompt_mapping_sha256=_sha(_canonical(mapping).encode()))
    source_methods = [Path(__file__), Path(__file__).with_name('replay_association_quality.py')]
    import neusymnav.perception.yoloe as yoloe_module
    import neusymnav.evaluation.quality_export as export_module
    import neusymnav.evaluation.quality_dataset as dataset_module
    source_methods += [Path(module.__file__) for module in (yoloe_module, export_module, dataset_module)]
    method_hashes = {str(path.resolve()):_file_sha(path.resolve()) for path in source_methods}
    summary = dict(schema_version=1, frames=len(inputs), detections=0, empty_masks_skipped=0,
        cap_reached_frames=0, source_ledger=str(root), source_predictions=str(prediction_path),
        input_predictions_sha256=_sha(prediction_raw), runtime_config=str(config_path),
        runtime_config_sha256=_sha(config_raw), ledger_logical_sha256=logical_digest,
        verified_input_assets=assets, input_source_metadata=copy.deepcopy(document['provenance']['source_metadata']),
        source_methods_sha256=method_hashes, recipe=recipe, recipe_sha256=_sha(_canonical(recipe).encode()),
        prompt_mapping=mapping, prompt_file_sha256=None if prompt_raw is None else _sha(prompt_raw),
        checkpoint=dict(path=str(checkpoint_path), sha256=checkpoint_sha, license=license_text,
                        override=checkpoint is not None),
        encoder=dict(path=str(encoder_path), sha256=encoder_sha, override=encoder is not None),
        taxonomy=dict(path=str(taxonomy_path), sha256=taxonomy_sha),
        inference_timing='synchronized wall time around model.predict only; includes first inference warmup',
        per_frame=[], cuda_peak_memory_allocated_bytes=None, cuda_peak_memory_reserved_bytes=None,
        limitations=['All original retained frames are development/diagnostic sources, not held-out data.',
            'No GT is read; evaluate separately against the unchanged all-frame GT.',
            'Inference timing excludes prompt/model loading, source decoding, mask export and evaluation.',
            'Cap saturation marks a frame partial; empty instance masks are skipped and explicitly counted.',
            'CUDA peaks cover this process allocator, not total device usage or a native live-runtime budget.'])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='detector-replay-', dir=output.parent) as temporary:
        stage = Path(temporary)
        cuda = None
        if model_factory is None:
            # These are consumed by Ultralytics at import. Explicit local
            # weights + explicit text embeddings avoid all online model paths.
            os.environ['YOLO_AUTOINSTALL'] = 'false'
            os.environ['YOLO_OFFLINE'] = 'true'
            os.environ.setdefault('YOLO_CONFIG_DIR', str(stage/'ultralytics-config'))
            if importlib.util.find_spec('clip') is None:
                raise RuntimeError('local clip tokenizer unavailable; no auto-install permitted')
            import torch
            from ultralytics import YOLOE
            model_factory = YOLOE
            prompt_provider_factory = LocalMobileCLIPPromptProvider
            summary['runtime_versions'] = dict(torch=torch.__version__)
            import ultralytics
            summary['runtime_versions']['ultralytics'] = ultralytics.__version__
            if device.startswith('cuda'):
                if not torch.cuda.is_available():
                    raise RuntimeError('requested CUDA unavailable; no CPU fallback')
                cuda = torch.cuda
                cuda.synchronize(device)
                cuda.reset_peak_memory_stats(device)
        model = model_factory(str(checkpoint_path))
        if callable(getattr(model, 'to', None)):
            model.to(device)
        provider = prompt_provider_factory(encoder_path)
        embeddings = provider(model, descriptions)
        if embeddings is None:
            raise ValueError('local prompt provider returned no embeddings')
        model.set_classes(list(taxonomy.categories), embeddings)
        setup_ns = time.perf_counter_ns()
        frames = []
        for ordinal, (source, _, original) in enumerate(inputs):
            # Always give the backend independent storage. Its returned image
            # must still match the immutable original, even if it mutates this
            # input array in place and returns that same array as orig_img.
            bgr = np.array(source.rgb[..., ::-1], copy=True, order='C')
            if cuda is not None: cuda.synchronize(device)
            started = time.perf_counter_ns()
            results = list(model.predict(source=bgr, imgsz=imgsz, conf=confidence,
                max_det=max_detections, retina_masks=True, verbose=False, device=device, save=False))
            if cuda is not None: cuda.synchronize(device)
            elapsed = time.perf_counter_ns()-started
            if len(results) != 1:
                raise ValueError('YOLOE requires exactly one result for each exact source frame')
            objects, diagnostic = _result(results[0], source.rgb[..., ::-1],
                taxonomy.categories, confidence, max_detections)
            frame = {field:copy.deepcopy(original[field]) for field in FRAME_FIELDS}
            frame.update(status='partial' if diagnostic['cap_reached'] else 'complete', objects=[])
            for obj, mask in objects:
                stream = io.BytesIO(); np.save(stream, mask, allow_pickle=False)
                raw = stream.getvalue()
                relative = f'masks/{ordinal:06d}-{obj["id"]}.npy'
                destination = stage/relative
                destination.parent.mkdir(exist_ok=True)
                destination.write_bytes(raw)
                obj['mask'] = dict(path=relative, sha256=_sha(raw))
                frame['objects'].append(obj)
            frames.append(frame)
            summary['per_frame'].append(dict(frame_id=frame['frame_id'], frame_index=frame['frame_index'],
                source_sha256=frame['source_sha256'], inference_elapsed_ns=elapsed,
                exported_detections=len(objects), **diagnostic))
            summary['detections'] += len(objects)
            summary['empty_masks_skipped'] += diagnostic['empty_masks_skipped']
            summary['cap_reached_frames'] += int(diagnostic['cap_reached'])
        summary['replay_loop_elapsed_ns'] = time.perf_counter_ns()-setup_ns
        summary['total_inference_elapsed_ns'] = sum(item['inference_elapsed_ns'] for item in summary['per_frame'])
        if cuda is not None:
            summary['cuda_peak_memory_allocated_bytes'] = cuda.max_memory_allocated(device)
            summary['cuda_peak_memory_reserved_bytes'] = cuda.max_memory_reserved(device)
        # Loading/inference cannot silently change a pinned asset or recipe.
        for path, digest in ((checkpoint_path, checkpoint_sha), (encoder_path, encoder_sha),
                             (taxonomy_path, taxonomy_sha)):
            if _file_sha(path) != digest:
                raise ValueError('local pinned asset changed during replay')
        derived = dict(schema_version=1, binding=copy.deepcopy(document['binding']),
            provenance=dict(kind=document['provenance']['kind'],
                description='GT-free local detector replay; all original source frames retained.',
                recipe=recipe, recipe_sha256=summary['recipe_sha256'],
                input_predictions_sha256=summary['input_predictions_sha256'],
                ledger_logical_sha256=logical_digest,
                source_metadata=copy.deepcopy(document['provenance']['source_metadata'])),
            identity_semantics='none', score_floor=confidence, max_detections=max_detections,
            final_aliases={}, frames=frames)
        _validate_document(derived, prediction=True)
        raw = (_canonical(derived)+'\n').encode()
        (stage/'predictions.json').write_bytes(raw)
        summary['predictions'] = str(output/'predictions.json')
        summary['predictions_sha256'] = _sha(raw)
        (stage/'replay-manifest.json').write_text(_canonical(summary)+'\n')
        if output.exists() or output.is_symlink():
            raise FileExistsError('replay output appeared during preparation')
        stage.rename(output)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--objects', required=True)
    parser.add_argument('--predictions', required=True)
    parser.add_argument('--config', required=True, help='Checked local runtime JSON config')
    parser.add_argument('--out', required=True, help='New directory outside both source trees')
    parser.add_argument('--imgsz', type=int, choices=(640,960,1280), default=640)
    parser.add_argument('--confidence', type=float, default=.01)
    parser.add_argument('--max-detections', type=int, default=100)
    parser.add_argument('--checkpoint', help='Explicit existing local checkpoint override')
    parser.add_argument('--encoder', help='Explicit compatible local MobileCLIP override')
    parser.add_argument('--prompts', help='JSON category-to-description map; defaults to canonical text')
    parser.add_argument('--device', default='cuda:0')
    args = vars(parser.parse_args())
    objects = args.pop('objects')
    print(_canonical(replay_detection_quality(objects, **args)))


if __name__ == '__main__':
    main()
