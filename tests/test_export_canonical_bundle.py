"""Canonical exports must not depend on a best-effort display publication."""
from dataclasses import replace

import pytest

from neusymnav.contracts.serialization import loads
from neusymnav.runtime.launcher import _export
from neusymnav.visualization.publisher import DisplayPublisher
from test_runtime_scheduling import pipeline,source,nav_for,wait_for,DOMAIN


class DroppingUi:
    def __init__(self):
        self.publisher=DisplayPublisher(clock_domain=DOMAIN,now_ns=lambda:1_000_000_000)
    def publish(self,hierarchy,metrics):
        if hierarchy.map_revision==1:self.publisher.publish(hierarchy,metrics)


def captured_pipeline(root):
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    ui=DroppingUi();p,_,_=pipeline(root,mapper=Mapper(),publisher=ui)
    try:
        p.submit(source())
        wait_for(lambda:p.telemetry()['committed']==1 and ui.publisher.read_latest() is not None)
        p.submit(source(1))
        wait_for(lambda:p.telemetry()['committed']==2 and p.snapshot() is not None and p.snapshot().object_revision==2 and p.snapshot().map_revision==2)
    finally:report=p.close(2)
    assert report['clean_shutdown']
    assert ui.publisher.read_latest().sources.nav.revision==1
    return p,report,ui


def test_real_pipeline_export_uses_atomic_canonical_bundle_when_display_coalesces(tmp_path):
    p,report,ui=captured_pipeline(tmp_path)
    # The display is not even consulted once canonical publication is available.
    ui.publisher.read_latest=lambda:pytest.fail('export consulted stale display')
    result=_export(tmp_path,p,report,dict(outcome='completed',mode='live'))
    assert result['outcome']=='completed' and result['export_issue'] is None
    hierarchy=loads((tmp_path/'hierarchy.json').read_text());nav=loads((tmp_path/'nav.json').read_text())
    objects=loads((tmp_path/'objects.json').read_text())
    assert hierarchy.map_revision==nav.revision==2
    assert hierarchy.object_revision==objects.revision==2
    assert nav.source==source(1).key and nav.clock_domain==DOMAIN
    bundle=p.snapshot_bundle()
    assert bundle[0] is p.snapshot() and bundle[0].map_revision==bundle[1].revision


def test_canonical_bundle_keeps_pinned_map_when_latest_navigation_advances(tmp_path):
    p,report,ui=captured_pipeline(tmp_path)
    old=p.snapshot()
    with p._lock:p._latest_nav=nav_for(source(2),3)
    hierarchy,nav=p.snapshot_bundle()
    assert hierarchy is old and hierarchy.map_revision==nav.revision==2
    assert p._latest_nav.revision==3
    result=_export(tmp_path,p,report,dict(outcome='completed',mode='live'))
    assert result['outcome']=='completed'
    assert loads((tmp_path/'nav.json').read_text()).revision==2


@pytest.mark.parametrize('mutation',[
    lambda hierarchy,nav:(replace(hierarchy,object_revision=1,edges=tuple(replace(edge,object_revision=1) for edge in hierarchy.edges)),nav),
    lambda hierarchy,nav:(hierarchy,replace(nav,clock_domain='host_monotonic:wrong')),
    lambda hierarchy,nav:(hierarchy,replace(nav,revision=1)),
    lambda hierarchy,nav:(hierarchy,None),
    lambda hierarchy,nav:(None,None),
])
def test_canonical_export_rejects_mismatch_without_falling_back_to_ui(tmp_path,mutation):
    p,report,ui=captured_pipeline(tmp_path)
    p.snapshot_bundle=lambda:mutation(p.snapshot(),nav_for(source(1),2))
    ui.publisher.read_latest=lambda:pytest.fail('invalid canonical bundle fell back to display')
    result=_export(tmp_path,p,report,dict(outcome='completed',mode='live'))
    assert result['outcome']=='incomplete' and not result['hierarchy_available']
    assert 'mismatch' in result['export_issue'] or 'unavailable' in result['export_issue']
    assert not (tmp_path/'hierarchy.json').exists() and not (tmp_path/'nav.json').exists()
