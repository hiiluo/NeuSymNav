#!/usr/bin/env python3
"""Materialize Hypersim instance rasters; zeros are ignore, never background.

Outputs are not YOLO polygon labels. Training must explicitly mask ignored pixels
and unsupported class negatives. Source HDF5 arrays remain untouched.
"""
import argparse
import csv
import ctypes as C
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE_NAMES = {3:'cabinet', 4:'bed', 5:'chair', 6:'sofa', 7:'table', 8:'door', 9:'window', 10:'bookcase', 12:'counter', 13:'blinds', 14:'desk', 15:'shelf', 16:'curtain', 17:'dresser', 18:'pillow', 19:'mirror', 23:'book', 24:'fridge', 25:'television', 27:'towel', 32:'nightstand', 33:'toilet', 34:'sink', 35:'lamp', 36:'bathtub'}


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def freeze_split(scenes):
    scenes = set(scenes)
    val = {'ai_004_003', 'ai_007_001', 'ai_010_007'}
    test = {'ai_016_009', 'ai_044_001'}
    if len(scenes) != 14 or not val | test <= scenes:
        raise ValueError('expected frozen 14-scene pool')
    return {'train': sorted(scenes - val - test), 'val': sorted(val), 'test': sorted(test)}


def crosstab(semantic, instance):
    # Audited source range: semantic -1..40, instance -1..522.
    if semantic.shape != instance.shape or semantic.min() < -1 or semantic.max() > 40 or instance.min() < -1 or instance.max() > 32766:
        raise ValueError('unexpected source shape or label range')
    keys = (instance.astype(np.int32).ravel() + 1) * 42 + semantic.ravel() + 1
    counts = np.bincount(keys)
    result = defaultdict(dict)
    for key in np.flatnonzero(counts):
        i, s = divmod(int(key), 42)
        result[i-1][s-1] = int(counts[key])
    return dict(result)


def convert_frame(semantic, instance, mapping, excluded=()):
    cross = crosstab(semantic, instance)
    mask = np.zeros(instance.shape, dtype=np.uint16)
    objects = []
    excluded = set(excluded)
    for raw_id, counts in sorted(cross.items()):
        if raw_id <= 0 or raw_id in excluded or len(counts) != 1:
            continue
        semantic_id = next(iter(counts))
        if semantic_id not in mapping:
            continue
        name, class_id = mapping[semantic_id]
        new_id = len(objects) + 1
        mask[instance == raw_id] = new_id
        objects.append({'id': new_id, 'raw_instance_id': raw_id, 'raw_semantic_id': semantic_id, 'class_id': class_id, 'class_name': name, 'pixels': counts[semantic_id]})
    background = np.isin(semantic, (1, 2, 22))
    for raw_id in excluded:
        background[instance == raw_id] = False
    for raw_id, counts in cross.items():
        if raw_id > 0 and len(counts) != 1:
            background[instance == raw_id] = False
    ignore = (mask == 0) & ~background
    return mask, ignore, background, objects, cross


class HDF5:
    def __init__(self):
        self.lib = C.CDLL('libhdf5_serial.so')
        self.hl = C.CDLL('libhdf5_serial_hl.so')
        self.lib.H5Fopen.argtypes = [C.c_char_p, C.c_uint, C.c_longlong]
        self.lib.H5Fopen.restype = C.c_longlong
        self.lib.H5Fclose.argtypes = [C.c_longlong]
        self.hl.H5LTget_dataset_ndims.argtypes = [C.c_longlong, C.c_char_p, C.POINTER(C.c_int)]
        self.hl.H5LTget_dataset_info.argtypes = [C.c_longlong, C.c_char_p, C.POINTER(C.c_ulonglong), C.POINTER(C.c_int), C.POINTER(C.c_size_t)]
        self.hl.H5LTread_dataset_short.argtypes = [C.c_longlong, C.c_char_p, C.POINTER(C.c_short)]

    def read(self, path):
        f = self.lib.H5Fopen(str(path).encode(), 0, 0)
        if f < 0:
            raise ValueError(f'cannot open {path}')
        try:
            rank = C.c_int()
            if self.hl.H5LTget_dataset_ndims(f, b'dataset', C.byref(rank)) < 0 or rank.value != 2:
                raise ValueError(f'invalid rank: {path}')
            dims = (C.c_ulonglong * 2)()
            typ, size = C.c_int(), C.c_size_t()
            if self.hl.H5LTget_dataset_info(f, b'dataset', dims, C.byref(typ), C.byref(size)) < 0 or typ.value != 0 or size.value != 2 or tuple(dims) != (768, 1024):
                raise ValueError(f'invalid array: {path}')
            a = np.empty(tuple(dims), dtype=np.int16)
            if self.hl.H5LTread_dataset_short(f, b'dataset', a.ctypes.data_as(C.POINTER(C.c_short))) < 0:
                raise ValueError(f'cannot read {path}')
            return a
        finally:
            self.lib.H5Fclose(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--triplets', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    rows = list(csv.reader(args.triplets.open(), delimiter='\t'))
    if any(len(row) != 10 for row in rows):
        raise ValueError('expected 10 columns per triplet')
    taxonomy_path = ROOT / 'configs/taxonomy-v1.json'
    cats = json.loads(taxonomy_path.read_text())['categories']
    mapping = {k: (v, cats.index(v)) for k, v in SOURCE_NAMES.items()}
    split = freeze_split(row[1] for row in rows)
    scene_split = {scene: part for part, scenes in split.items() for scene in scenes}
    (out/'split.json').write_text(json.dumps({'algorithm':'fixed-balanced-scenes-v1', 'splits':split, 'triplets_sha256':sha(args.triplets), 'base_model':'original YOLOE-11s segmentation; never legacy fine-tuned weights', 'development_00861_excluded':True}, indent=2)+'\n')
    (out/'mapping.json').write_text(json.dumps({'taxonomy_sha256':sha(taxonomy_path), 'mapping':{str(k):{'class_name':v[0], 'class_id':v[1]} for k,v in mapping.items()}, 'unmapped_and_void':'ignore', 'instance_conflict':'exclude entire scene instance if multiple raw semantic IDs including void', 'unlabeled_class_negatives':'must be masked by trainer; no exhaustive negatives', 'supervised_class_ids':sorted(v[1] for v in mapping.values()), 'background_semantic_ids':[1,2,22], 'background_scope':'25 mapped classes only; not a global 59-class negative', 'raster':'uint16 instance IDs, 0 nonpositive; uint8 ignore/background 255 true'}, indent=2)+'\n')
    hdf = HDF5()
    scene_cross = defaultdict(lambda: defaultdict(Counter))
    cross_file = out/'crosstabs.jsonl'
    with cross_file.open('w') as f:
        for n, row in enumerate(rows):
            for path, expected in zip(row[4::2], row[5::2]):
                if sha(path) != expected:
                    raise ValueError(f'hash mismatch {path}')
            cross = crosstab(hdf.read(row[6]), hdf.read(row[8]))
            for i, counts in cross.items():
                if i > 0:
                    scene_cross[row[1]][i].update(counts)
            f.write(json.dumps({'scene':row[1], 'camera':row[2], 'frame':row[3], 'instances':cross}, sort_keys=True)+'\n')
            if (n+1)%100 == 0:
                print(f'audit {n+1}/{len(rows)}', flush=True)
    excluded = {scene: {i for i,c in ids.items() if len(c)>1} for scene,ids in scene_cross.items()}
    conflicts = {scene:{str(i):dict(scene_cross[scene][i]) for i in sorted(ids)} for scene,ids in excluded.items() if ids}
    (out/'scene-conflicts.json').write_text(json.dumps(conflicts, indent=2, sort_keys=True)+'\n')
    stats = defaultdict(Counter)
    with (out/'manifest.jsonl').open('w') as f:
        for n,row in enumerate(rows):
            group, scene, camera, frame = row[:4]
            part = scene_split[scene]
            key = f'{scene}_{camera}_{frame}'
            mask, ignore, background, objects, cross = convert_frame(hdf.read(row[6]), hdf.read(row[8]), mapping, excluded[scene])
            folder = out/'masks'/part
            folder.mkdir(parents=True, exist_ok=True)
            maskpath, ignorepath, bgpath = folder/f'{key}.instance.png', folder/f'{key}.ignore.png', folder/f'{key}.background.png'
            Image.fromarray(mask, mode='I;16').save(maskpath)
            Image.fromarray(ignore.astype(np.uint8)*255, mode='L').save(ignorepath)
            Image.fromarray(background.astype(np.uint8)*255, mode='L').save(bgpath)
            rec = {'key':key, 'split':part, 'scene':scene, 'camera':camera, 'frame':frame, 'source_group':group, 'image':row[4], 'image_sha256':row[5], 'semantic_sha256':row[7], 'instance_sha256':row[9], 'instance_mask':str(maskpath.relative_to(out)), 'instance_mask_sha256':sha(maskpath), 'ignore_mask':str(ignorepath.relative_to(out)), 'ignore_mask_sha256':sha(ignorepath), 'background_mask':str(bgpath.relative_to(out)), 'background_mask_sha256':sha(bgpath), 'supervised_class_ids':sorted(v[1] for v in mapping.values()), 'objects':objects}
            f.write(json.dumps(rec, sort_keys=True)+'\n')
            stats[part]['frames'] += 1
            stats[part]['positive_pixels'] += int((mask > 0).sum())
            stats[part]['ignore_pixels'] += int(ignore.sum())
            stats[part]['background_pixels'] += int(background.sum())
            stats[part]['instances'] += len(objects)
            for obj in objects:
                stats[part]['class:'+obj['class_name']] += 1
            if (n+1)%100 == 0:
                print(f'materialize {n+1}/{len(rows)}', flush=True)
    (out/'summary.json').write_text(json.dumps({'stats':stats, 'scene_conflict_count':sum(map(len,excluded.values())), 'frames':len(rows)}, indent=2, sort_keys=True)+'\n')


if __name__ == '__main__':
    main()
