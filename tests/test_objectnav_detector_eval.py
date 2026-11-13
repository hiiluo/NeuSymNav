"""Phase-2 detector measurement: masks, mapping, scoring and the end-to-end scorer CLI."""
import gzip
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from neusymnav.objectnav.detector_eval.categories import GoalCategories
from neusymnav.objectnav.detector_eval.masks import bbox_xyxy, dominant_instance, iou, rle_decode, rle_encode
from neusymnav.objectnav.detector_eval.scoring import confirmation_markdown, confirmation_table, match_frame, summarize

ROOT = Path(__file__).resolve().parents[1]


def _load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/objectnav/detector_eval' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rle_round_trip_and_mask_helpers():
    rng = np.random.default_rng(0)
    cases = [rng.random((7, 9)) > .5, np.zeros((4, 5), bool), np.ones((4, 5), bool)]
    first_on = np.zeros((3, 3), bool); first_on[0, 0] = True
    cases.append(first_on)
    for mask in cases:
        assert np.array_equal(rle_decode(json.loads(json.dumps(rle_encode(mask)))), mask)
    with pytest.raises(ValueError):
        rle_decode({'shape': [2, 2], 'runs': [1, 1]})
    a = np.zeros((4, 4), bool); a[:2, :2] = True
    b = np.zeros((4, 4), bool); b[:2, :4] = True
    assert iou(a, b) == 0.5 and bbox_xyxy(b) == [0, 0, 4, 2]
    ids = np.array([[5, 5, 7, 0]] * 4)
    assert dominant_instance(ids, b) == (5, 0.5)
    assert dominant_instance(ids, np.zeros_like(b)) == (0, 0.0)


def test_frozen_mapping_loads_and_is_unambiguous():
    cats = GoalCategories.load()
    assert cats.categories == ['bed', 'chair', 'plant', 'sofa', 'toilet', 'tv_monitor']
    assert cats.goal_category('armchair') == 'chair' and cats.goal_category('television') == 'tv_monitor'
    assert cats.goal_category('lamp') is None and cats.is_near_miss('tv_monitor', 'computer monitor')
    with pytest.raises(ValueError):
        GoalCategories({'schema_version': 1, 'name': 'x', 'hm3d': {'a': ['chair'], 'b': ['chair']}})
    assert 'shower' in GoalCategories.load(dataset='mp3d_draft').labels


CHAIR, CABINET, TV = 11, 22, 33


def synthetic_frame(i, *, chair_score=None, fp_score=None, tv_label=None, depth=2.0, kind='path'):
    """8x8 frame: a chair (cols 0-3), a cabinet (cols 4-7, rows 0-3), a TV (cols 4-7, rows 4-7)."""
    ids = np.zeros((8, 8), np.uint32)
    ids[:, :4] = CHAIR
    ids[:4, 4:] = CABINET
    ids[4:, 4:] = TV
    frame = dict(frame_id='f%d' % i, scene='S', kind=kind, episode_uid='ep%d' % (i % 2), episode_category='chair',
                 goals_visible=[dict(object_id=CHAIR, category='chair', pixels=32, depth_m=depth),
                                dict(object_id=TV, category='tv_monitor', pixels=16, depth_m=depth)])
    preds = []
    if chair_score is not None:
        preds.append(dict(label='chair', score=chair_score, mask=ids == CHAIR))
    if fp_score is not None:
        preds.append(dict(label='chair', score=fp_score, mask=ids == CABINET))
    if tv_label is not None:
        preds.append(dict(label=tv_label, score=.5, mask=ids == TV))
    masks = {CHAIR: ids == CHAIR, TV: ids == TV}
    return frame, ids, masks, preds


def run_frames(specs):
    cats = GoalCategories.load()
    gts, preds = [], []
    for i, spec in enumerate(specs):
        frame, ids, masks, p = synthetic_frame(i, **spec)
        g, q = match_frame(frame, ids, masks, p, cats, {CHAIR: 'chair', TV: 'tv_monitor'},
                           {CHAIR: 'office chair', CABINET: 'kitchen cabinet', TV: 'tv'})
        gts += g
        preds += q
    return summarize(gts, preds, frames=len(specs), scenes=['S'], categories=cats.categories,
                     thresholds=(0.1, 0.3, 0.5))


def test_recall_false_positives_persistence_and_threshold_choice():
    specs = ([dict(chair_score=.6, fp_score=.2, tv_label='television')] * 2 +
             [dict(chair_score=.2, fp_score=.2, tv_label='computer monitor')] +
             [dict(fp_score=.2, depth=4.0)])
    report = run_frames(specs)
    chair = {c['threshold']: c for c in report['categories']['chair']['curve']}
    assert chair[0.1]['recall_loose'] == pytest.approx(3 / 4) and chair[0.3]['recall_loose'] == pytest.approx(2 / 4)
    assert chair[0.1]['false_positives'] == 4 and chair[0.1]['persistent_fp_instances'] == 1
    assert chair[0.3]['false_positives'] == 0 and chair[0.3]['persistent_fp_per_scene'] == 0
    assert chair[0.1]['by_distance']['3-5 m']['recall_loose'] == 0.0
    assert chair[0.1]['instance_recall_1'] == 1.0 and chair[0.1]['instance_recall_3'] == 1.0
    assert chair[0.5]['episode_ceiling'] == 1.0          # both episodes have a 0.6 chair within 3 m
    assert chair[0.1]['episode_ceiling'] == 1.0
    block = report['categories']['chair']
    assert block['recommended_threshold'] == 0.1      # 1 persistent FP instance in 1 scene is within <= 1/scene
    tv = {c['threshold']: c for c in report['categories']['tv_monitor']['curve']}
    assert tv[0.1]['recall_loose'] == pytest.approx(2 / 4)
    assert report['categories']['tv_monitor']['near_miss_labels'] == {'computer monitor': 1}
    assert report['categories']['chair']['top_false_positive_sources'] == {'kitchen cabinet': 4}


def test_scorer_cli_end_to_end(tmp_path):
    views = tmp_path / 'views'
    (views / 'frames').mkdir(parents=True)
    rows, preds = [], []
    for i, spec in enumerate([dict(chair_score=.7, fp_score=.4)] * 3):
        frame, ids, _, p = synthetic_frame(i, **spec)
        np.savez_compressed(views / 'frames' / (frame['frame_id'] + '.npz'), rgb=np.zeros((8, 8, 3), np.uint8),
                            depth_mm=np.full((8, 8), 2000, np.uint16), semantic=ids)
        rows.append(frame)
        preds.append(dict(frame_id=frame['frame_id'], cap_reached=False,
                          detections=[dict(label=d['label'], score=d['score'], rle=rle_encode(d['mask']))
                                      for d in p]))
    (views / 'views.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    (views / 'scenes.json').write_text(json.dumps({'scenes': {'S': dict(
        goal_instances={'chair': [dict(object_id=CHAIR, name='office chair', seen=True)],
                        'tv_monitor': [dict(object_id=TV, name='tv', seen=True)]},
        alignment=dict(frames=1, passed=1, failures=[]),
        names={str(CHAIR): 'office chair', str(CABINET): 'kitchen cabinet', str(TV): 'tv'})}}))
    (tmp_path / 'p.jsonl').write_text(''.join(json.dumps(p) + '\n' for p in preds))
    _load_tool('score_detector').main(['--views', str(views), '--predictions', str(tmp_path / 'p.jsonl'),
                                       '--out-dir', str(tmp_path / 'report')])
    report = json.loads((tmp_path / 'report/report.json').read_text())
    chair = report['categories']['chair']
    assert chair['recommended_threshold'] == 0.05     # one persistent FP instance in the only scene
    persistent = {c['threshold']: c['persistent_fp_instances'] for c in chair['curve']}
    assert persistent[0.35] == 1 and persistent[0.5] == 0
    at = {c['threshold']: c for c in chair['curve']}[0.05]
    assert at['recall_strict'] == 1.0 and at['precision_strict'] == 0.5
    assert report['prediction_scores']['min'] == 0.4
    assert 'Phase 2 detector report' in (tmp_path / 'report/report.md').read_text()
    with gzip.open(tmp_path / 'report/matches.jsonl.gz', 'rt') as stream:
        kinds = [json.loads(l)['row_type'] for l in stream]
    assert kinds.count('gt') == 6 and kinds.count('pred') == 6


def test_detector_observation_is_a_valid_runtime_contract():
    run = _load_tool('run_detector')
    obs = run.observation(3, np.zeros((480, 640, 3), np.uint8), np.full((480, 640), 1500, np.uint16))
    assert obs.modality == 'rgbd' and obs.key.frame_index == 3 and obs.clock_domain.startswith('replay:')
    assert float(obs.depth_m[0, 0]) == pytest.approx(1.5) and obs.K[0, 0] == pytest.approx(320.0)


def test_unlisted_same_category_objects_are_not_false_positives_and_misses_are_explained():
    cats = GoalCategories.load()
    frame, ids, masks, _ = synthetic_frame(0)
    preds = [dict(label='chair', score=.6, mask=ids == CABINET),        # cabinet is an unlisted chair here
             dict(label='bench', score=.7, mask=ids == CHAIR)]          # detector calls the goal chair "bench"
    g, q = match_frame(frame, ids, masks, preds, cats, {CHAIR: 'chair', TV: 'tv_monitor'},
                       {CHAIR: 'chair', CABINET: 'chair', TV: 'tv'}, unlisted={CABINET: 'chair'})
    report = summarize(g, q, frames=1, scenes=['S'], categories=cats.categories, thresholds=(0.25,))
    chair = report['categories']['chair']
    assert chair['curve'][0]['false_positives'] == 0 and chair['curve'][0]['unlisted_same_category'] == 1
    assert chair['missed_at_0_25'] == 1 and chair['labels_on_missed_at_0_25'] == {'bench': 1}
    json.dumps(report)


def test_confirmation_table_counts_instances_views_and_vote():
    cats = GoalCategories.load()
    gts, preds = [], []
    specs = [dict(chair_score=.6, fp_score=.6)] * 2 + [dict(chair_score=.6)]
    for i, spec in enumerate(specs):
        frame, ids, masks, p = synthetic_frame(i, **spec)
        p.append(dict(label='sofa', score=.9, mask=ids == CABINET))      # cabinet also called sofa, more often
        g, q = match_frame(frame, ids, masks, p, cats, {CHAIR: 'chair', TV: 'tv_monitor'},
                           {CHAIR: 'chair', CABINET: 'cabinet', TV: 'tv'})
        gts += g
        preds += q
    rows = confirmation_table(gts, preds, scenes=['S'], categories=cats.categories, thresholds=(0.5,))
    get = {(r['min_views'], r['vote']): r['categories'] for r in rows}
    assert get[(3, False)]['chair'] == dict(confirmed_goal_instances=1, goal_instances=1, recall=1.0,
                                            wrong_instances_per_scene=0.0)
    assert get[(2, False)]['chair']['wrong_instances_per_scene'] == 1.0   # cabinet seen as chair twice
    assert get[(2, True)]['chair']['wrong_instances_per_scene'] == 0.0    # ...but called sofa 3 times: vote drops it
    assert get[(3, False)]['sofa']['wrong_instances_per_scene'] == 1.0
    assert 'Min views' in confirmation_markdown(rows, cats.categories)
