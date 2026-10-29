"""Navigation scans disk quota only for archive writes, preserving fail-before-mutation."""
from contextlib import contextmanager
from dataclasses import replace
import pytest
from test_navmap import mapper, down


def test_archive_budget_entered_only_on_actual_eviction_write(tmp_path,monkeypatch):
    m=mapper(tmp_path,max_active_tiles=8,height_bin_m=.2);events=[];active=[]
    @contextmanager
    def reserved():
        events.append('reserve');active.append(True)
        try:yield
        finally:active.pop();events.append('release')
    m.bind_archive_reservation(reserved)
    original=m._core._tile_archive.write_many
    def write(*args,**kwargs):
        assert active;events.append('write');return original(*args,**kwargs)
    monkeypatch.setattr(m._core._tile_archive,'write_many',write)
    m.update(down(size=41,focal=40.));assert events==[]
    m.update(down(1,x=20.,size=41,focal=40.))
    m.update(down(2,x=40.,size=41,focal=40.))
    assert events and all(events[i:i+3]==['reserve','write','release'] for i in range(0,len(events),3))


def test_quota_rejection_keeps_original_active_tiles_and_map_revision(tmp_path):
    from neusymnav.mapping.tiles import TileArchiveError
    m=mapper(tmp_path,max_active_tiles=4,height_bin_m=.2)
    m.update(down(size=9,focal=40.))
    before={k:t.planar_log_odds.tobytes() for k,t in m._core._tiles.items()};revision=m._revision
    @contextmanager
    def denied():
        raise RuntimeError('quota-denied')
        yield
    m.bind_archive_reservation(denied)
    with pytest.raises(TileArchiveError,match='quota-denied'):
        m.update(down(1,x=20.,size=9,focal=40.))
    assert m._revision==revision
    assert {k:t.planar_log_odds.tobytes() for k,t in m._core._tiles.items()}==before


def test_pipeline_does_not_scan_navigation_archive_for_memory_only_frame(tmp_path,monkeypatch):
    from test_runtime_scheduling import pipeline,wait_for,DOMAIN
    from neusymnav.contracts import FrameKey
    m=mapper(tmp_path/'tiles');p,_,_=pipeline(tmp_path,mapper=m)
    calls=[];original=p.quota.reserve
    def reserve(key,*args,**kwargs):calls.append(key);return original(key,*args,**kwargs)
    monkeypatch.setattr(p.quota,'reserve',reserve)
    obs=replace(down(size=9,focal=40.),key=FrameKey('episode','nav',0),clock_domain=DOMAIN)
    try:
        p.submit(obs);wait_for(lambda:p._latest_nav is not None)
        assert 'navigation-archive' not in calls
    finally:assert p.close(3.)['clean_shutdown']
