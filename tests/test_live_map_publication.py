"""The current occupancy display advances without graph/model progress."""
from dataclasses import replace
import json
import threading
import time

import pytest

from neusymnav.contracts import FrameKey
from neusymnav.runtime.ui_transport import decode_publication, encode_publication
from neusymnav.visualization.publisher import DisplayPublisher
from neusymnav.visualization.robot_overlay import RobotSample, RobotTrack
from test_display_snapshot import make_publisher
from test_ui_publication_cadence import ui_process


def wait_envelope(ui, predicate=lambda e: True):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        path=ui.root/'publication.json'
        if path.exists():
            result=decode_publication(path.read_bytes())
            if predicate(result):return result
        time.sleep(.01)
    raise AssertionError('display worker did not publish expected value')


def live(nav, revision=2):
    return replace(nav,revision=revision,source=FrameKey(nav.episode_id,nav.source.sensor_id,revision),
                   capture_monotonic_ns=nav.capture_monotonic_ns+revision)


def test_map_advances_while_graph_bundle_and_model_are_stalled(tmp_path):
    _,hierarchy,metrics,*_=make_publisher()
    old=metrics['sources'].nav;pointer=[live(old)]
    with ui_process(tmp_path,publish_hz=5,live_nav_provider=lambda:pointer[0]) as ui:
        ui.publish(hierarchy,metrics)
        first=wait_envelope(ui,lambda e:e.sources.live_nav.revision==2)
        pointer[0]=live(old,3)
        current=wait_envelope(ui,lambda e:e.sources.live_nav.revision==3)
        assert current.hierarchy.revision==first.hierarchy.revision
        assert current.sources.nav.revision==hierarchy.map_revision
        assert current.sources.live_nav.source==pointer[0].source
        assert 'live_map' in current.metrics.source_age_ns
        assert current.publication_sequence>first.publication_sequence


def test_current_map_before_first_graph_has_no_invented_entities(tmp_path):
    _,hierarchy,metrics,*_=make_publisher();nav=live(metrics['sources'].nav)
    with ui_process(tmp_path,live_nav_provider=lambda:nav) as ui:
        initial=wait_envelope(ui)
        assert not initial.hierarchy.nodes and not initial.hierarchy.edges
        assert initial.hierarchy.statuses['display']=='awaiting_canonical_hierarchy'
        assert initial.sources.nav is None and initial.sources.live_nav.source==nav.source
        ui.publish(hierarchy,metrics)
        canonical=wait_envelope(ui,lambda e:e.hierarchy.revision==hierarchy.revision)
        assert canonical.hierarchy.revision>initial.hierarchy.revision
        assert canonical.sources.nav.revision==hierarchy.map_revision


def live_metrics(metrics,nav):
    return dict(metrics,source_age_ns=dict(metrics['source_age_ns'],live_map=10),
                sources=replace(metrics['sources'],live_nav=nav,robot=None))


def test_live_map_wire_legacy_optional_field_and_exact_robot_binding():
    _,h,m,*_=make_publisher();nav=live(m['sources'].nav)
    p=DisplayPublisher(clock_domain='clock',now_ns=lambda:1000)
    m=live_metrics(m,nav)
    sample=RobotSample(nav.source,nav.capture_monotonic_ns,nav.clock_domain,0,(1.,2.),0.)
    m['sources']=replace(m['sources'],robot=RobotTrack((sample,)))
    p.publish(h,m);packet=encode_publication(p.read_latest())
    assert decode_publication(packet).sources.live_nav.source==nav.source
    bad=replace(sample,capture_monotonic_ns=sample.capture_monotonic_ns-1)
    with pytest.raises(ValueError,match='robot'):p.publish(h,dict(m,sources=replace(m['sources'],robot=RobotTrack((bad,)))))
    original=make_publisher()[0].read_latest();wire=json.loads(encode_publication(original))
    del wire['payload']['fields']['sources']['fields']['live_nav']
    assert decode_publication(json.dumps(wire).encode()).sources.live_nav is None


@pytest.mark.parametrize('field,value', [('clock_domain','other'),('calibration_hash','b'*64),
    ('robot_geometry_id','other'),('floor_z_m',99.),('floor_datum_source','other'),('resolution_m',2.)])
def test_live_map_rejects_cross_domain_or_geometry(field,value):
    _,h,m,*_=make_publisher();nav=replace(live(m['sources'].nav),**{field:value})
    p=DisplayPublisher(clock_domain='clock',now_ns=lambda:1000)
    with pytest.raises(ValueError):p.publish(h,live_metrics(m,nav))


def test_live_map_rejects_future_backward_revision_time_and_source_change():
    _,h,m,*_=make_publisher();nav=live(m['sources'].nav,3)
    p=DisplayPublisher(clock_domain='clock',now_ns=lambda:1000);p.publish(h,live_metrics(m,nav))
    for bad in (replace(nav,capture_monotonic_ns=1001),live(nav,2),
                replace(nav,revision=4,capture_monotonic_ns=nav.capture_monotonic_ns-1),
                replace(nav,source=FrameKey('e',nav.source.sensor_id,50))):
        with pytest.raises(ValueError):p.publish(h,live_metrics(m,bad))
    assert p.read_latest().sources.live_nav.revision==3


def test_publication_handoff_does_not_wait_for_images_and_shutdown_is_bounded(tmp_path,monkeypatch):
    _,h,m,*_=make_publisher();entered=threading.Event();release=threading.Event()
    with ui_process(tmp_path,publish_hz=5) as ui:
        caller=threading.get_ident()
        def stalled(_):
            assert threading.get_ident()!=caller
            entered.set();release.wait(3);return ()
        monkeypatch.setattr(ui,'_images',stalled)
        start=time.monotonic();ui.publish(h,m)
        assert time.monotonic()-start<.1
        assert entered.wait(1)
        for i in range(20):ui.publish(h,dict(m,actual_profile=str(i)))
        assert ui.status['coalesced_publications']>=19
        report=ui.close(.05)
        assert report['publication_thread_pending'] and not report['clean_shutdown']
        release.set()


def test_real_pipeline_mapper_and_robot_display_advance_during_blocked_inference(tmp_path):
    """Production mapper pointer path continues before the first object commit."""
    import sys
    from neusymnav.runtime.ui_transport import UiProcess
    from test_runtime_scheduling import pipeline,source,nav_for,Detector,DOMAIN,wait_for
    entered=threading.Event();release=threading.Event()
    class Slow(Detector):
        def infer(self,obs):entered.set();release.wait(5);return super().infer(obs)
    class Mapper:
        def update(self,obs):return nav_for(obs,obs.key.frame_index+1)
    p,_,_=pipeline(tmp_path/'run',detector=Slow(),mapper=Mapper(),clock=time.monotonic_ns)
    script=tmp_path/'idle.py';script.write_text('import time\ntime.sleep(30)\n')
    ui=UiProcess(tmp_path/'ipc',python=sys.executable,script=script,clock_domain=DOMAIN,
        command_handler=p.handle_ui_command,live_nav_provider=p.live_navigation_display,publish_hz=5)
    p.publisher=ui
    try:
        frozen_revision=None
        for i in range(3):
            depth=source(i,stamp=time.monotonic_ns(),modality='depth_only')
            pose=dict(source=depth.key,capture_monotonic_ns=depth.capture_monotonic_ns,
                clock_domain=DOMAIN,pose_version=depth.pose_version,robot_xy=(float(i),0.),yaw_rad=0.)
            ui.observe_robot(None,depth,pose)
            if i==0:
                p.submit_sensor_pair(source(stamp=depth.capture_monotonic_ns),depth,pose)
                assert entered.wait(1)
            else:p.submit_navigation(depth,pose)
            wait_for(lambda:p.live_navigation_display() is not None and p.live_navigation_display().source==depth.key)
            current=wait_envelope(ui,lambda e:e.sources.live_nav is not None and e.sources.live_nav.source==depth.key)
            assert current.sources.robot.samples[-1].source==depth.key
            assert current.sources.robot.samples[-1].xy==(float(i),0.)
            if frozen_revision is None:frozen_revision=current.hierarchy.revision
            assert current.hierarchy.revision==frozen_revision
            assert current.hierarchy.object_revision==0 and p.telemetry()['committed']==0
        release.set();wait_for(lambda:p.snapshot() is not None and p.snapshot().object_revision>0)
        canonical=wait_envelope(ui,lambda e:e.hierarchy.object_revision>0)
        assert canonical.sources.nav.revision==canonical.hierarchy.map_revision
        assert canonical.sources.live_nav.revision>=canonical.sources.nav.revision
    finally:
        release.set();assert p.close(2)['clean_shutdown'];assert ui.close(2)['clean_shutdown']


def test_provider_exception_and_backward_candidate_keep_old_map_aging(tmp_path,monkeypatch):
    from test_ui_publication_cadence import fixed_clock
    now=fixed_clock(monkeypatch)
    _,h,m,*_=make_publisher();original=live(m['sources'].nav,3);pointer=[original]
    def provider():
        if isinstance(pointer[0],Exception):raise pointer[0]
        return pointer[0]
    with ui_process(tmp_path,live_nav_provider=provider) as ui:
        ui.publish(h,m);first=wait_envelope(ui)
        pointer[0]=RuntimeError('fixture provider stopped')
        now[0]+=200_000_000
        stale=wait_envelope(ui,lambda e:e.publication_sequence>first.publication_sequence)
        assert stale.sources.live_nav.source==original.source
        assert stale.metrics.source_age_ns['live_map']==first.metrics.source_age_ns['live_map']+200_000_000
        assert 'fixture provider stopped' in ui.status['live_nav_error']
        assert ui.status['failed'] is None
        pointer[0]=live(m['sources'].nav,2)
        now[0]+=200_000_000
        rejected=wait_envelope(ui,lambda e:e.publication_sequence>stale.publication_sequence)
        assert rejected.sources.live_nav.revision==3
        assert 'backward' in ui.status['live_nav_error']


def test_live_map_rejects_wrong_episode_even_before_graph_and_geometry_extent_can_move(tmp_path):
    _,h,m,*_=make_publisher();nav=live(m['sources'].nav)
    wrong=replace(nav,episode_id='wrong',source=FrameKey('wrong',nav.source.sensor_id,2))
    p=DisplayPublisher(clock_domain='clock',now_ns=lambda:1000)
    with pytest.raises(ValueError):p.publish(h,live_metrics(m,wrong))
    moving=replace(nav,origin_xy=(10.,20.))
    p.publish(h,live_metrics(m,moving))
    assert p.read_latest().sources.live_nav.origin_xy==(10.,20.)


def test_omitted_live_map_does_not_reset_stream_and_endpoint_rejects_replay(tmp_path):
    from neusymnav.runtime.ui_transport import UiEndpoint
    from neusymnav.recording.replay import _write_atomic
    _,h,m,*_=make_publisher();nav=live(m['sources'].nav,3)
    p=DisplayPublisher(clock_domain='clock',now_ns=lambda:1000)
    p.publish(h,live_metrics(m,nav));current=p.read_latest()
    p.publish(h,m)
    with pytest.raises(ValueError):p.publish(h,live_metrics(m,live(m['sources'].nav,2)))
    endpoint=UiEndpoint(tmp_path,clock_domain='clock')
    _write_atomic(tmp_path/'publication.json',encode_publication(p.read_latest()))
    assert endpoint.read_latest().publication_sequence==p.read_latest().publication_sequence
    _write_atomic(tmp_path/'publication.json',encode_publication(current))
    assert endpoint.read_latest().publication_sequence==p.read_latest().publication_sequence
