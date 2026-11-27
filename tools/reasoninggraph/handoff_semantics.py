"""Offline handoff: rank reviewed replay objects or inspect saved Hydra rooms.

Examples: object --revision 9 --query 'kitchen island'; rooms --id 5908722711110090752.
Neither result is a current navigation or semantic-ground-truth certificate.
"""
import argparse
import hashlib
import inspect
import json
from pathlib import Path

BASE = Path('runs/reasoninggraph/m1-holdout-00770-20261127')
GRAPH = Path('runs/reasoninggraph/m3-replay-20261127/graph.json')
PROFILE = Path('configs/p10/demo-yoloe11s-conceptgraphs-visual-gpu-00861.json')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    data = path.read_bytes()
    return json.loads(data), sha(data)


def rooms(path, room_id):
    graph, digest = load(path)
    nodes = {n['id']: n for n in graph['nodes']}
    matches = [n for n in nodes.values() if n['layer'] == 4 and (room_id is None or n['id'] == room_id)]
    result = []
    for node in matches:
        attr = node['attributes']
        edges = [e for e in graph['edges'] if node['id'] in (e['source'], e['target'])]
        neighbors = sorted(({'id': e['target'] if e['source'] == node['id'] else e['source'],
                             'layer': nodes[e['target'] if e['source'] == node['id'] else e['source']]['layer']}
                            for e in edges), key=lambda x: x['id'])
        result.append({'id': node['id'], 'name': attr.get('name'), 'semantic_label_raw': attr.get('semantic_label'),
                       'position': attr.get('position'), 'bounding_box': attr.get('bounding_box'), 'neighbors': neighbors})
    return {'status': 'ok' if result else 'no_evidence', 'graph_sha256': digest, 'rooms': result,
            'limitation': 'Native topology and raw labels only; no certified room polygon or semantic room geometry. Edges are not traversability certificates.'}


def objects(base, revision, query, checkpoint=None):
    import clip
    import numpy as np
    import torch
    from PIL import Image
    from clip.clip import _transform
    from clip.model import build_model
    from neusymnav.perception.appearance_worker import _validate_openai_architecture, _validate_openai_transform
    from neusymnav.reasoninggraph.semantic_encoder import unit_vector

    report_path = base / 'probe-matched-cpu/report.json'
    report, report_hash = load(report_path)
    annotations, annotation_hash = load(base / 'annotations-ai-reviewed.json')
    if annotations['report_sha256'] != report_hash:
        raise ValueError('annotation/report mismatch')
    rows = [r for r in report['records'] if r['revision'] == revision]
    if len(rows) != 1:
        raise ValueError('unknown or duplicate revision')
    row = rows[0]
    if not row['exact_class_raster']:
        raise ValueError('revision lacks an exact class raster')
    labels = [x for x in annotations['labels'] if x['revision'] == revision and x['status'] == 'matched']
    result = {'status': 'no_evidence', 'query': query, 'revision': revision, 'token': row['token'],
              'report_sha256': report_hash, 'annotation_sha256': annotation_hash, 'objects': [],
              'limitation': 'Offline revision-local reviewed links, not canonical identity or ground truth. Cosine ranks do not certify a match.'}
    if not labels:
        return result
    profile, profile_hash = load(PROFILE)
    worker = profile['worker']
    checkpoint = checkpoint or Path(worker['checkpoint_path'])
    checkpoint_hash = sha(checkpoint.read_bytes())
    if checkpoint_hash != worker['checkpoint_sha256']:
        raise ValueError('checkpoint hash mismatch')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    archive = torch.jit.load(str(checkpoint), map_location='cpu')
    state = dict(archive.state_dict())
    _validate_openai_architecture(state)
    del archive
    model = build_model(state).float().eval()
    transform = _transform(224)
    _validate_openai_transform(transform)
    preprocess_hash = sha((repr(transform) + inspect.getsource(clip.tokenize)).encode())
    with torch.inference_mode():
        q = unit_vector(model.encode_text(clip.tokenize(['a photo of a ' + query]))[0].numpy(), 512)
    if q is None:
        raise ValueError('invalid query encoding')
    probe = base / 'probe-matched-cpu'
    manifest_hash = sha((probe / row['manifest']).read_bytes())
    if manifest_hash != row['manifest_sha256']:
        raise ValueError('manifest mismatch')
    for label in labels:
        items = [e for e in row['evidence'] if e['evidence']['detection_id'] == label['detection_id']]
        if len(items) != 1 or label['native_id'] not in row['native_endpoints']:
            raise ValueError('invalid reviewed endpoint')
        item = items[0]
        evidence = item['evidence']
        if evidence['source'] != row['token']['source'] or evidence['input_prefix_sha256'] != row['token']['native']['input_prefix_sha256']:
            raise ValueError('source mismatch')
        asset = probe / evidence['asset_key']
        asset_hash = sha(asset.read_bytes())
        with np.load(asset, allow_pickle=False) as data:
            for key, field in [('rgb', 'rgb_sha256'), ('mask', 'mask_sha256'), ('depth_m', 'depth_sha256')]:
                if sha(data[key].tobytes()) != evidence[field]:
                    raise ValueError('evidence hash mismatch')
            rgb, mask = data['rgb'], data['mask']
            if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3 or mask.dtype != np.bool_ or mask.shape != rgb.shape[:2] or not mask.any():
                raise ValueError('invalid image/mask')
            image = np.where(mask[:, :, None], rgb, np.uint8(0))
            with torch.inference_mode():
                vector = unit_vector(model.encode_image(transform(Image.fromarray(image)).unsqueeze(0))[0].numpy(), 512)
        if vector is None:
            raise ValueError('invalid image encoding')
        result['objects'].append({'native_id_revision_local': label['native_id'], 'detection_id': label['detection_id'],
                                  'category_detector': item['category'], 'cosine': float(np.dot(vector, q)),
                                  'asset_sha256': asset_hash, 'rgb_sha256': evidence['rgb_sha256'], 'mask_sha256': evidence['mask_sha256']})
    result['objects'].sort(key=lambda x: (-x['cosine'], x['native_id_revision_local']))
    result.update(status='ok', model_sha256=checkpoint_hash, profile_sha256=profile_hash,
                  preprocessing_sha256=preprocess_hash, manifest_sha256=manifest_hash)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    obj = sub.add_parser('object')
    obj.add_argument('--base', type=Path, default=BASE)
    obj.add_argument('--revision', type=int, required=True)
    obj.add_argument('--query', required=True)
    obj.add_argument('--checkpoint', type=Path)
    room = sub.add_parser('rooms')
    room.add_argument('--graph', type=Path, default=GRAPH)
    room.add_argument('--id', type=int)
    args = parser.parse_args()
    if args.command == 'object':
        if not args.query.strip() or len(args.query) > 128:
            parser.error('query must contain 1–128 characters')
        result = objects(args.base, args.revision, args.query, args.checkpoint)
    else:
        result = rooms(args.graph, args.id)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
