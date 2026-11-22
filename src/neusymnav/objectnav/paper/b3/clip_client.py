"""Policy-side client of the CLIP image encoder worker (paper/b3/clip_worker.py)."""
from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[5]


def _abs(p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else REPO / p


class ClipClient:
    """Image embeddings (L2-normalised) and stored text embeddings of one exported model."""

    def __init__(self, model_dir, *, python='.runtime/clip-ov/bin/python', device: str = 'GPU'):
        self.model_dir = _abs(model_dir)
        texts = json.loads((self.model_dir / 'texts.json').read_text())
        emb = np.load(self.model_dir / 'text.npy').astype(np.float32)
        self.text: Dict[str, np.ndarray] = {t: emb[i] for i, t in enumerate(texts)}
        self._cmd = [str(_abs(python)), str(Path(__file__).with_name('clip_worker.py')), str(self.model_dir), device]
        self._proc = None
        self.calls = 0

    def _ensure(self):
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(self._cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL)
            if self._proc.stdout.readline().strip() != b'READY':
                raise RuntimeError('clip worker did not start: %s' % self._cmd)

    def embed(self, images: Sequence[np.ndarray]) -> np.ndarray:
        self._ensure()
        parts = [struct.pack('<I', len(images))]
        for im in images:
            im = np.ascontiguousarray(np.asarray(im)[..., :3], np.uint8)
            parts.append(struct.pack('<II', im.shape[0], im.shape[1]) + im.tobytes())
        self._proc.stdin.write(b''.join(parts))
        self._proc.stdin.flush()
        n, dim = struct.unpack('<II', self._proc.stdout.read(8))
        self.calls += 1
        return np.frombuffer(self._proc.stdout.read(4 * n * dim), np.float32).reshape(n, dim)

    def scores(self, feats: np.ndarray, prompts: List[str]) -> np.ndarray:
        """Cosine similarity (n images x len(prompts))."""
        return feats @ np.stack([self.text[p] for p in prompts]).T

    def close(self):
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.stdin.write(struct.pack('<I', 0))
                self._proc.stdin.flush()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
        self._proc = None
