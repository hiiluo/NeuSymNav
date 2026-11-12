from dataclasses import replace
from types import MappingProxyType
from types import SimpleNamespace
import threading,time
import pytest
from neusymnav.contracts.room_semantics import RoomLabelProposal
from test_room_context import ROOM_ID,query,candidate
from test_hydra_scene_graph_query import _taxonomy


def graph(category='toilet',rev=9,run=None):
    q=query([candidate('O(0)',category)]);g=q._projection
    md=dict(g.native_metadata)
    md['room_label_input']={'schema_version':1,'graph_revision':rev,'input_prefix_sha256':g.input_prefix_sha256,'semantic_labels':dict(q._semantic_labels),'snapshot_sha256':f'{rev:064x}'}
    return replace(g,graph_revision=rev,run_id=run or g.run_id,native_metadata=md)


def wait(pred,timeout=2):
    end=time.monotonic()+timeout
    while not pred():
        assert time.monotonic()<end,'timed out waiting for debug service'
        time.sleep(.01)


class FakeBackend:
    def __init__(self):self.entered=threading.Event();self.release=threading.Event();self.last_metrics={};self.calls=[];self.closed=False;self.cancels=0
    def infer(self,req):
        self.calls.append(req);self.entered.set();self.release.wait(2)
        return RoomLabelProposal(req.key.room_id,req.key.graph_revision,req.key.context_hash,'bathroom',(),('O(0)',),'proposed','toilet anchor','a'*64,'b'*64)
    def cancel(self):self.cancels+=1;self.release.set()
    def close(self,timeout_s=3):self.closed=True;self.release.set();return {'clean_shutdown':True}


@pytest.mark.parametrize('has_view', [False, True])
def test_visual_service_only_bypasses_empty_objects_with_admitted_room_view(has_view):
    from neusymnav.rooms.service import RoomLabelDebugService

    class VisualBackend(FakeBackend):
        def infer(self, request, *, views):
            self.calls.append(request)
            return RoomLabelProposal(request.key.room_id, request.key.graph_revision,
                request.key.context_hash, 'bathroom', (), (), 'proposed', None, 'a'*64, 'b'*64,
                tuple(view.view_id for view in views))

    def select(source, room_id):
        assert source is snapshot
        assert room_id == ROOM_ID
        if not has_view:
            return ()
        view_id = ('f' if source.graph_revision == 11 else 'e') * 64
        return (SimpleNamespace(view_id=view_id, manifest=lambda: {'view_id': view_id}),)

    snapshot = graph()
    metadata = dict(snapshot.native_metadata)
    metadata['room_label_input'] = {**metadata['room_label_input'], 'semantic_labels': {}}
    snapshot = replace(snapshot, native_metadata=metadata)
    backend = VisualBackend()
    service = RoomLabelDebugService(backend, _taxonomy(), debounce_s=0, room_view_selector=select)
    try:
        service.offer(snapshot)
        wait(lambda: any(row.state in {'complete', 'error'} for row in service.records()))
        record = service.records()[0]
        assert record.result is not None, record.error
        assert record.result.status == ('available' if has_view else 'insufficient_evidence')
        assert len(backend.calls) == int(has_view)
        assert record.result.supporting_view_ids == (('e'*64,) if has_view else ())
        if has_view:
            for revision in (10, 11):
                metadata = dict(snapshot.native_metadata)
                metadata['room_label_input'] = {**metadata['room_label_input'],
                    'graph_revision': revision, 'snapshot_sha256': f'{revision:064x}'}
                snapshot = replace(snapshot, graph_revision=revision, native_metadata=metadata)
                service.offer(snapshot)
                wait(lambda: any(row.state == 'complete' and row.job.request.key.graph_revision == revision
                                 for row in service.records()))
            assert [request.key.graph_revision for request in backend.calls] == [9, 11]
            assert service.records()[0].result.supporting_view_ids == ('f'*64,)
    finally:
        assert service.close(2)['clean_shutdown']


def test_vlm_label_survives_new_revisions_and_abstention_until_a_new_label():
    from neusymnav.rooms.label_overlay import current_room_labels
    from neusymnav.rooms.service import RoomLabelDebugService

    class VisualBackend(FakeBackend):
        def infer(self, request, *, views):
            self.calls.append(request)
            rev = request.key.graph_revision
            label = {9: 'bathroom', 10: 'unknown', 11: 'hallway'}[rev]
            known = label != 'unknown'
            return RoomLabelProposal(request.key.room_id, rev, request.key.context_hash,
                label, (), (), 'proposed' if known else 'unknown',
                'model result', 'a'*64, 'b'*64, (views[0].view_id,) if known else ())

    def select(source, room_id):
        view_id = f'{source.graph_revision:064x}'
        return (SimpleNamespace(view_id=view_id, manifest=lambda: {'view_id': view_id}),)

    service = RoomLabelDebugService(VisualBackend(), _taxonomy(), debounce_s=0,
                                    room_view_selector=select)
    try:
        for rev, label in ((9, 'bathroom'), (10, 'bathroom'), (11, 'hallway')):
            source = graph(rev=rev)
            service.offer(source)
            if rev == 10:
                assert current_room_labels((), source, backend='vlm',
                    retained=service.retained_vlm_labels(source)) == {ROOM_ID: 'VLM bathroom'}
            wait(lambda: any(r.state == 'complete' and r.job.request.key.graph_revision == rev
                             for r in service.records()))
            assert current_room_labels(service.records(), source, backend='vlm',
                retained=service.retained_vlm_labels(source)) == {ROOM_ID: f'VLM {label}'}
        new_run = graph(rev=12, run='new-run')
        assert service.retained_vlm_labels(new_run) == {}
        same_scope_without_room = replace(source, graph_revision=12, nodes=())
        service.offer(same_scope_without_room)
        assert service.retained_vlm_labels(source) == {}
    finally:
        assert service.close(2)['clean_shutdown']


def test_source_builder_requires_exact_explicit_semantics_not_node_name():
    from neusymnav.rooms.debug_context import build_debug_jobs
    jobs=build_debug_jobs(graph(),_taxonomy(),100)
    assert len(jobs)==1 and jobs[0].request.context.objects[0].category=='toilet'
    assert jobs[0].request.key.geometry_hash==graph().native_metadata['room_label_input']['snapshot_sha256']
    legacy=query([candidate('O(0)','toilet')])._projection
    missing=replace(legacy,native_metadata={k:v for k,v in legacy.native_metadata.items() if k!='room_label_input'})
    with pytest.raises(ValueError):build_debug_jobs(missing,_taxonomy(),100)
    empty=build_debug_jobs(legacy,_taxonomy(),100)
    assert not empty[0].request.context.objects # names must not substitute absent semantic IDs
    broken=graph();m=dict(broken.native_metadata);m['room_label_input']={**m['room_label_input'],'graph_revision':8}
    with pytest.raises(ValueError):build_debug_jobs(replace(broken,native_metadata=m),_taxonomy(),100)


def test_offer_nonblocking_and_old_result_stays_pinned_history():
    from neusymnav.rooms.service import RoomLabelDebugService
    from neusymnav.rooms.debug_types import record_is_current
    b=FakeBackend();svc=RoomLabelDebugService(b,_taxonomy(),debounce_s=0)
    try:
        t=time.monotonic();svc.offer(graph());assert time.monotonic()-t<.1
        assert b.entered.wait(1)
        svc.offer(graph(rev=10));b.release.set()
        wait(lambda:any(r.state=='complete' and r.job.request.key.graph_revision==9 for r in svc.records()))
        old=next(r for r in svc.records() if r.state=='complete' and r.job.request.key.graph_revision==9)
        assert old.result.geometry_revision==9
        assert not record_is_current(old,svc.current_graph)
        wait(lambda:any(r.state=='complete' and r.job.request.key.graph_revision==10 for r in svc.records()))
        assert all(r.job.request.key.graph_revision in(9,10) for r in svc.records())
    finally:assert svc.close(2)['clean_shutdown']
    assert b.closed


def test_episode_reset_cancels_old_work_and_shutdown_does_not_wait_model_deadline():
    from neusymnav.rooms.service import RoomLabelDebugService
    b=FakeBackend();svc=RoomLabelDebugService(b,_taxonomy(),debounce_s=0)
    svc.offer(graph());assert b.entered.wait(1)
    svc.offer(None)
    wait(lambda:b.cancels>0)
    assert svc.current_graph is None
    assert not any(r.state=='complete' for r in svc.records())
    t=time.monotonic();report=svc.close(1);assert time.monotonic()-t<1.2 and report['clean_shutdown']
    assert not svc.offer(graph())


def test_graph_only_evidence_is_not_claimed_verified():
    from neusymnav.rooms.debug_context import build_debug_jobs
    from neusymnav.rooms.evidence_quality import assess_evidence_quality
    job=build_debug_jobs(graph(),_taxonomy(),100)[0]
    quality=assess_evidence_quality(job.request.context)
    assert quality['verified'] is False
    assert quality['tier']=='graph_only'
    assert 'object_image_links_missing' in quality['flags']


def test_stale_replay_and_epoch_changes_are_observed_even_with_same_source_digest():
    from neusymnav.rooms.service import RoomLabelDebugService
    from neusymnav.rooms.debug_types import record_is_current
    b=FakeBackend();b.release.set();svc=RoomLabelDebugService(b,_taxonomy(),debounce_s=0)
    g=graph()
    try:
        svc.offer(g);wait(lambda:any(r.state=='complete' for r in svc.records()))
        record=next(r for r in svc.records() if r.state=='complete')
        assert record_is_current(record,svc.current_graph)
        assert svc.offer(replace(g,stale=True))
        assert not record_is_current(record,svc.current_graph)
        assert svc.offer(replace(g,replay_required=True))
        assert not record_is_current(record,svc.current_graph)
        md={**g.native_metadata,'graph_world_epoch':'epoch-1'}
        assert svc.offer(replace(g,native_metadata=md))
        assert svc.status()['world_epoch']=='epoch-1'
        assert not record_is_current(record,svc.current_graph)
    finally:assert svc.close(2)['clean_shutdown']


@pytest.mark.parametrize('timeout',[float('nan'),float('inf'),True,0,-1])
def test_shutdown_rejects_nonfinite_or_invalid_budget(timeout):
    from neusymnav.rooms.service import RoomLabelDebugService
    svc=RoomLabelDebugService(FakeBackend(),_taxonomy())
    try:
        with pytest.raises(ValueError):svc.close(timeout)
    finally:svc.close(2)


def test_offer_invalidates_queued_source_before_manager_can_dispatch_it():
    from neusymnav.rooms.service import RoomLabelDebugService
    from neusymnav.rooms.debug_context import build_debug_jobs
    b=FakeBackend();svc=RoomLabelDebugService(b,_taxonomy(),debounce_s=0)
    try:
        g=graph();svc.offer(g);assert b.entered.wait(1)
        # Hold manager lock to model an old pending job at the exact offer boundary.
        with svc._cv:
            old=build_debug_jobs(graph(rev=10),_taxonomy(),time.monotonic_ns())[0]
            svc._pending[old.request.key.room_id]=old
            assert svc.offer(graph(rev=11))
            assert not svc._pending
        b.release.set()
        wait(lambda:any(r.state=='complete' and r.job.request.key.graph_revision==11 for r in svc.records()))
        # rev 10 was invalidated before dispatch; rev 11 has the same room rows
        # as rev 9, so it reuses that model answer instead of a second call.
        assert [q.key.graph_revision for q in b.calls]==[9]
        reused=next(r for r in svc.records() if r.state=='complete' and r.job.request.key.graph_revision==11)
        assert reused.backend_metrics['semantic_cache']=='hit' and reused.backend_metrics['reused_from_revision']==9
    finally:assert svc.close(2)['clean_shutdown']


def test_generic_only_context_abstains_without_loading_model():
    from neusymnav.rooms.service import RoomLabelDebugService
    from neusymnav.backends.hydra.labels import HydraLabelRasterizer
    taxonomy=replace(_taxonomy(),categories=(*_taxonomy().categories,'mirror'))
    raster=HydraLabelRasterizer(taxonomy);g=graph();source=dict(g.last_source);source['labelspace_hash']=raster.labelspace_hash
    md=dict(g.native_metadata);md['room_label_input']={**md['room_label_input'],'semantic_labels':{'O(0)':raster.class_to_label['mirror']}}
    g=replace(g,last_source=source,native_metadata=md)
    b=FakeBackend();svc=RoomLabelDebugService(b,taxonomy,debounce_s=0)
    try:
        svc.offer(g)
        wait(lambda:any(r.state=='complete' for r in svc.records()))
        record=next(r for r in svc.records() if r.state=='complete')
        assert not b.calls
        assert record.result.status=='insufficient_evidence'
        assert record.result.reason=='non_discriminating_object_context'
        assert record.evidence_quality['only_generic_objects']
        assert record.result.supporting_object_ids==()
    finally:assert svc.close(2)['clean_shutdown']


def test_snapshot_metadata_is_detached_from_mutable_source_maps():
    from neusymnav.rooms.debug_context import build_debug_jobs
    g=graph();md=dict(g.native_metadata);md['custom_source']={'nested':['original']}
    job=build_debug_jobs(replace(g,native_metadata=md),_taxonomy(),100)[0]
    md['custom_source']['nested'].append('later mutation')
    assert job.graph.native_metadata['custom_source']['nested']==('original',)
    with pytest.raises(TypeError):job.graph.native_metadata['custom_source']['nested']='replacement'


def test_brief_stale_recovery_rebuilds_pending_rooms_without_new_revision():
    from neusymnav.rooms.service import RoomLabelDebugService
    g=graph();nodes={n.layer_id:n for n in g.nodes}
    names={2:'O(1)',3:'p(1)',4:'R(1)'}
    ids={layer:f'hydra:{g.run_id}:{layer}:{name}' for layer,name in names.items()}
    extra=tuple(replace(nodes[layer],native_id=names[layer],node_id=ids[layer],parent_id=ids.get(layer+1,nodes[layer].parent_id)) for layer in (2,3,4))
    md=dict(g.native_metadata);md['room_label_input']={**md['room_label_input'],'semantic_labels':{**md['room_label_input']['semantic_labels'],'O(1)':md['room_label_input']['semantic_labels']['O(0)']}}
    g=replace(g,nodes=(*g.nodes,*extra),node_counts={**g.node_counts,'2':2,'3':2,'4':2},native_metadata=md)
    b=FakeBackend();svc=RoomLabelDebugService(b,_taxonomy(),debounce_s=0)
    try:
        svc.offer(g);assert b.entered.wait(1)
        with svc._cv:
            # Both transitions occur while manager cannot consume either offer.
            svc.offer(replace(g,stale=True));svc.offer(g)
        b.release.set()
        wait(lambda:len(b.calls)==2)
        assert b.calls[1].key.room_id.endswith('R(1)')
    finally:assert svc.close(2)['clean_shutdown']
