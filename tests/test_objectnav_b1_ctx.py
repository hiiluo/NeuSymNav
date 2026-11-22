"""B1-ctx: context prior on frontier choice (paper mode)."""
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.objectnav.paper.context_prior import ContextPrior

CFG = dict(min_score=0.4, bonus_m=4.0, sigma_m=1.5, radius_m=4.0, level_m=0.5,
           weights={'toilet': {'sink': 1.0, 'bathtub': 1.0}})


def _frontiers():
    near = SimpleNamespace(cell=(0, 0), xy=(1.0, 0.0))
    far = SimpleNamespace(cell=(1, 1), xy=(-3.0, 0.0))
    cost = {(0, 0): 1.0, (1, 1): 3.0}
    return [near, far], cost.__getitem__


def test_no_context_is_b0_nearest():
    ctx = ContextPrior(CFG, 'toilet')
    fr, cost = _frontiers()
    assert ctx.choose(fr, cost, 0.0) is fr[0]
    assert ctx.summary()['choices'] == 0


def test_related_object_pulls_frontier_and_filters():
    ctx = ContextPrior(CFG, 'toilet')
    pts = np.array([[-3.2, 0.1, 0.5], [-3.0, -0.1, 0.6]])
    ctx.add('sink', 0.3, pts, 0.0)                 # below min_score: ignored
    ctx.add('bed', 0.9, pts, 0.0)                  # no weight for this target: ignored
    ctx.add('sink', 0.8, pts, 2.5)                 # other floor: kept but not used on floor 0
    fr, cost = _frontiers()
    assert ctx.choose(fr, cost, 0.0) is fr[0]
    ctx.add('sink', 0.8, pts, 0.0)
    assert ctx.choose(fr, cost, 0.0) is fr[1]      # 3 - 4*~0.93 < 1
    s = ctx.summary()
    assert s['labels'] == {'sink': 2} and s['changed'] == 1


def test_other_target_has_no_prior():
    ctx = ContextPrior(CFG, 'bed')
    ctx.add('sink', 0.9, np.array([[-3.0, 0.0, 0.5]]), 0.0)
    fr, cost = _frontiers()
    assert ctx.choose(fr, cost, 0.0) is fr[0]


def test_validate():
    ContextPrior.validate(CFG)
    with pytest.raises(ValueError):
        ContextPrior.validate(dict(CFG, extra=1))
    with pytest.raises(ValueError):
        ContextPrior.validate(dict(CFG, weights={'toilet': {'sink': 1.5}}))
