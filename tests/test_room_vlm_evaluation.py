from io import BytesIO

import pytest
from PIL import Image

from tools.evaluate_room_vlm import (
    annotated_case_rows,
    jpeg_dimensions,
    load_reference_labels,
    rotating_variant_order,
    score_annotated_first_round,
    unique_image_dimensions,
)


def test_reference_labels_include_only_explicit_canonical_annotations(tmp_path):
    path = tmp_path / 'reference.json'
    path.write_text(
        '{"schema_version":1,"labels":'
        '{"R(0)":["bedroom"],"R(1)":[],"R(2)":["bathroom","utility"]}}'
    )

    labels = load_reference_labels(path)

    assert labels == {'R(0)': ('bedroom',), 'R(2)': ('bathroom', 'utility')}


def test_reference_rejects_noncanonical_labels(tmp_path):
    path = tmp_path / 'reference.json'
    path.write_text('{"schema_version":1,"labels":{"R(0)":["lounge"]}}')

    with pytest.raises(ValueError, match='canonical'):
        load_reference_labels(path)


def test_variant_order_rotates_deterministically_by_round_and_room():
    variants = ('text', 'text+geometry', 'text+kss')

    assert rotating_variant_order(0, 0, variants) == variants
    assert rotating_variant_order(0, 1, variants) == ('text+geometry', 'text+kss', 'text')
    assert rotating_variant_order(1, 0, variants) == ('text+geometry', 'text+kss', 'text')


def test_annotation_scores_use_only_annotated_room_ids_and_first_round():
    references = {'R(0)': ('bedroom',), 'R(2)': ('bathroom',)}
    rows = [
        {'room_id': 'R(0)', 'round': 0, 'status': 'available', 'label': 'bedroom'},
        {'room_id': 'R(0)', 'round': 1, 'status': 'available', 'label': 'kitchen'},
        {'room_id': 'R(1)', 'round': 0, 'status': 'available', 'label': 'living_room'},
        {'room_id': 'R(2)', 'round': 0, 'status': 'insufficient_evidence', 'label': 'unknown'},
    ]

    score = score_annotated_first_round(rows, references)

    assert score == {
        'annotation_room_count': 2,
        'matched_room_count': 2,
        'supported_count': 1,
        'correct_supported_count': 1,
        'coverage': 0.5,
        'selective_accuracy': 1.0,
        'unmatched_annotation_room_ids': [],
    }

    assert annotated_case_rows(rows, references) == [
        {'room_id': 'R(0)', 'reference_labels': ['bedroom'],
         'prediction_status': 'available', 'prediction_label': 'bedroom',
         'supported': True, 'correct_if_supported': True},
        {'room_id': 'R(2)', 'reference_labels': ['bathroom'],
         'prediction_status': 'insufficient_evidence', 'prediction_label': 'unknown',
         'supported': False, 'correct_if_supported': False},
    ]


def test_report_image_dimensions_are_deduplicated_as_tuples_before_json_lists():
    records = {
        'text+geometry': {'R(0)': [{'image_width': 448, 'image_height': 252}]},
        'text+kss': {'R(0)': [{'image_width': 448, 'image_height': 252},
                              {'image_width': 320, 'image_height': 240}]},
    }

    assert unique_image_dimensions(records) == [[320, 240], [448, 252]]


def test_jpeg_dimensions_reads_encoded_size():
    buffer = BytesIO()
    Image.new('RGB', (32, 16), color=(20, 40, 60)).save(buffer, format='JPEG')

    assert jpeg_dimensions(buffer.getvalue()) == (32, 16)

    with pytest.raises(ValueError, match='JPEG'):
        jpeg_dimensions(b'not-an-image')
