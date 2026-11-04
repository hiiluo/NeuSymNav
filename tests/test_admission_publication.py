from dataclasses import replace
import pytest
from test_membership import objects, regions, OID, ALIAS
from test_regions import nav
from neusymnav.contracts.admission import AdmissionDecision, AdmissionSnapshot
from neusymnav.hierarchy.composer import publication_objects
from neusymnav.hierarchy import HierarchyComposer


def admission(state, *, revision=1, availability='available'):
    decision = AdmissionDecision(OID, state, availability, (), (), {})
    return AdmissionSnapshot('e', revision, revision, 'object-admission:v1', 'a'*64, {OID: decision})


def test_enforce_filters_objects_aliases_and_edges_without_mutating_owner():
    owner = objects()
    selected = publication_objects(owner, admission('candidate'), 'enforce')
    assert not selected.objects and not selected.aliases
    assert OID in owner.objects and ALIAS in owner.aliases
    graph = HierarchyComposer().compose(selected, nav(), regions(), latest_nav_revision=1, now_ns=200, clock_domain='clock')
    assert OID not in graph.nodes
    assert all(OID not in (edge.source_id, edge.target_id) for edge in graph.edges)


def test_shadow_preserves_original_and_enforce_preserves_admitted_identity():
    owner = objects()
    assert publication_objects(owner, admission('candidate'), 'shadow') is owner
    selected = publication_objects(owner, admission('admitted'), 'enforce')
    assert selected.objects[OID] == owner.objects[OID]
    assert selected.resolve_id(ALIAS) == OID
    graph = HierarchyComposer().compose(selected, nav(), regions(), latest_nav_revision=1, now_ns=200, clock_domain='clock')
    assert tuple(graph.nodes[OID].attributes['centroid']) == tuple(owner.objects[OID].centroid)
    assert any(e.source_id == OID and e.kind == 'in_region' for e in graph.edges)


def test_enforce_rejects_mismatched_or_unavailable_admission():
    owner = objects()
    with pytest.raises(ValueError): publication_objects(owner, admission('admitted', revision=2), 'enforce')
    with pytest.raises(ValueError): publication_objects(owner, admission('admitted', availability='unavailable'), 'enforce')
    with pytest.raises(ValueError): publication_objects(owner, replace(admission('admitted'), decisions={}), 'enforce')


def test_enforce_retains_last_coherent_bundle_on_missing_admission():
    from test_canonical_publication_cadence import fixture
    p, _, _ = fixture()
    p._admission_mode = 'off'
    p._publish()
    old = p.snapshot_bundle()
    p._admission_mode = 'enforce'
    p._objects = replace(p._objects, revision=2)
    p._publish()
    assert p.snapshot_bundle() == old
    assert p.object_admission_status()['status'] == 'unavailable'


def test_config_modes_are_explicit_and_legacy_is_off(tmp_path):
    from test_long_demo_configuration import profile
    from neusymnav.runtime.configuration import load_config
    assert load_config(profile(tmp_path)).data.get('admission', {}).get('mode', 'off') == 'off'
    assert load_config(profile(tmp_path, admission={'mode':'shadow'})).data['admission']['mode'] == 'shadow'
    with pytest.raises(ValueError): load_config(profile(tmp_path, admission={'mode':'bad'}))


def test_export_projection_never_exposes_candidates_or_their_events():
    from neusymnav.runtime.launcher import _admission_export_projection
    owner = objects()
    graph = HierarchyComposer().compose(publication_objects(owner, admission('candidate'), 'enforce'), nav(), regions(), latest_nav_revision=1, now_ns=200, clock_domain='clock')
    selected, events = _admission_export_projection(owner, graph, [{'object_id':OID}])
    assert not selected.objects and not selected.aliases and not events
    assert OID in owner.objects
    selected, events = _admission_export_projection(owner, None, [{'object_id':OID}])
    assert selected is None and not events


def test_runtime_shadow_keeps_graph_and_enforce_filters_shared_display(monkeypatch):
    from types import SimpleNamespace
    from test_canonical_publication_cadence import fixture
    import neusymnav.objects.admission as engine
    from neusymnav.contracts.serialization import dumps
    base, _, _ = fixture()
    base._objects=objects();base._latest_nav=nav();base.clock_domain='clock';base.now_ns=lambda:200
    base._publish(); baseline=dumps(base.snapshot())
    p, _, _ = fixture()
    p._objects=objects();p._latest_nav=nav();p.clock_domain='clock';p.now_ns=lambda:200
    p._admission_owner=object();p._admission_mode='shadow'
    class Journal:
        def __init__(self, owner, policy): pass
        def evaluate(self, verifier): return admission('candidate')
    monkeypatch.setattr(engine, 'AdmissionJournal', Journal)
    p._admission_journal=Journal(None,None)
    p._publish(object())
    assert dumps(p.snapshot()) == baseline
    assert p.object_admission_status()['counts']['candidate'] == 1
    assert p.object_admission_status()['decisions'][OID]['state'] == 'candidate'
    p._admission_mode='enforce';p._closing=True;p._publish(object())
    assert OID not in p.snapshot().nodes
    assert all(OID not in (edge.source_id,edge.target_id) for edge in p.snapshot().edges)


def test_qt_candidate_table_displays_diagnostics_without_graph_nodes():
    from PyQt5 import QtWidgets
    from neusymnav.visualization.publisher import DisplaySources
    from neusymnav.visualization.desktop import DashboardWindow
    from neusymnav.runtime.ui_transport import encode_publication, decode_publication
    from test_display_snapshot import make_publisher
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher, hierarchy, metrics, source_objects, source_nav, _ = make_publisher(with_images=False)
    d=AdmissionDecision('diagnostic-candidate','candidate','available',('label_uncertain',),(),{'independent_views':2,'depth_fraction_min':0.75})
    snap=AdmissionSnapshot(hierarchy.episode_id,hierarchy.object_revision,1,'object-admission:v1','a'*64,{d.object_id:d})
    publisher.publish(hierarchy,{**metrics,'sources':DisplaySources(objects=source_objects,nav=source_nav,admission=snap)})
    packet=decode_publication(encode_publication(publisher.read_latest()))
    assert packet.sources.admission.decisions[d.object_id].state=='candidate'
    window=DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:200)
    try:
        window.refresh();app.processEvents()
        assert window.admission_table.rowCount()==1
        row=[window.admission_table.item(0,i).text() for i in range(window.admission_table.columnCount())]
        assert row==['diagnostic-candidate','candidate','label_uncertain','2','0.75']
        assert 'diagnostic-candidate' not in hierarchy.nodes
    finally:window.close();app.processEvents()


def test_runtime_rejects_stale_evidence_revision(monkeypatch):
    from test_canonical_publication_cadence import fixture
    import neusymnav.objects.admission as engine
    p,_,_=fixture();p._publish();old=p.snapshot_bundle()
    p._objects=replace(p._objects,revision=2);p._admission_mode='enforce';p._admission_owner=object()
    class Journal:
        def __init__(self, owner, policy): pass
        def evaluate(self, verifier):
            return AdmissionSnapshot('episode',2,1,'object-admission:v1','a'*64,{})
    monkeypatch.setattr(engine,'AdmissionJournal',Journal)
    p._admission_journal=Journal(None,None)
    p._publish(object())
    assert p.snapshot_bundle()==old
    assert p.object_admission_status()['status']=='unavailable'


def test_journal_opens_before_any_observation_without_waiting_for_map(tmp_path, monkeypatch):
    import neusymnav.objects.admission as engine
    from test_runtime_scheduling import pipeline, source, wait_for
    seen=[]
    class Journal:
        def __init__(self, owner, policy): seen.append(('open',owner.snapshot().revision))
        def evaluate(self, verifier): raise AssertionError('no map means no publication')
    monkeypatch.setattr(engine,'AdmissionJournal',Journal)
    p,_,_=pipeline(tmp_path,admission_mode='shadow')
    try:
        assert seen == [('open',0)]
        p.submit(source());wait_for(lambda:p.telemetry()['committed']==1)
        assert seen == [('open',0)]
    finally:p.close(2)


def test_qt_reports_stale_admission_without_new_graph():
    from PyQt5 import QtWidgets
    from neusymnav.visualization.publisher import DisplaySources
    from neusymnav.visualization.desktop import DashboardWindow
    from test_display_snapshot import make_publisher
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    publisher,hierarchy,metrics,objs,n,_=make_publisher(with_images=False)
    publisher.publish(hierarchy,{**metrics,'sources':DisplaySources(objects=objs,nav=n,admission_status={'mode':'enforce','status':'unavailable','reason':'revision mismatch','stale':True})})
    from neusymnav.runtime.ui_transport import encode_publication, decode_publication
    assert decode_publication(encode_publication(publisher.read_latest())).sources.admission_status['stale'] is True
    window=DashboardWindow(publisher,clock_domain='clock',now_ns=lambda:200)
    try:
        window.refresh();app.processEvents()
        assert 'STALE' in window.admission_status_label.text()
        assert 'revision mismatch' in window.admission_status_label.text()
    finally:window.close();app.processEvents()


def test_unavailable_enforce_notifies_display_without_new_graph():
    from test_canonical_publication_cadence import fixture
    p,_,_=fixture();p._publish();old=p.snapshot_bundle()
    statuses=[]
    class Publisher:
        def set_admission_status(self,status):statuses.append(status)
        def publish(self,*args):raise AssertionError('stale graph must not be republished as fresh')
    p.publisher=Publisher();p._admission_mode='enforce';p._objects=replace(p._objects,revision=2)
    p._publish()
    assert p.snapshot_bundle()==old
    assert statuses[-1]['status']=='unavailable' and statuses[-1]['stale'] is True


def test_public_hierarchy_export_only_floor_room_object_and_valid_edges():
    from neusymnav.hierarchy.composer import public_hierarchy
    internal=HierarchyComposer().compose(objects(),nav(),regions(),latest_nav_revision=1,now_ns=200,clock_domain='clock')
    public=public_hierarchy(internal)
    assert {node.kind for node in public.nodes.values()} == {'floor','room','object'}
    assert OID in public.nodes and public.nodes[OID] == internal.nodes[OID]
    assert any(e.kind=='in_region' and e.source_id==OID for e in public.edges)
    assert any(e.kind=='region_adjacent_to' for e in public.edges)
    assert all(e.source_id in public.nodes and e.target_id in public.nodes for e in public.edges)
    assert (public.object_revision,public.map_revision,public.region_revision)==(1,1,1)


def test_actual_export_is_public_and_serialized_room_roundtrips(tmp_path):
    from neusymnav.contracts.serialization import loads, dumps
    from neusymnav.runtime.launcher import _export
    from test_export_canonical_bundle import captured_pipeline
    p, report, _ = captured_pipeline(tmp_path)
    result=_export(tmp_path,p,report,dict(outcome='completed',mode='live'))
    graph=loads((tmp_path/'hierarchy.json').read_text())
    assert result['hierarchy_available']
    assert {n.kind for n in graph.nodes.values()} <= {'floor','room','object'}
    assert loads(dumps(graph)) == graph
    assert any(n.kind=='building' for n in p.snapshot().nodes.values())


def test_public_hierarchy_does_not_export_stale_room_adjacency():
    from neusymnav.hierarchy.composer import public_hierarchy
    internal=HierarchyComposer().compose(objects(),nav(),regions(True),latest_nav_revision=1,now_ns=200,clock_domain='clock')
    public=public_hierarchy(internal)
    assert not any(edge.kind in {'region_adjacent_to','in_region'} for edge in public.edges)
    assert OID in public.nodes
