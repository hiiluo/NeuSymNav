"""B3 semantic value map (VLFM-style, with a SigLIP image-text score instead of BLIP-2 ITM).

One layer per obstacle-map floor. Each new view gives one score s = cos(image embedding, "a <target>")
and is written into the cells that view saw (``ObstacleMap.last_frame``) with confidence
c = cos^2(angle off the optical axis / (hfov / 2) * pi / 2). Fusion (VLFM eq. 1-2):
    v <- (c * s + c_old * v) / (c + c_old),   c_old <- (c^2 + c_old^2) / (c + c_old)
so a cell seen head-on dominates one seen at the edge of the image, and the newest head-on view of
a cell outweighs older side views.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Tuple

import numpy as np


class ValueMap:
    def __init__(self, hfov_deg: float):
        self.half_fov = math.radians(float(hfov_deg)) / 2.0
        self.layers: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}   # id(level) -> (value, confidence)
        self.updates = 0

    def _layer(self, level, shape):
        key = id(level)
        if key not in self.layers:
            self.layers[key] = (np.zeros(shape, np.float32), np.zeros(shape, np.float32))
        return self.layers[key]

    def update(self, obstacle_map, robot_xy, yaw_rad: float, score: float) -> int:
        """Write one view's score into the cells it saw; returns the number of cells updated."""
        frame = obstacle_map.last_frame
        if frame is None:
            return 0
        r0, c0, mask = frame
        rr, cc = np.nonzero(mask)
        if not len(rr):
            return 0
        value, conf = self._layer(obstacle_map.level, obstacle_map.level.explored.shape)
        rr, cc = rr + r0, cc + c0
        res, (ox, oy) = obstacle_map.res, obstacle_map.origin
        x = ox + (cc + 0.5) * res
        y = oy + (rr + 0.5) * res
        off = np.arctan2(y - robot_xy[1], x - robot_xy[0]) - yaw_rad
        off = (off + math.pi) % (2 * math.pi) - math.pi
        c = (np.cos(np.clip(off / self.half_fov, -1.0, 1.0) * math.pi / 2) ** 2).astype(np.float32)
        near = np.hypot(x - robot_xy[0], y - robot_xy[1]) < 2 * res
        c[near] = 1.0                                     # the robot's own cells: no meaningful angle
        c_old, v_old = conf[rr, cc], value[rr, cc]
        tot = np.maximum(c + c_old, 1e-6)
        value[rr, cc] = (c * score + c_old * v_old) / tot
        conf[rr, cc] = (c * c + c_old * c_old) / tot
        self.updates += 1
        return int(len(rr))

    def at(self, obstacle_map, cell, radius_cells: int = 5) -> Optional[float]:
        """Confidence-weighted mean value around ``cell`` on the current floor (None: never seen)."""
        layer = self.layers.get(id(obstacle_map.level))
        if layer is None:
            return None
        value, conf = layer
        r, c = cell
        sl = (slice(max(r - radius_cells, 0), r + radius_cells + 1), slice(max(c - radius_cells, 0), c + radius_cells + 1))
        w = conf[sl]
        if float(w.sum()) <= 1e-6:
            return None
        return float((value[sl] * w).sum() / w.sum())
