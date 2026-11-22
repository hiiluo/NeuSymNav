"""B1-vlm (paper mode): a VLM answer that does not name the target vetoes the STOP candidate."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.objectnav.detector_eval.categories import GoalCategories
from neusymnav.objectnav.paper.b0 import PaperB0Config, PaperB0Policy
from neusymnav.objectnav.paper.runner import PaperRunner
from neusymnav.objectnav.paper.vlm_verify import VlmVerifier

import test_objectnav_paper_b0 as base

CFG = base.ROOT / 'configs/objectnav/paper-b1v-v1.json'


class RgbRoom(base.RoomSim):
    def _render(self):
        obs = super()._render()
        obs.rgb = np.full((self.H, self.W, 3), 128, np.uint8)
        return obs


def _run(tmp_path, cfg, answer, asked):
    sim = RgbRoom()
    calls = []

    def factory():
        pol = PaperB0Policy(cfg, categories=GoalCategories.load(), detector_factory=base._detector(sim, calls),
                            evidence_dir=tmp_path / 'evidence', projector=base.FakeProjector())
        pol.vlm.ask = lambda crop: asked.append(crop.shape) or answer
        return pol
    runner = PaperRunner(base.PROTOCOL, out_dir=tmp_path, run_id='b1v', sim_factory=lambda: sim,
                         policy_factory=factory, log=lambda *_: None)
    episode = SimpleNamespace(uid='hm3d_v2/val/Room/1', scene_path='/room.glb', object_category='chair')
    return json.loads(runner.run([episode]).read_text().splitlines()[0])


def _cfg():
    data = json.loads(CFG.read_text())
    data.pop('schema_version')
    data['vlm_verify'] = dict(data['vlm_verify'], targets={'chair': ['chair']})
    return PaperB0Config(**data)


def test_config_and_accepts():
    cfg = PaperB0Config.load(CFG)
    v = VlmVerifier(cfg.vlm_verify)
    assert set(v.targets) == {'sofa', 'toilet'}
    assert v.accepts('sofa', 'Couch') and v.accepts('sofa', 'sectional sofa') and not v.accepts('sofa', 'armchair')
    assert v.accepts('toilet', 'toilet') and not v.accepts('toilet', 'bed')
    with pytest.raises(ValueError):
        base._config(vlm_verify={'targets': {'sofa': ['sofa']}})


def test_accepted_answer_stops(tmp_path):
    asked = []
    rec = _run(tmp_path, _cfg(), 'chair', asked)
    assert rec['diagnostics']['end_reason'] == 'policy_stop:confirmed_target'
    assert len(asked) == 1 and asked[0][2] == 3
    assert rec['diagnostics']['policy']['vlm'][0]['accepted'] is True


def test_rejected_answer_vetoes_the_candidate(tmp_path):
    asked = []
    rec = _run(tmp_path, _cfg(), 'table', asked)
    pol = rec['diagnostics']['policy']
    assert rec['diagnostics']['end_reason'] == 'policy_stop:frontiers_exhausted'
    assert len(asked) == 1 and pol['vlm'][0]['accepted'] is False
    assert any(e['note'] == 'reject:vlm_rejected' for e in pol['events'])
