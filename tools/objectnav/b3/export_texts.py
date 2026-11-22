"""Add the text embeddings a B3 config needs to a SigLIP/CLIP model dir (text.npy + texts.json).

Existing rows are kept bit-for-bit (runs made with them stay reproducible); only missing prompts are
encoded, the same way clip_bench.py does ('a photo of ' + prompt, normalized, CPU).

HF_HOME=local-assets/models/b3/hf HF_HUB_OFFLINE=1 \
  .runtime/clip-ov/bin/python tools/objectnav/b3/export_texts.py configs/objectnav/paper-b3-v2.json
"""
import json
import sys
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoProcessor

cfg = json.loads(Path(sys.argv[1]).read_text())
model_dir = Path(cfg['semantic']['model_dir'])
need = set(cfg['semantic']['prompts'].values())
for spec in (cfg.get('clip_verify') or {}).get('targets', {}).values():
    need |= set(spec) if isinstance(spec, list) else set(spec['pos']) | set(spec['neg'])
texts = json.loads((model_dir / 'texts.json').read_text())
emb = np.load(model_dir / 'text.npy')
new = sorted(need - set(texts))
print('have %d, adding %d: %s' % (len(texts), len(new), new))
if new:
    model_id = json.loads((model_dir / 'meta.json').read_text())['model']
    model = AutoModel.from_pretrained(model_id).eval()
    proc = AutoProcessor.from_pretrained(model_id)
    tok = proc(text=['a photo of ' + t for t in new], return_tensors='pt',
               padding='max_length' if 'siglip' in model_id else True)
    with torch.no_grad():
        out = model.get_text_features(**{k: v for k, v in tok.items() if k in ('input_ids', 'attention_mask')})
    tf = out if torch.is_tensor(out) else out.pooler_output
    tf = (tf / tf.norm(dim=-1, keepdim=True)).numpy().astype(emb.dtype)
    np.save(model_dir / 'text.npy', np.concatenate([emb, tf]))
    (model_dir / 'texts.json').write_text(json.dumps(texts + new))
print('done')
