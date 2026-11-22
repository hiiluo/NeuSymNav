"""B3-semsearch (paper mode): value map fusion, value-guided frontier choice, SigLIP crop veto."""
import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.objectnav.detector_eval.categories import GoalCategories
from neusymnav.objectnav.paper.b3.policy import PaperB3Config, PaperB3Policy
from neusymnav.objectnav.paper.b3.value_map import ValueMap
from neusymnav.objectnav.paper.obstacle_map import ObstacleMap
from neusymnav.objectnav.paper.runner import PaperRunner

import test_objectnav_paper_b0 as base
from test_objectnav_b1_vlm import RgbRoom

CFG = base.ROOT / 'configs/objectnav/paper-b3-v1.json'


class FakeClip:
    """Image embedding = unit vector picked by ``top``; text embeddings are the axes."""
    def __init__(self, top='a chair', frame_score=0.1):
        self.top, self.frame_score, self.calls = top, frame_score, []
        self.text = {}

    def embed(self, images):
        self.calls.append([np.asarray(i).shape for i in images])
        return np.ones((len(images), 1), np.float32)

    def scores(self, feats, prompts):
        if len(prompts) == 1:
            return np.full((len(feats), 1), self.frame_score, np.float32)
        return np.array([[1.0 if p == self.top else 0.0 for p in prompts]] * len(feats), np.float32)

    def close(self):
        pass


def _cfg(**over):
    data = json.loads(CFG.read_text())
    data.pop('schema_version')
    data['clip_verify'] = dict(data['clip_verify'], targets={'chair': ['a chair', 'a sofa', 'a table']})
    data.update(over)
    return PaperB3Config(**data)


def _run(tmp_path, cfg, clip):
    sim = RgbRoom()
    calls = []

    def factory():
        pol = PaperB3Policy(cfg, categories=GoalCategories.load(), detector_factory=base._detector(sim, calls),
                            evidence_dir=tmp_path / 'evidence', projector=base.FakeProjector(), clip=clip)
        return pol
    runner = PaperRunner(base.PROTOCOL, out_dir=tmp_path, run_id='b3', sim_factory=lambda: sim,
                         policy_factory=factory, log=lambda *_: None)
    episode = SimpleNamespace(uid='hm3d_v2/val/Room/1', scene_path='/room.glb', object_category='chair')
    return json.loads(runner.run([episode]).read_text().splitlines()[0])


def test_config_validation():
    cfg = PaperB3Config.load(CFG)
    assert set(cfg.clip_verify['targets']) == {'sofa', 'toilet', 'bed'}
    with pytest.raises(ValueError):
        _cfg(semantic=dict(cfg.semantic, extra=1))
    with pytest.raises(ValueError):
        _cfg(semantic=None)                                    # clip_verify needs the semantic model


def test_value_map_fuses_by_view_angle():
    m = ObstacleMap(origin_xy=(0.0, 0.0), size_m=4.0)
    m.level = m._select_level(0.0)
    r, c = m.cell((1.0, 0.0))
    mask = np.zeros((3, 3), bool)
    mask[1, 1] = True
    m.last_frame = (r - 1, c - 1, mask)
    vm = ValueMap(79.0)
    vm.update(m, (0.0, 0.0), 0.0, 0.2)                         # cell straight ahead: confidence 1
    assert vm.at(m, (r, c), 0) == pytest.approx(0.2)
    vm.update(m, (0.0, 0.0), math.radians(35.0), 0.8)          # same cell near the image edge: low weight
    v = vm.at(m, (r, c), 0)
    assert 0.2 < v < 0.3
    vm.update(m, (0.0, 0.0), 0.0, 0.8)                         # head-on again: new view weighs as much
    assert vm.at(m, (r, c), 0) > 0.45
    assert vm.at(m, m.cell((-1.5, -1.5)), 0) is None


def test_accepted_crop_stops_and_value_map_runs(tmp_path):
    clip = FakeClip(top='a chair')
    rec = _run(tmp_path, _cfg(), clip)
    pol = rec['diagnostics']['policy']
    assert rec['diagnostics']['end_reason'] == 'policy_stop:confirmed_target'
    assert pol['semantic']['views'] > 0 and pol['semantic']['value_updates'] > 0
    assert pol['clip_verify'][0]['accepted'] is True and pol['clip_verify'][0]['top'] == 'a chair'


def test_rejected_crop_vetoes_the_candidate(tmp_path):
    rec = _run(tmp_path, _cfg(), FakeClip(top='a sofa'))
    pol = rec['diagnostics']['policy']
    assert rec['diagnostics']['end_reason'] == 'policy_stop:frontiers_exhausted'
    assert pol['clip_verify'][0]['accepted'] is False
    assert any(e['note'] == 'reject:clip_rejected' for e in pol['events'])


class GapClip(FakeClip):
    """Crop scores: the target prompt 0.050, the first confusable ``0.050 + gap``."""
    def __init__(self, gap):
        super().__init__()
        self.gap = gap

    def scores(self, feats, prompts):
        if len(prompts) == 1:
            return np.full((len(feats), 1), self.frame_score, np.float32)
        row = [0.05] + [0.05 + self.gap] + [0.0] * (len(prompts) - 2)
        return np.array([row] * len(feats), np.float32)


def test_reject_margin_keeps_near_ties(tmp_path):
    cv = dict(margin=0.15, reject_margin=0.005, targets={'chair': ['a chair', 'a sofa', 'a table']})
    rec = _run(tmp_path / 'a', _cfg(clip_verify=cv), GapClip(0.002))
    assert rec['diagnostics']['end_reason'] == 'policy_stop:confirmed_target'
    assert rec['diagnostics']['policy']['clip_verify'][0]['accepted'] is True
    rec = _run(tmp_path / 'b', _cfg(clip_verify=cv), GapClip(0.02))
    assert rec['diagnostics']['policy']['clip_verify'][0]['accepted'] is False


def test_pos_neg_prompts():
    from neusymnav.objectnav.paper.b3.policy import verify_prompts
    assert verify_prompts({'pos': ['a plant', 'a vase of flowers'], 'neg': ['a vase']}) == (
        ['a plant', 'a vase of flowers', 'a vase'], 2)
    with pytest.raises(ValueError):
        _cfg(clip_verify=dict(margin=0.1, targets={'chair': {'pos': ['a chair'], 'neg': []}}))


def test_low_conf_filter_and_validation():
    from neusymnav.objectnav.paper.b3.low_conf import FilteredClient
    det = lambda label, score, i: SimpleNamespace(raw_label=label, score=score, detection_id=i)
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class Batch:
        detections: tuple
    inner = SimpleNamespace(infer=lambda o: Batch((det('plant', 0.12, 1), det('chair', 0.12, 2), det('chair', 0.6, 3))))
    out = FilteredClient(inner, ['plant'], 0.25).infer(None)
    assert [d.detection_id for d in out.detections] == [1, 3]
    with pytest.raises(ValueError):
        _cfg(low_conf=dict(detector_confidence=0.1, targets={'plant': 0.05}))     # below the worker floor
    cfg = _cfg(low_conf=dict(detector_confidence=0.1, targets={'chair': 0.12}))
    assert cfg.low_conf['targets']['chair'] == 0.12


def test_low_conf_swaps_worker_and_threshold_per_episode():
    cfg = _cfg(low_conf=dict(detector_confidence=0.1, targets={'chair': 0.12}))
    made = []

    def low_factory():
        made.append('low')
        return SimpleNamespace(infer=lambda o: None, close=lambda: made.append('low-closed'))
    base_client = SimpleNamespace(close=lambda: made.append('base-closed'))
    pol = PaperB3Policy(cfg, categories=GoalCategories.load(), detector_factory=lambda: base_client,
                        projector=base.FakeProjector(), clip=FakeClip(), low_detector_factory=low_factory)
    pol.reset(SimpleNamespace(uid='a', scene_path='/r.glb', object_category='chair'))
    assert pol._client is pol._low and pol.rule['categories']['chair']['threshold'] == 0.12
    pol.reset(SimpleNamespace(uid='b', scene_path='/r.glb', object_category='bed'))
    assert pol._client is base_client and pol.rule['categories']['chair']['threshold'] == 0.5
    assert pol._base_rule['categories']['chair']['threshold'] == 0.5
    pol.close()
    assert made == ['low', 'base-closed', 'low-closed']


EG = dict(max_steps=500, min_step=200, check_every=5, step_m=0.25, overhead=1.3, margin_steps=25)


def test_endgame_stops_at_rejected_object_instead_of_ending_undecided(tmp_path):
    rec = _run(tmp_path, _cfg(endgame=EG), FakeClip(top='a sofa'))      # SigLIP rejects the only chair
    pol = rec['diagnostics']['policy']
    assert pol['clip_verify'][0]['accepted'] is False
    assert pol['endgame'][0]['why'] == 'exhausted' and pol['endgame'][0]['was_rejected'] == 'clip_rejected'
    assert rec['diagnostics']['end_reason'] == 'policy_stop:fallback_target'


def test_endgame_config_validation():
    with pytest.raises(ValueError):
        _cfg(endgame=dict(EG, extra=1))
    with pytest.raises(ValueError):
        _cfg(endgame=dict(EG, min_step=600))


def test_early_stop_rule():
    from neusymnav.objectnav.paper.b3 import early_stop
    fp = np.array([[2.0, 0.0]])
    dist = lambda pts, xy: float(np.min(np.hypot(pts[:, 0] - xy[0], pts[:, 1] - xy[1])))
    assert early_stop.arrives_next_step(fp, (1.45, 0.0), 0.0, 0.25, 0.4, dist)          # 0.55 -> 0.30
    assert not early_stop.arrives_next_step(fp, (1.0, 0.0), 0.0, 0.25, 0.4, dist)       # 1.00 -> 0.75
    assert not early_stop.arrives_next_step(fp, (1.45, 0.0), math.pi, 0.25, 0.4, dist)  # stepping away
    assert not early_stop.arrives_next_step(fp, (1.7, 0.0), 0.0, 0.25, 0.4, dist)       # already inside
    with pytest.raises(ValueError):
        _cfg(early_stop={'step_m': 0.25, 'x': 1})


def test_early_stop_arrives_one_step_before_and_stops(tmp_path):
    base_rec = _run(tmp_path / 'a', _cfg(), FakeClip(top='a chair'))
    rec = _run(tmp_path / 'b', _cfg(early_stop={'step_m': 0.25}), FakeClip(top='a chair'))
    pol = rec['diagnostics']['policy']
    assert rec['diagnostics']['end_reason'] == 'policy_stop:confirmed_target'
    assert pol['early_stop'] and pol['early_stop'][0]['distance_m'] > 0.4
    assert 0.4 < pol['stop']['distance_to_object_m'] <= 0.65 + 0.05
    assert rec['steps'] <= base_rec['steps']
