"""Standalone raw-image relation evaluation for an ordered pair of detections."""
from dataclasses import dataclass
import hashlib
from io import BytesIO

import numpy as np
from PIL import Image, ImageDraw

from .pair_selection import PairCrop


_PROMPT = (
    'Look at the two marked detections. Is A (red) to the left of B (blue) in this image? '
    'Answer yes if A is on the left, no if A is on the right, '
    'or insufficient if you cannot locate both markers or tell their order.'
)
_GRAMMAR = 'root ::= "yes" | "no" | "insufficient"\n'
_POLICIES = {
    'yes-no-v1': (_PROMPT, _GRAMMAR, {'yes': 'yes', 'no': 'no', 'insufficient': 'insufficient'}),
    'left-marker-v1': (
        'Which marked detection appears farther to the left in this image? '
        'Reply red for the red box, blue for the blue box, or insufficient if the order is unclear.',
        'root ::= "red" | "blue" | "insufficient"\n',
        {'red': 'yes', 'blue': 'no', 'insufficient': 'insufficient'},
    ),
}
PROMPT_POLICIES = tuple(_POLICIES)
_MAX_JPEG_BYTES = 2 * 1024**2
_MAX_PIXELS = 2048**2


@dataclass(frozen=True)
class ImageRelationResult:
    verdict: str
    image_sha256: str
    prompt_sha256: str
    grammar_sha256: str
    response: str


def _bounds(box, width, height):
    x0, y0, x1, y1 = box
    if not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height:
        raise ValueError('invalid relation crop or marker bounds')
    return x0, y0, x1, y1


def marked_pair_jpeg(rgb, pair):
    """Render A for the subject and B for the object on the union crop."""
    if (not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8
            or rgb.ndim != 3 or rgb.shape[2] != 3):
        raise ValueError('expected an RGB uint8 raster')
    if not isinstance(pair, PairCrop) or pair.subject == pair.object:
        raise ValueError('expected two distinct ordered detections')
    height, width = rgb.shape[:2]
    x0, y0, x1, y1 = _bounds(pair.crop_xyxy, width, height)
    width, height = x1 - x0, y1 - y0
    if width * height > _MAX_PIXELS:
        raise ValueError('relation image exceeds pixel budget')
    boxes = [_bounds(box, width, height) for box in (pair.subject_xyxy, pair.object_xyxy)]
    image = Image.fromarray(rgb[y0:y1, x0:x1])
    draw = ImageDraw.Draw(image)
    for (left, top, right, bottom), color, label in zip(boxes, ('red', 'blue'), ('A', 'B')):
        draw.rectangle((left, top, right - 1, bottom - 1), outline=color, width=3)
        label_x = max(0, min(width - 12, (left + right) // 2 - 6))
        label_y = max(0, min(height - 13, top))
        draw.rectangle((label_x, label_y, label_x + 11, label_y + 12), fill=color)
        draw.text((label_x + 2, label_y), label, fill='white')
    output = BytesIO()
    image.save(output, format='JPEG', quality=90, subsampling=0)
    jpeg = output.getvalue()
    if len(jpeg) > _MAX_JPEG_BYTES:
        raise ValueError('relation image exceeds byte budget')
    return jpeg


def ask_image_left_of(complete_visual, jpeg, *, prompt_policy='yes-no-v1'):
    """Constrain a bounded transport call to the fixed image-space predicate."""
    if not isinstance(jpeg, bytes) or not jpeg.startswith(b'\xff\xd8') or len(jpeg) > _MAX_JPEG_BYTES:
        raise ValueError('expected bounded JPEG evidence')
    if prompt_policy not in _POLICIES:
        raise ValueError('unknown image relation prompt policy')
    prompt, grammar, verdicts = _POLICIES[prompt_policy]
    raw = complete_visual(prompt, grammar, jpeg)
    response = raw.strip() if isinstance(raw, str) and len(raw) <= 64 else None
    if response not in verdicts:
        raise ValueError('invalid image relation verdict')
    return ImageRelationResult(verdicts[response], hashlib.sha256(jpeg).hexdigest(),
                               hashlib.sha256(prompt.encode()).hexdigest(),
                               hashlib.sha256(grammar.encode()).hexdigest(), response)
