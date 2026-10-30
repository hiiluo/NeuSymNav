"""Offline-only versioned, exact-source object quality annotation boundary."""
from __future__ import annotations

import hashlib
import io
import json
import math
from pathlib import Path
import re

import numpy as np

MAX_JSON_BYTES = 64 * 1024**2
FRAME_FIELDS = ('frame_id', 'frame_index', 'capture_monotonic_ns', 'source_sha256',
                'geometry_hash', 'width', 'height')


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} requires nonempty text')
    return value


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('expected lowercase SHA-256')
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_document(path):
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES: raise ValueError('quality JSON exceeds 64 MiB')
    raw = path.read_bytes()
    def invalid(token): raise ValueError(f'nonfinite JSON: {token}')
    value = json.loads(raw, object_pairs_hook=_unique_pairs, parse_constant=invalid)
    if not isinstance(value, dict): raise ValueError('quality document must be an object')
    return value, hashlib.sha256(raw).hexdigest()


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('expected finite number')
    return value


def _mask(value, shape, base):
    if isinstance(value, dict):
        if set(value) != {'path', 'sha256'}: raise ValueError('mask requires path and sha256')
        path = Path(_text(value['path'], 'mask path'))
        path = path if path.is_absolute() else base/path
        if path.stat().st_size > MAX_JSON_BYTES: raise ValueError('mask file exceeds limit')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != _digest(value['sha256']):
            raise ValueError('mask checksum mismatch')
        array = np.load(io.BytesIO(raw), allow_pickle=False)
    else:
        array = np.asarray(value)
    if array.shape != shape or array.dtype != np.bool_:
        raise ValueError('mask must be bool raster matching source image')
    if not array.any(): raise ValueError('instance mask must be nonempty')
    return array


def _objects(items, frame, base, prediction):
    if not isinstance(items, list) or len(items) > 4096: raise ValueError('invalid object list')
    result = []; ids = set()
    for item in items:
        if not isinstance(item, dict): raise ValueError('object must be a JSON object')
        allowed = {'id','label','bbox','mask'} | ({'score','identity'} if prediction else set())
        if set(item)-allowed: raise ValueError('unsupported object fields (crowd/ignore not supported)')
        key = _text(item.get('id'), 'observation id')
        if key in ids: raise ValueError('duplicate observation id')
        ids.add(key)
        label = _text(item.get('label'), 'label')
        box = item.get('bbox')
        if not isinstance(box, list) or len(box) != 4: raise ValueError('bbox must be xyxy')
        x1,y1,x2,y2 = map(_number, box)
        if not (0 <= x1 < x2 <= frame['width'] and 0 <= y1 < y2 <= frame['height']):
            raise ValueError('bbox outside source or empty')
        output = dict(id=key, label=label, bbox=box)
        if prediction:
            score = _number(item.get('score'))
            if not 0 <= score <= 1: raise ValueError('score outside [0,1]')
            output['score'] = score
            if item.get('identity') is not None: output['identity'] = _text(item['identity'], 'identity')
        if 'mask' in item: output['mask'] = _mask(item['mask'], (frame['height'], frame['width']), base)
        result.append(output)
    return result


def _validate_document(doc, prediction=False):
    required = {'schema_version', 'binding', 'provenance', 'frames'}
    optional = {'geometry_objects', 'scope_gt_ids', 'geometry_scope'}
    if prediction: required |= {'identity_semantics', 'score_floor', 'max_detections'}; optional |= {'final_aliases'}
    if not required <= doc.keys() or set(doc)-required-optional: raise ValueError('invalid quality document fields')
    if type(doc['schema_version']) is not int or doc['schema_version'] != 1: raise ValueError('unsupported quality version')
    binding = doc['binding']
    if not isinstance(binding, dict) or set(binding) != {'scene_id','episode_id','recording_sha256','taxonomy_sha256','coordinate_convention'}:
        raise ValueError('invalid source binding')
    for name in ('scene_id','episode_id'): _text(binding[name], name)
    for name in ('recording_sha256','taxonomy_sha256'): _digest(binding[name])
    if binding['coordinate_convention'] != 'canonical_z_up_m_v1': raise ValueError('coordinate convention mismatch')
    provenance = doc['provenance']
    if not isinstance(provenance, dict) or provenance.get('kind') not in {'synthetic','recorded'}:
        raise ValueError('provenance kind required')
    _text(provenance.get('description'), 'provenance description')
    frames = doc['frames']
    if not isinstance(frames, list) or len(frames) > 10000: raise ValueError('invalid frame list')
    previous = -1; previous_stamp = -1; keys = set()
    for frame in frames:
        if not isinstance(frame, dict): raise ValueError('invalid frame')
        fields = set(FRAME_FIELDS) | {'objects', 'status' if prediction else 'annotated'}
        if set(frame) != fields: raise ValueError('invalid frame fields')
        key = _text(frame['frame_id'], 'frame_id')
        if key in keys: raise ValueError('duplicate frame id')
        keys.add(key)
        for name in ('frame_index','capture_monotonic_ns','width','height'):
            if type(frame[name]) is not int or frame[name] < (1 if name in {'width','height'} else 0):
                raise ValueError('invalid frame numeric metadata')
        if frame['width']*frame['height'] > 16_777_216: raise ValueError('image bound exceeded')
        if frame['frame_index'] <= previous or frame['capture_monotonic_ns'] <= previous_stamp:
            raise ValueError('frames must increase in source order and capture time')
        previous = frame['frame_index']; previous_stamp = frame['capture_monotonic_ns']
        _digest(frame['source_sha256']); _digest(frame['geometry_hash'])
        if prediction:
            if frame['status'] not in {'complete','partial','failed','missing'}: raise ValueError('invalid prediction status')
            if frame['status'] in {'failed','missing'} and frame['objects']: raise ValueError('missing/failed frame cannot have detections')
        elif frame['annotated'] is not True: raise ValueError('unannotated GT: annotate explicitly before evaluation')
    if prediction:
        if doc['identity_semantics'] not in {'online','final_canonical_only','none'}: raise ValueError('identity semantics required')
        floor = doc['score_floor']
        if floor is not None and not 0 <= _number(floor) <= 1: raise ValueError('invalid supplied score floor')
        cap = doc['max_detections']
        if cap is not None and (type(cap) is not int or cap < 1): raise ValueError('invalid detection cap')


def load_quality_pair(gt_path, prediction_path):
    gt, gt_hash = read_document(gt_path); pred, pred_hash = read_document(prediction_path)
    _validate_document(gt); _validate_document(pred, True)
    if gt['binding'] != pred['binding']: raise ValueError('prediction and GT binding mismatch')
    if gt['provenance']['kind'] != pred['provenance']['kind']: raise ValueError('synthetic/recorded provenance mismatch')
    if len(gt['frames']) != len(pred['frames']): raise ValueError('same complete frame scope required; mark absent predictions missing')
    frames = []
    for g,p in zip(gt['frames'], pred['frames']):
        if any(g[name] != p[name] for name in FRAME_FIELDS): raise ValueError('exact source frame binding mismatch')
        frames.append(dict(frame_id=g['frame_id'], gt=_objects(g['objects'],g,Path(gt_path).parent,False),
            pred=_objects(p['objects'],p,Path(prediction_path).parent,True), status=p['status']))
        if pred['max_detections'] is not None and len(p['objects']) > pred['max_detections']:
            raise ValueError('prediction count exceeds declared cap')
        if pred['score_floor'] is not None and any(o['score'] < pred['score_floor'] for o in p['objects']):
            raise ValueError('prediction below declared upstream score floor')
    return dict(frames=frames, gt=gt, predictions=pred,
        input_hashes=dict(gt=gt_hash, predictions=pred_hash))
