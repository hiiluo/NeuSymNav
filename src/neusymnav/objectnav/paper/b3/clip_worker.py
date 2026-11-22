"""CLIP-family image encoder worker (runs in the .runtime/clip-ov venv; numpy, Pillow, OpenVINO only).

    python clip_worker.py MODEL_DIR DEVICE

MODEL_DIR holds ``image_encoder.xml`` (OpenVINO IR, L2-normalised output) and ``meta.json``
({"side", "mean", "std"}). Requests on stdin, replies on stdout, little-endian:
request  = uint32 n, then n x (uint32 h, uint32 w, h*w*3 uint8 RGB)
reply    = uint32 n, uint32 dim, then n*dim float32
Each image is resized (squashed, bicubic) to side x side so the whole field of view is kept.
n = 0 ends the worker.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np
import openvino as ov
from PIL import Image


def _read(stream, k):
    buf = stream.read(k)
    if len(buf) != k:
        raise EOFError
    return buf


def main():
    model_dir, device = Path(sys.argv[1]), sys.argv[2]
    meta = json.loads((model_dir / 'meta.json').read_text())
    side = int(meta['side'])
    mean = np.asarray(meta['mean'], np.float32)[:, None, None]
    std = np.asarray(meta['std'], np.float32)[:, None, None]
    model = ov.Core().compile_model(model_dir / 'image_encoder.xml', device)
    inp, out = sys.stdin.buffer, sys.stdout.buffer
    out.write(b'READY\n')
    out.flush()
    while True:
        (n,) = struct.unpack('<I', _read(inp, 4))
        if n == 0:
            return
        batch = []
        for _ in range(n):
            h, w = struct.unpack('<II', _read(inp, 8))
            rgb = np.frombuffer(_read(inp, h * w * 3), np.uint8).reshape(h, w, 3)
            img = np.asarray(Image.fromarray(rgb).resize((side, side), Image.BICUBIC), np.float32) / 255.0
            batch.append((img.transpose(2, 0, 1) - mean) / std)
        feats = np.asarray(model(np.stack(batch).astype(np.float32))[0], np.float32)
        out.write(struct.pack('<II', *feats.shape) + feats.tobytes())
        out.flush()


if __name__ == '__main__':
    main()
