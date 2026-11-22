"""Day 1: export CLIP-family image encoders to OpenVINO, time them on CPU/iGPU, zero-shot crop check.

.runtime/clip-ov/bin/python tools/objectnav/b3/clip_bench.py MODEL_ID OUT_DIR [STOPS_DIR]
Without STOPS_DIR it only exports the model (image_encoder.xml, meta.json, text.npy, texts.json) and times it.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np
import openvino as ov
import torch
from PIL import Image
from transformers import AutoModel, AutoProcessor

model_id, out = sys.argv[1], Path(sys.argv[2])
stops = Path(sys.argv[3]) if len(sys.argv) > 3 else None
out.mkdir(parents=True, exist_ok=True)
model = AutoModel.from_pretrained(model_id).eval()
proc = AutoProcessor.from_pretrained(model_id)
size = proc.image_processor.size
side = size.get('shortest_edge') or size.get('height')


def _feat(out):
    # transformers >= 5 returns a model output whose pooler_output is the projected embedding
    return out if torch.is_tensor(out) else out.pooler_output


class Img(torch.nn.Module):
    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, pixel_values):
        f = _feat(self.m.get_image_features(pixel_values=pixel_values))
        return f / f.norm(dim=-1, keepdim=True)


ex = torch.zeros(1, 3, side, side)
ir = ov.convert_model(Img(model), example_input=ex, input=[(-1, 3, side, side)])
ov.save_model(ir, out / 'image_encoder.xml', compress_to_fp16=True)
ip = proc.image_processor
(out / 'meta.json').write_text(json.dumps(dict(model=model_id, side=side, mean=list(ip.image_mean), std=list(ip.image_std))))

# prompts -> normalized text embeddings (computed once, stored)
SETS = {  # target: [target prompt, confusable prompts...] (written before looking at any CLIP score)
    'sofa': ['a sofa', 'an armchair', 'a chair', 'a bed', 'a bench'],
    'toilet': ['a toilet', 'a chair', 'a sink', 'a bathtub', 'a bed'],
    'bed': ['a bed', 'a sofa', 'a table', 'a chair'],
    'chair': ['a chair', 'a sofa', 'a stool', 'a toilet', 'a table'],
    'tv_monitor': ['a television', 'a computer monitor', 'a picture frame', 'a window', 'a mirror'],
    'plant': ['a potted plant', 'a vase without plants', 'a lamp', 'a basket'],
}
texts = sorted({t for v in SETS.values() for t in v})
tok = proc(text=['a photo of ' + t for t in texts], return_tensors='pt', padding='max_length' if 'siglip' in model_id else True)
with torch.no_grad():
    tf = _feat(model.get_text_features(**{k: v for k, v in tok.items() if k in ('input_ids', 'attention_mask')}))
tf = (tf / tf.norm(dim=-1, keepdim=True)).numpy()
np.save(out / 'text.npy', tf)
(out / 'texts.json').write_text(json.dumps(texts))

core = ov.Core()
timing = {}
for dev in [d for d in ('CPU', 'GPU') if d in core.available_devices]:
    c = core.compile_model(out / 'image_encoder.xml', dev)
    x = np.random.rand(1, 3, side, side).astype(np.float32)
    for _ in range(3):
        c(x)
    t0 = time.perf_counter()
    for _ in range(20):
        c(x)
    timing[dev] = round((time.perf_counter() - t0) / 20 * 1000, 1)
print(model_id, 'side', side, 'ms/frame', timing)

if stops is None:
    sys.exit(0)
c = core.compile_model(out / 'image_encoder.xml', 'GPU')
idx = {t: i for i, t in enumerate(texts)}
rows = json.loads((stops / 'index.json').read_text())
res = []
for r in rows:
    img = Image.open(stops / (r['tag'] + '_crop.png')).convert('RGB')
    pv = proc(images=img, return_tensors='np')['pixel_values'].astype(np.float32)
    f = c(pv)[0][0]
    names = SETS[r['target']]
    sims = np.array([float(f @ tf[idx[n]]) for n in names])
    p = np.exp(100 * (sims - sims.max())); p /= p.sum()
    wrong = r['mode'] == 'wrong_object_stop'
    res.append(dict(tag=r['tag'], target=r['target'], wrong=wrong, top=names[int(np.argmax(sims))], p_target=round(float(p[0]), 3)))
keep_true = sum(1 for x in res if not x['wrong'] and x['top'] == SETS[x['target']][0])
rej_wrong = sum(1 for x in res if x['wrong'] and x['top'] != SETS[x['target']][0])
n_true, n_wrong = sum(not x['wrong'] for x in res), sum(x['wrong'] for x in res)
print('top-1 keeps true %d/%d, rejects wrong %d/%d' % (keep_true, n_true, rej_wrong, n_wrong))
for x in res:
    if x['wrong'] or x['top'] != SETS[x['target']][0]:
        print(' ', x)
(out / 'bench.json').write_text(json.dumps(dict(model=model_id, side=side, ms=timing, rows=res), indent=1))
