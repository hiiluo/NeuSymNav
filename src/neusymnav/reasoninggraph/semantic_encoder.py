"""Image/text encoder seam for offline ReasoningGraph object features."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math

import numpy as np

from ..contracts.reasoninggraph import FeatureSpec


CHANNELS = ('bbox', 'mask', 'text')


@dataclass(frozen=True)
class ObjectRecipe:
    bbox_weight: float = 0.
    mask_weight: float = .1
    text_weight: float = .9

    def __post_init__(self):
        if (not all(type(value) in (int, float) and math.isfinite(value) and value >= 0
                    for value in self.weights) or not math.isfinite(sum(self.weights))
                or sum(self.weights) <= 0):
            raise ValueError('invalid object feature weights')

    @property
    def weights(self):
        return self.bbox_weight, self.mask_weight, self.text_weight


@dataclass(frozen=True)
class ObjectChannels:
    spec: FeatureSpec
    bbox: tuple | None
    mask: tuple | None
    text: tuple | None

    @property
    def missing(self):
        return tuple(name for name in CHANNELS if getattr(self, name) is None)


def unit_vector(value, dimension):
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (dimension,) or not np.isfinite(array).all():
        return None
    scale = float(abs(array).max())
    if scale == 0.:
        return None
    vector = array / scale
    return tuple(float(x) for x in vector / np.linalg.norm(vector))


class ObjectEncoder:
    def __init__(self, spec, encode_image, encode_text, *, prompt_cache=64):
        if not isinstance(spec, FeatureSpec) or spec.modality != 'object' or not spec.normalized:
            raise ValueError('expected a normalized object feature spec')
        if not callable(encode_image) or not callable(encode_text):
            raise ValueError('paired image and text encoders are required')
        if type(prompt_cache) is not int or not 1 <= prompt_cache <= 256:
            raise ValueError('invalid prompt cache size')
        self.spec = spec
        self._encode_image = encode_image
        self._encode_text = encode_text
        self._cache = OrderedDict()
        self._cache_cap = prompt_cache

    def encode_object(self, rgb, mask, category):
        """Use one XYXY crop with foreground-only RGB and a pinned prompt template."""
        if (not isinstance(rgb, np.ndarray) or rgb.ndim != 3 or rgb.shape[2] != 3
                or rgb.dtype != np.uint8 or not 0 < rgb.nbytes <= 16*1024**2):
            raise ValueError('invalid RGB crop')
        if (not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.shape != rgb.shape[:2]
                or not mask.any()):
            raise ValueError('invalid crop mask')
        if not isinstance(category, str) or not category.strip() or len(category) > 128:
            raise ValueError('invalid category prompt')
        prompt = 'a photo of a ' + category
        if prompt not in self._cache:
            self._cache[prompt] = unit_vector(self._encode_text(prompt), self.spec.dimension)
        self._cache.move_to_end(prompt)
        if len(self._cache) > self._cache_cap:
            self._cache.popitem(last=False)
        bbox = unit_vector(self._encode_image(rgb), self.spec.dimension)
        masked = unit_vector(self._encode_image(np.where(mask[:, :, None], rgb, np.uint8(0))), self.spec.dimension)
        return ObjectChannels(self.spec, bbox, masked, self._cache[prompt])
