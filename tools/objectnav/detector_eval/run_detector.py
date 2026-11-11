#!/usr/bin/env python3
"""Phase 2, step 2: run the runtime YOLOE detector on the sampled frames (detector env).

    PYTHONPATH=src ~/Desktop/test_Room_segmentation/NeuSymNav/.runtime/detector26/bin/python tools/objectnav/detector_eval/run_detector.py \
        --views runs/objectnav/detector_eval/views --out runs/objectnav/detector_eval/predictions.jsonl

Uses the runtime ``YOLOEDetector`` class with the pinned assets, backend, imgsz
and taxonomy of the runtime profile (default: the v11 00806 profile), so the
numbers describe the detector the robot runs. Only the confidence floor is
lowered (default 0.01) so that every threshold can be evaluated offline; the
per-frame cap stays at the runtime maximum of 30. The detector only sees RGB
(depth is passed for the contract but not used by YOLOE). Resumable.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.contracts.observations import FrameKey, Observation, Taxonomy  # noqa: E402
from neusymnav.objectnav.detector_eval.masks import bbox_xyxy, rle_encode  # noqa: E402
from neusymnav.perception.yoloe import YOLOEDetector  # noqa: E402

DEFAULT_PROFILE = ROOT / 'configs/demo-00806.hydra-tour-slm.experimental.local.json'


def pinned(entry, name):
    path = Path(entry['path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry['sha256']:
        raise SystemExit('%s checksum differs from the profile pin' % name)
    return path, digest


def build_detector(profile, confidence):
    d = json.loads(Path(profile).read_text())['detector']
    checkpoint, _ = pinned(d['checkpoint'], 'checkpoint')
    encoder, _ = pinned(d['encoder'], 'encoder')
    taxonomy_path, _ = pinned(d['taxonomy'], 'taxonomy')
    kwargs = {}
    if d.get('backend') == 'openvino_gpu':
        xml, xml_sha = pinned(d['openvino_model'], 'openvino_model')
        binary, bin_sha = pinned(d['openvino_bin'], 'openvino_bin')
        kwargs = dict(openvino_model_path=xml, openvino_model_sha256=xml_sha,
                      openvino_bin_path=binary, openvino_bin_sha256=bin_sha)
    detector = YOLOEDetector(checkpoint, encoder, Taxonomy.load(taxonomy_path),
                             checkpoint_license=d['checkpoint_license'], imgsz=int(d['imgsz']),
                             max_detections=int(d['max_detections']), confidence_threshold=float(confidence),
                             device=d['device'], backend=d.get('backend', 'torch'), **kwargs)
    detector._load()
    detector.warmup()
    recipe = dict(profile=str(profile), checkpoint=str(checkpoint), backend=detector.backend, device=d['device'],
                  imgsz=int(d['imgsz']), max_detections=int(d['max_detections']), confidence_floor=float(confidence),
                  runtime_confidence_threshold=float(d['confidence_threshold']),
                  openvino_device=detector.openvino_device_name, taxonomy=str(taxonomy_path))
    return detector, recipe


def observation(index, rgb, depth_mm):
    h, w = rgb.shape[:2]
    f = (w / 2.0) / np.tan(np.radians(90.0) / 2)
    K = np.array([[f, 0, (w - 1) / 2.0], [0, f, (h - 1) / 2.0], [0, 0, 1.0]])
    depth = depth_mm.astype(np.float32) / 1000.0
    return Observation(FrameKey('detector-eval', 'primary-rgbd', index), index + 1, 'replay:detector-eval', 0.0,
                       rgb, depth, depth > 0, K, np.eye(4), 'detector-eval', 0, 'rgbd')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--views', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--profile', type=Path, default=DEFAULT_PROFILE)
    ap.add_argument('--confidence-floor', type=float, default=0.01)
    a = ap.parse_args(argv)
    rows = [json.loads(line) for line in (a.views / 'views.jsonl').read_text().splitlines() if line.strip()]
    done = set()
    if a.out.exists():
        done = {json.loads(line)['frame_id'] for line in a.out.read_text().splitlines() if line.strip()}
    detector, recipe = build_detector(a.profile, a.confidence_floor)
    meta_path = a.out.with_suffix('.recipe.json')
    if meta_path.exists() and json.loads(meta_path.read_text()) != recipe:
        raise SystemExit('existing predictions were made with a different recipe; use a new --out')
    meta_path.write_text(json.dumps(recipe, indent=2) + '\n')
    todo = [r for r in rows if r['frame_id'] not in done]
    print('frames: %d total, %d done, %d to run; backend %s' % (len(rows), len(done), len(todo), recipe['backend']), flush=True)
    started, n = time.monotonic(), 0
    with open(a.out, 'a') as stream:
        for index, row in enumerate(rows):
            if row['frame_id'] in done:
                continue
            with np.load(a.views / 'frames' / (row['frame_id'] + '.npz')) as arrays:
                obs = observation(index, arrays['rgb'], arrays['depth_mm'])
            t0 = time.monotonic()
            batch = detector.infer(obs)
            dt = time.monotonic() - t0
            detections = [dict(label=d.raw_label, score=round(float(d.score), 5), bbox=bbox_xyxy(d.mask),
                               rle=rle_encode(d.mask)) for d in batch.detections]
            stream.write(json.dumps(dict(frame_id=row['frame_id'], detections=detections,
                                         cap_reached=bool(batch.cap_reached), infer_ms=round(dt * 1000, 2))) + '\n')
            n += 1
            if n % 200 == 0:
                stream.flush()
                print('%d/%d frames, %.1f ms/frame' % (n, len(todo), 1000 * (time.monotonic() - started) / n), flush=True)
    print('done:', a.out)


if __name__ == '__main__':
    main()
