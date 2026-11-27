from dataclasses import replace

import numpy as np
from PIL import Image
import pytest

from neusymnav.reasoninggraph.pair_selection import PairCrop


PAIR = PairCrop('det-a', 'det-b', (0, 0, 100, 80), (5, 10, 40, 70), (65, 10, 95, 70), 1.0)


def test_marked_crop_binds_order_and_validates_raster_bounds():
    import io

    from neusymnav.reasoninggraph.relation_image import marked_pair_jpeg

    rgb = np.full((80, 100, 3), 100, dtype=np.uint8)
    forward = marked_pair_jpeg(rgb, PAIR)
    reverse = marked_pair_jpeg(rgb, replace(PAIR, subject=PAIR.object, object=PAIR.subject,
                                           subject_xyxy=PAIR.object_xyxy, object_xyxy=PAIR.subject_xyxy))
    a, b = (Image.open(io.BytesIO(data)) for data in (forward, reverse))
    assert a.size == b.size == (100, 80)
    for image, channels in ((a, (0, 2)), (b, (2, 0))):
        left, right = image.getpixel((6, 40)), image.getpixel((66, 40))
        assert left[channels[0]] > left[channels[1]] + 40
        assert right[channels[1]] > right[channels[0]] + 40
    assert np.all(rgb == 100)
    with pytest.raises(ValueError, match='bounds'):
        marked_pair_jpeg(rgb, replace(PAIR, object_xyxy=(65, 10, 101, 70)))
    with pytest.raises(ValueError, match='bounds'):
        marked_pair_jpeg(rgb, replace(PAIR, crop_xyxy=(-1, 0, 100, 80)))


@pytest.mark.parametrize(('raw', 'verdict'), [(' yes\n', 'yes'), ('insufficient', 'insufficient'),
                                           ('no', 'no')])
def test_inference_accepts_only_grounded_fixed_verdicts(raw, verdict):
    from neusymnav.reasoninggraph.relation_image import ask_image_left_of

    def complete(prompt, grammar, jpeg):
        assert 'A (red)' in prompt and 'B (blue)' in prompt
        assert 'det-a' not in prompt and 'det-b' not in prompt
        assert '"yes"' in grammar and '"insufficient"' in grammar
        assert jpeg.startswith(b'\xff\xd8')
        return raw

    assert ask_image_left_of(complete, b'\xff\xd8').verdict == verdict
    with pytest.raises(ValueError, match='verdict'):
        ask_image_left_of(lambda *args: 'yes because left', b'\xff\xd8')


def test_neutral_prompt_maps_marker_color_to_ordered_verdict():
    from neusymnav.reasoninggraph.relation_image import ask_image_left_of

    def complete(prompt, grammar, jpeg):
        assert 'Which marked detection' in prompt
        assert '"red"' in grammar and '"blue"' in grammar
        return 'blue'

    assert ask_image_left_of(complete, b'\xff\xd8', prompt_policy='left-marker-v1').verdict == 'no'
