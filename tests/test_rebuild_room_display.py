"""Separate, revision-safe display for the source Rebuild map and regions."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')

from dataclasses import replace

import numpy as np
import pytest
from PyQt5 import QtWidgets

from neusymnav.contracts import (
    FrameKey,Region,RegionSnapshot,RoomMapSnapshot,RoomPipelinePublication,
)
from neusymnav.visualization.desktop import DashboardWindow
from neusymnav.visualization.publisher import DisplayPublisher,DisplaySources
from test_display_snapshot import make_publisher


def room_publication(*,latest_revision=1,accepted_revision=1,stale=False):
    states=np.array([[0,-1],[100,0]],dtype=np.int8)
    heights=np.full((2,2),np.nan,dtype=np.float64)
    masks=np.zeros((2,2),dtype=bool)
    sha='b'*64
    m=RoomMapSnapshot('e','rebuild-m3:e',latest_revision,
        FrameKey('e','rgbd',latest_revision+1),150+latest_revision,'clock','cal-v1',sha,
        .05,(0.,0.),states,heights,heights,masks,masks,
        latest_revision,latest_revision,sha,'c'*64,'d'*64,'e'*64)
    regions=None;m5=None
    if accepted_revision is not None:
        m5=accepted_revision
        regions=RegionSnapshot('e',m5,accepted_revision,'f',{
            'region:f:1':Region('region:f:1',np.array([[0.,0.],[.05,0.],[.05,.05]]))
        },stale)
    accepted_map=(None if accepted_revision is None else replace(m,
        revision=accepted_revision,source=FrameKey('e','rgbd',accepted_revision+1),
        m2_revision=accepted_revision,m3_revision=accepted_revision))
    return RoomPipelinePublication('e',m.map_domain_id,latest_revision,m,
        accepted_revision,regions,m5,stale or regions is None,False,
        accepted_map=accepted_map)


def test_publisher_keeps_rebuild_map_in_its_own_domain_and_source_age():
    publisher,hierarchy,metrics,*_=make_publisher()
    room=room_publication()
    sources=replace(metrics['sources'],room_pipeline=room)
    updated={**metrics,'source_age_ns':{**metrics['source_age_ns'],'room_map':50},'sources':sources}
    publisher.publish(hierarchy,updated)
    envelope=publisher.read_latest()
    assert envelope.sources.room_pipeline is room
    assert envelope.sources.room_pipeline.map_domain_id=='rebuild-m3:e'
    assert envelope.sources.nav.revision==envelope.hierarchy.map_revision


def test_publisher_rejects_cross_episode_room_map():
    publisher,hierarchy,metrics,*_=make_publisher()
    bad_map=replace(room_publication().latest_map,episode_id='other',
                    source=FrameKey('other','rgbd',2))
    bad=RoomPipelinePublication('other',bad_map.map_domain_id,1,bad_map,1,
        RegionSnapshot('other',1,1,'f',{},False),1,False,False,
        accepted_map=bad_map)
    sources=replace(metrics['sources'],room_pipeline=bad)
    updated={**metrics,'source_age_ns':{**metrics['source_age_ns'],'room_map':50},'sources':sources}
    with pytest.raises(ValueError,match='different episode'):
        publisher.publish(hierarchy,updated)


def test_ui_uses_separate_rebuild_tab_and_never_overlays_old_m5_on_new_m3(qapp):
    publisher,hierarchy,metrics,*_=make_publisher(with_images=False)
    room=room_publication(latest_revision=2,accepted_revision=1,stale=True)
    sources=replace(metrics['sources'],room_pipeline=room)
    updated={**metrics,'source_age_ns':{**metrics['source_age_ns'],'room_map':50},'sources':sources}
    publisher.publish(hierarchy,updated)
    window=DashboardWindow(publisher)
    try:
        assert window.map_tabs.tabText(0)=='Control map'
        assert window.map_tabs.tabText(1)=='Rebuild M3/M5'
        assert window.room_map_view._overlay_regions==()
        assert 'not overlaid' in window.room_map_view.status_text
        assert 'rebuild-m3:e' in window.room_map_view.status_text
        assert window.room_map_revision_combo.isEnabled()
        window.room_map_revision_combo.setCurrentIndex(1)
        assert window.room_map_view._display_map().revision==1
        assert window.room_map_view._overlay_regions
        window.room_map_revision_combo.setCurrentIndex(0)
        assert window.room_map_view._display_map().revision==2
        assert window.room_map_view._overlay_regions==()
    finally:
        window.close()


def test_final_export_writes_room_publication_separately_from_nav(tmp_path):
    import json
    from neusymnav.contracts import loads
    from neusymnav.runtime.launcher import _export

    room=room_publication()
    class Quota:
        def reserve(self,*args,**kwargs):pass
        def release(self,*args,**kwargs):pass
    class Pipeline:
        clock_domain='clock';quota=Quota();_launcher_worker_metadata={}
        def snapshot_bundle(self):return None,None
        def snapshot(self):return None
        def room_pipeline_snapshot(self):return room

    result=_export(tmp_path,Pipeline(),{'clean_shutdown':True,'actual_profile':'fixture'},
                   {'mode':'live','outcome':'completed'})
    path=tmp_path/'room-pipeline.json'
    restored=loads(path.read_text())
    assert isinstance(restored,RoomPipelinePublication)
    assert restored.map_domain_id=='rebuild-m3:e'
    assert result['room_pipeline_available']
    manifest=json.loads((tmp_path/'export-manifest.json').read_text())
    assert manifest['files']['room-pipeline.json']


def test_older_accepted_map_is_retained_for_stale_region_pair():
    publication=room_publication(latest_revision=2,accepted_revision=1,stale=True)
    assert publication.latest_map.revision==2
    assert publication.accepted_map.revision==1
    assert publication.regions.source_map_revision==publication.accepted_map.revision


@pytest.fixture(scope='module')
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
