from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest

from neusymnav.objectnav.b0.detection import recipe_from_profile
from neusymnav.objectnav.detector_eval.categories import GoalCategories
from neusymnav.objectnav.paper.b0 import make_policy_factory
from test_objectnav_paper_b0 import _config, RoomSim

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def detector_profile(tmp_path):
    """Source-only profile for testing pin validation without loading any model."""
    def pin(path):
        return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    checkpoint = tmp_path / 'checkpoint.bin'
    checkpoint.write_bytes(b'checkpoint fixture')
    encoder = tmp_path / 'mobileclip2_b.ts'
    encoder.write_bytes(b'encoder fixture')
    worker = tmp_path / 'detector_worker.py'
    worker.write_bytes(b'# Detector launch fixture\n')
    profile = tmp_path / 'detector.json'
    profile.write_text(json.dumps(dict(
        detector=dict(checkpoint=pin(checkpoint), encoder=pin(encoder),
                      taxonomy=pin(ROOT / 'configs/taxonomy-v1.json'), checkpoint_license='fixture',
                      imgsz=640, max_detections=30, confidence_threshold=0.25, device='cpu'),
        workers=dict(detector=dict(python=pin(worker), script=pin(worker))),
    )))
    return profile


def test_plant_override_pins_distinct_lexicon_but_keeps_checkpoint(detector_profile):
    from neusymnav.objectnav.b0.detection import with_taxonomy

    base = recipe_from_profile(detector_profile)
    path = ROOT/'configs/objectnav/paper-plant-taxonomy-v1.json'
    plant = with_taxonomy(base, path)
    assert plant['recipe']['taxonomy_sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert plant['recipe']['checkpoint_sha256'] == base['recipe']['checkpoint_sha256']
    assert plant['recipe']['encoder_sha256'] == base['recipe']['encoder_sha256']
    assert plant['recipe']['taxonomy_path'] != base['recipe']['taxonomy_path']


def test_shared_plant_mapping_distinguishes_empty_vase():
    cats = GoalCategories.load(ROOT/'configs/objectnav/paper-goal-categories-v2.json')
    for label in ('plant', 'potted plant', 'houseplant', 'flowers in a vase'):
        assert cats.goal_category(label) == 'plant'
    assert cats.goal_category('vase') is None
    assert cats.goal_category('chair') == 'chair'


def test_shared_factory_chooses_plant_worker_only_for_plant_episode(monkeypatch, detector_profile):
    from unittest.mock import Mock
    from neusymnav.objectnav.b0 import detection
    from neusymnav.objectnav.paper.runner import PaperEpisode

    clients = []
    def client_for(launch):
        def factory():
            client = Mock()
            clients.append((launch['recipe']['taxonomy_path'], client))
            return client
        return factory

    monkeypatch.setattr(detection, 'client_from_launch', client_for, raising=False)
    cfg = replace(_config(), detector_profile=str(detector_profile),
                  plant_taxonomy='configs/objectnav/paper-plant-taxonomy-v1.json')
    policy = make_policy_factory(cfg)()
    try:
        policy.reset(PaperEpisode('plant', 'plant'))
        policy.reset(PaperEpisode('chair', 'chair'))
        assert clients[0][0].endswith('configs/objectnav/paper-plant-taxonomy-v1.json')
        assert not clients[1][0].endswith('paper-plant-taxonomy-v1.json')
        clients[0][1].close.assert_called_once()
    finally:
        policy.close()


def test_upgraded_baseline_uses_reachable_component_and_refuses_blind_probe(monkeypatch):
    from types import SimpleNamespace
    import numpy as np

    from neusymnav.objectnav.paper import b0
    from neusymnav.objectnav.paper.nav import NavResult

    policy = b0.PaperB0Policy(replace(_config(), reachable_approach=True), categories=GoalCategories.load(),
                              detector_factory=lambda: object(), projector=object())
    reachable = np.array([[True, False]])
    policy.nav = SimpleNamespace(yaw=0., robot_xy=(0., 0.), trav=np.ones((1, 2)),
                                 reachable=lambda: reachable, face=lambda _xy: None,
                                 _forward_ok=lambda _yaw: None, escape_turn=lambda: 'turn_left',
                                 go_to_cells=lambda *_a, **_kw: NavResult(None, 'unreachable'))
    policy._fallback = True
    policy.state_steps = 1
    policy._no_path = 0
    policy._reached_far = 0
    cand = SimpleNamespace(rejected=None, points=np.array([[1., 0., .6]]), centroid_xy=(1., 0.))
    monkeypatch.setattr(policy, '_target', lambda: cand)
    monkeypatch.setattr(policy, '_grid', lambda: None)

    def goals(_grid, allowed, *_args, **_kwargs):
        assert allowed is reachable
        return [(0, 0)], {}, 'closer'

    monkeypatch.setattr(b0, 'approach_goals', goals)
    assert policy._act_approach() == 'turn_left'
