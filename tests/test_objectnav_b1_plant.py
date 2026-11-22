"""B1-plant (paper mode): a raw detector label counted as a goal only in that goal's episodes."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.objectnav.detector_eval.categories import GoalCategories
from neusymnav.objectnav.paper.b0 import PaperB0Config, PaperB0Policy
from neusymnav.objectnav.paper.runner import PaperRunner

import test_objectnav_paper_b0 as base

CFG = base.ROOT / 'configs/objectnav/paper-b1p-v2.json'


def _detector(sim, label, score):
    class Client:
        def infer(self, obs):
            dets = ()
            if sim.chair_pixels >= 20:
                mask = np.zeros((4, 4), bool)
                mask[1:3, 1:3] = True
                dets = (SimpleNamespace(detection_id='d0', raw_label=label, score=score, mask=mask),)
            return SimpleNamespace(detections=dets, cap_reached=False)

        def close(self):
            pass
    return Client


def _run(tmp_path, cfg, target, label, score):
    sim = base.RoomSim()
    factory = lambda: PaperB0Policy(base.small_map(cfg), categories=GoalCategories.load(), detector_factory=_detector(sim, label, score),  # noqa: E731
                                    evidence_dir=tmp_path / 'evidence', projector=base.FakeProjector())
    runner = PaperRunner(base.PROTOCOL, out_dir=tmp_path, run_id='b1p', sim_factory=lambda: sim,
                         policy_factory=factory, log=lambda *_: None)
    episode = SimpleNamespace(uid='hm3d_v2/val/Room/1', scene_path='/room.glb', object_category=target)
    return json.loads(runner.run([episode]).read_text().splitlines()[0])


def test_config_loads_and_validates():
    cfg = PaperB0Config.load(CFG)
    assert cfg.target_labels == {'vase': {'goal': 'plant', 'min_score': 0.5}} and cfg.revisit is None
    assert PaperB0Config.load(base.ROOT / 'configs/objectnav/paper-b0-v1.json').target_labels is None
    with pytest.raises(ValueError):
        base._config(target_labels={'vase': {'goal': 'plant'}})


def test_vase_confirms_plant_in_plant_episode(tmp_path):
    rec = _run(tmp_path, PaperB0Config.load(CFG), 'plant', 'vase', 0.7)
    assert rec['diagnostics']['end_reason'] == 'policy_stop:confirmed_target'
    pol = rec['diagnostics']['policy']
    assert pol['candidates'][0]['views'] == {'plant': pol['candidates'][0]['views']['plant']}


@pytest.mark.parametrize('target,score', [('plant', 0.4), ('chair', 0.9)])
def test_vase_ignored_below_score_or_in_other_episodes(tmp_path, target, score):
    rec = _run(tmp_path, PaperB0Config.load(CFG), target, 'vase', score)
    assert rec['diagnostics']['end_reason'] == 'policy_stop:frontiers_exhausted'
    assert rec['diagnostics']['policy']['candidates'] == []


def test_b0_config_never_uses_vase(tmp_path):
    rec = _run(tmp_path, base._config(), 'plant', 'vase', 0.9)
    assert rec['diagnostics']['policy']['candidates'] == []
