"""B1 STOP check: ask a local VLM what the object to stop at is (paper mode, offline-free, no GT).

Before STOP on a target listed in ``targets``, the policy sends the robot's own RGB crop of the
candidate (latest detection box + margin) to Qwen3-VL-2B (llama.cpp ``llama-server``, local files
only) with one open question. The answer must name the target (one of its synonyms); otherwise the
candidate is rejected and exploration continues. An open question is used because the 2B model
answers yes to nearly every yes/no question and follows the letter order in A/B questions.

The server is started lazily on the first question and stopped with the policy.
"""
from __future__ import annotations

import base64
import io
import json
import socket
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[4]


class VlmVerifier:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.targets: Dict[str, List[str]] = {k: [w.lower() for w in v] for k, v in cfg['targets'].items()}
        self.port = int(cfg.get('port', 8712))
        self._proc: Optional[subprocess.Popen] = None

    @staticmethod
    def validate(cfg: dict) -> None:
        need = {'targets', 'prompt', 'server_bin', 'model', 'mmproj'}
        if not need <= set(cfg) or set(cfg) - need - {'port', 'threads', 'margin'}:
            raise ValueError('vlm_verify needs %s (optional port, threads, margin)' % sorted(need))
        if not cfg['targets'] or not all(isinstance(v, list) and v for v in cfg['targets'].values()):
            raise ValueError('vlm_verify.targets maps a goal category to its synonyms')

    def _path(self, key) -> str:
        p = Path(self.cfg[key])
        return str(p if p.is_absolute() else REPO / p)

    def _alive(self) -> bool:
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/health' % self.port, timeout=2) as r:
                return b'ok' in r.read()
        except Exception:
            return False

    def _ensure(self) -> None:
        if self._alive():
            return
        with socket.socket() as s:
            if s.connect_ex(('127.0.0.1', self.port)) == 0:
                raise RuntimeError('port %d is taken by something that is not a healthy llama-server' % self.port)
        self._proc = subprocess.Popen(
            [self._path('server_bin'), '-m', self._path('model'), '--mmproj', self._path('mmproj'),
             '--host', '127.0.0.1', '--port', str(self.port), '-c', '4096', '-t', str(int(self.cfg.get('threads', 8))),
             '--temp', '0'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            if self._alive():
                return
            if self._proc.poll() is not None:
                raise RuntimeError('llama-server exited with %s' % self._proc.returncode)
            time.sleep(1)
        raise RuntimeError('llama-server did not become healthy')

    def crop(self, rgb: np.ndarray, bbox, mask_shape) -> np.ndarray:
        h, w = rgb.shape[:2]
        sy, sx = h / mask_shape[0], w / mask_shape[1]
        x0, y0, x1, y1 = bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy
        m = float(self.cfg.get('margin', 0.15))
        bw, bh = x1 - x0, y1 - y0
        r0, r1 = int(max(0, y0 - m * bh)), int(min(h, y1 + m * bh))
        c0, c1 = int(max(0, x0 - m * bw)), int(min(w, x1 + m * bw))
        return np.ascontiguousarray(rgb[r0:r1, c0:c1, :3])

    def ask(self, crop: np.ndarray) -> str:
        from PIL import Image
        self._ensure()
        buf = io.BytesIO()
        Image.fromarray(crop.astype(np.uint8)).save(buf, format='PNG')
        body = dict(messages=[dict(role='user', content=[
            dict(type='image_url', image_url=dict(url='data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode())),
            dict(type='text', text=self.cfg['prompt'])])], temperature=0, max_tokens=8)
        req = urllib.request.Request('http://127.0.0.1:%d/v1/chat/completions' % self.port, json.dumps(body).encode(),
                                     {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)['choices'][0]['message']['content'].strip()

    def accepts(self, target: str, answer: str) -> bool:
        a = answer.lower()
        return any(w in a for w in self.targets[target])

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
