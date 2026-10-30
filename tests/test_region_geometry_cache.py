"""Pure geometry may be reused; source/revision acceptance is never cached."""
import math
import random
import pytest
from neusymnav.regions import geometry as g


def test_exact_ring_validation_reuses_computation_and_rechecks_changed_input(monkeypatch):
    g._cached_valid_ring.cache_clear();calls=[];original=g._valid_ring
    monkeypatch.setattr(g,'_valid_ring',lambda ring:(calls.append(ring),original(ring))[1])
    ring=[[0.,0.],[2.,0.],[2.,2.],[0.,2.]]
    assert g.valid_ring(ring) and g.valid_ring([p[:] for p in ring])
    assert len(calls)==1
    ring[1]=[0.,2.]
    assert not g.valid_ring(ring) and len(calls)==2
    assert not g.valid_ring([[math.nan,0.],[1.,0.],[0.,1.]])
    assert len(calls)==2


def test_intersection_cache_preserves_signed_zero_and_has_fixed_bound(monkeypatch):
    g._cached_ring_intersection_area.cache_clear();calls=[]
    original=g._ring_intersection_area_uncached
    monkeypatch.setattr(g,'_ring_intersection_area_uncached',lambda a,b:(calls.append((a,b)),original(a,b))[1])
    ring=((0.,0.),(1.,0.),(1.,1.),(0.,1.))
    assert g._ring_intersection_area(ring,ring)==1.
    assert g._ring_intersection_area(ring,ring)==1. and len(calls)==1
    negative=((-0.,0.),*ring[1:])
    assert g._ring_intersection_area(negative,ring)==1. and len(calls)==2
    for index in range(90):
        shifted=tuple((x+index,y) for x,y in ring)
        assert g._ring_intersection_area(shifted,ring)==original(shifted,ring)
    assert g._cached_ring_intersection_area.cache_info().currsize==64


def test_cached_geometry_matches_scalar_oracle_for_boundary_and_concave_rings():
    rng=random.Random(513)
    rings=[((0.,0.),(2.,0.),(1.,1.),(2.,2.),(0.,2.)),
           ((0.,0.),(1e-10,0.),(1.,1.),(0.,1.)),
           ((0.,0.),(1.,1.),(0.,1.),(1.,0.))]
    for _ in range(50):
        shift=rng.uniform(-3,3)
        rings.append(tuple((x+shift,y-shift) for x,y in ((0.,0.),(2.,0.),(2.,2.),(0.,2.))))
    for a in rings:
        assert g.valid_ring(a)==g._valid_ring(a)
        for b in rings[:4]:
            assert g._ring_intersection_area(a,b)==g._ring_intersection_area_uncached(a,b)
