"""Independent scalar oracle for fused local expiry and spatial forgetting."""
from types import SimpleNamespace
import numpy as np
import pytest
from neusymnav.mapping import rolling

FIELDS=('planar_log_odds','height_log_odds','floor_support','planar_last_ns','height_last_ns','floor_last_ns')


def tile(seed, strided=False):
    rng=np.random.default_rng(seed);n=8 if strided else 4
    p=rng.choice([np.nan,-1.,1.],size=(n,n)).astype(np.float32)
    h=rng.choice([np.nan,-1.,1.],size=(n,n,3)).astype(np.float32)
    f=rng.choice([False,True],size=(n,n))
    stamps=[rng.choice([-1,0,2,6,9],size=a.shape).astype(np.int64) for a in (p,h,f)]
    arrays=[p,h,f,*stamps]
    if strided:arrays=[a[::2,::2] for a in arrays]
    return SimpleNamespace(**dict(zip(FIELDS,arrays)))


def oracle(t,key,window,now,ttl):
    counts=[0]*6;size=t.planar_log_odds.shape[0]
    for r in range(size):
        for c in range(size):
            outside=not(window.min_row<=key[0]*size+r<window.end_row and window.min_col<=key[1]*size+c<window.end_col)
            for a,s,ei,di,index in [(t.planar_log_odds,t.planar_last_ns,0,3,(r,c)),(t.floor_support,t.floor_last_ns,2,5,(r,c))]+[(t.height_log_odds,t.height_last_ns,1,4,(r,c,b)) for b in range(t.height_log_odds.shape[2])]:
                floor=ei==2
                if s[index]>=0 and now-int(s[index])>=ttl:
                    counts[ei]+=1;a[index]=False if floor else np.nan;s[index]=-1
                if outside:
                    counts[di]+=int(bool(a[index]) if floor else not np.isnan(a[index]))
                    a[index]=False if floor else np.nan;s[index]=-1
    return tuple(counts)


@pytest.mark.parametrize('strided',[False,True])
@pytest.mark.parametrize('key',[(-1,-1),(0,0),(1,-1)])
def test_fused_maintenance_matches_scalar_expiry_and_crop_oracle(strided,key):
    t=tile(12,strided);reference=SimpleNamespace(**{k:getattr(t,k).copy() for k in FIELDS})
    w=rolling.RollingWindow(-2,-1,5)
    expected=oracle(reference,key,w,10,4)
    from neusymnav.mapping._retention_kernel import warmup_maintenance_kernel,apply_maintenance
    warmed=warmup_maintenance_kernel()
    if not strided and warmed:
        probe=SimpleNamespace(**{k:getattr(t,k).copy() for k in FIELDS})
        assert apply_maintenance(probe,key,4,w,10,4)==expected
    actual=rolling.maintain_tile(t,key,4,w,now_ns=10,retention_ns=4)
    assert actual==expected
    for name in FIELDS:np.testing.assert_array_equal(getattr(t,name),getattr(reference,name))


def test_unwarmed_or_strided_layout_falls_back_without_new_jit_signatures(monkeypatch):
    from neusymnav.mapping import _retention_kernel as k
    if not k.warmup_maintenance_kernel():pytest.skip("Numba unavailable; fallback covered by oracle tests")
    before=tuple(k._dispatcher.signatures)
    t=tile(9,True);w=rolling.RollingWindow(0,0,4)
    assert k.apply_maintenance(t,(0,0),4,w,10,4) is None
    assert tuple(k._dispatcher.signatures)==before
    monkeypatch.setattr(k,'_entry',None)
    t=tile(7);ref=SimpleNamespace(**{n:getattr(t,n).copy() for n in FIELDS})
    expected=oracle(ref,(0,0),w,10,4)
    assert rolling.maintain_tile(t,(0,0),4,w,now_ns=10,retention_ns=4)==expected
    assert tuple(k._dispatcher.signatures)==before
    for n in FIELDS:np.testing.assert_array_equal(getattr(t,n),getattr(ref,n))
