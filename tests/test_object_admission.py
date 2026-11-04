from dataclasses import replace
from types import SimpleNamespace
import pytest
from neusymnav.contracts import FrameKey
from neusymnav.objects.admission import AdmissionPolicy, AdmissionView, AdmissionEvidenceSummary, evaluate_admission
import numpy as np


def fixture(views, *, prior=None, neg=0, complete=True, revision=5):
    obj = SimpleNamespace(bounds=np.array([[0.,0.,0.],[1.,1.,1.]]))
    objects = SimpleNamespace(episode_id='ep', revision=revision, objects={'id':obj}, aliases={}, resolve_id=lambda x: x if x == 'id' else (_ for _ in ()).throw(KeyError(x)))
    verification = SimpleNamespace(episode_id='ep', object_revision=revision, replay_required=False, objects={'id': SimpleNamespace(negative_views=neg)})
    summary = AdmissionEvidenceSummary('ep', revision, revision, tuple(views), complete)
    return evaluate_admission(objects, verification, summary, prior, AdmissionPolicy())


def view(i, *, x=None, centroid=(0.,0.,0.), **kwargs):
    values = dict(event_id=str(i), object_id='id', source=FrameKey('ep','camera',i), detection_id=str(i), object_revision=i, capture_monotonic_ns=i, clock_domain='clock', calibration_id='cal', geometry_hash='a'*64, vocabulary_id='vocab', feature_space='none', evidence_kind='detected', temporal_status='current', depth_fraction=.8, voxel_count=30, centroid=centroid, camera_position=(float(i if x is None else x),0.,0.), label='chair')
    values.update(kwargs)
    return AdmissionView(**values)


def test_multiview_geometry_and_repeat_frame():
    assert fixture([view(1)]).decisions['id'].state == 'candidate'
    assert fixture([view(1),view(2),view(3)]).decisions['id'].state == 'admitted'
    repeat = view(3, source=FrameKey('ep','camera',2))
    assert fixture([view(1),view(2),repeat]).decisions['id'].state == 'candidate'
    assert fixture([view(1),view(2),view(3, evidence_kind='tracked')]).decisions['id'].state == 'candidate'
    assert fixture([view(1),view(2),view(3, temporal_status='historical')]).decisions['id'].state == 'candidate'


def test_quality_outliers_and_uncertain_label():
    assert fixture([view(1),view(2),view(3, depth_fraction=.4)]).decisions['id'].state == 'candidate'
    assert fixture([view(1),view(2),view(3, voxel_count=19)]).decisions['id'].state == 'candidate'
    assert fixture([view(1),view(2, centroid=(2.,0.,0.)),view(3, centroid=(4.,0.,0.))]).decisions['id'].state == 'candidate'
    decision=fixture([view(1),view(2,label='table'),view(3,label='sofa')]).decisions['id']
    assert decision.state == 'admitted' and 'label_uncertain' in decision.reason_codes
    with pytest.raises(ValueError): view(1, depth_fraction=float('nan'))


def test_hysteresis_and_unavailable():
    views=[view(1),view(2),view(3)]
    admitted=fixture(views)
    assert fixture(views, prior=admitted).decisions['id'].state == 'admitted'
    review=fixture(views, prior=admitted, neg=3)
    assert review.decisions['id'].state == 'review_required'
    assert fixture(views, prior=review).decisions['id'].state == 'review_required'
    assert fixture(views+[view(6,x=1),view(7,x=2)], prior=review, revision=7).decisions['id'].state == 'admitted'
    assert fixture(views, complete=False).decisions['id'].availability == 'unavailable'


def test_committed_summary_and_journal_reopen(tmp_path):
    from test_projection import scene
    from test_object_identity import owner, commit
    from neusymnav.objects.admission import committed_evidence_summary, AdmissionJournal
    from neusymnav.verification.ledger import VerificationOwner
    o=owner(tmp_path)
    result=commit(o, scene())
    summary=committed_evidence_summary(o)
    assert summary.complete and len(summary.views)==1
    assert summary.views[0].depth_fraction == 1.
    v=VerificationOwner(o, clock_domain='host:boot1', now_ns=lambda: 2_000_000_000)
    v.consume(result)
    before=AdmissionJournal(o).evaluate(v)
    v.close(); o.close()
    o=owner(tmp_path); v=VerificationOwner(o, clock_domain='host:boot1', now_ns=lambda: 2_000_000_000)
    after=AdmissionJournal(o).evaluate(v)
    assert after == before
    v.close(); o.close()


def test_journal_crash_gap_unavailable(tmp_path):
    from test_projection import scene, batch
    from test_object_identity import owner, commit
    from neusymnav.objects.admission import AdmissionJournal
    from neusymnav.verification.ledger import VerificationOwner
    o=owner(tmp_path); v=VerificationOwner(o, clock_domain='host:boot1', now_ns=lambda: 2_000_000_000)
    first=commit(o,scene()); v.consume(first); AdmissionJournal(o).evaluate(v)
    result=commit(o,scene(10,depth=3.),batch(scene(10,depth=3.),()))
    assert o.ledger.connection.execute('SELECT count(*) FROM negatives').fetchone()[0] == 1
    v.close(); o.close()
    o=owner(tmp_path); v=VerificationOwner(o, clock_domain='host:boot1', now_ns=lambda: 2_000_000_000)
    v.replay(); journal=AdmissionJournal(o)
    assert journal.evaluate(v).decisions[next(iter(o.snapshot().objects))].availability == 'unavailable'
    v.close(); o.close()


def test_merge_rebuild_preserves_review_and_deduplicates():
    from neusymnav.contracts import AdmissionDecision, AdmissionSnapshot
    policy = AdmissionPolicy()
    prior = AdmissionSnapshot('ep', 5, 5, policy.version, policy.policy_hash, {
        'id': AdmissionDecision('id','admitted','available',(),(),{'transition_revision':0}),
        'old': AdmissionDecision('old','review_required','available',(),(),{'transition_revision':5}),
    })
    obj=SimpleNamespace(bounds=np.array([[0.,0.,0.],[1.,1.,1.]]))
    objects=SimpleNamespace(episode_id='ep',revision=7,objects={'id':obj},aliases={'old':'id'},resolve_id=lambda x:'id')
    ver=SimpleNamespace(episode_id='ep',object_revision=7,replay_required=False,objects={'id':SimpleNamespace(negative_views=0)})
    views=(view(1),view(2),view(3,object_id='old'),view(6,x=1),view(7,x=2))
    result=evaluate_admission(objects,ver,AdmissionEvidenceSummary('ep',7,7,views,True),prior,policy)
    assert result.decisions['id'].state == 'admitted'
    assert result.decisions['id'].availability == 'available'
    older=evaluate_admission(objects,ver,AdmissionEvidenceSummary('ep',7,7,views[:3],True),prior,policy)
    assert older.decisions['id'].state == 'review_required'
    assert older.decisions['id'].quality['transition_revision'] == 5


def test_expired_live_rejection_does_not_poison_journal(tmp_path):
    from test_projection import scene, batch
    from test_object_identity import owner, commit
    from neusymnav.objects.admission import AdmissionJournal
    from neusymnav.verification.ledger import VerificationOwner
    o=owner(tmp_path); clock=[2_000_000_000]
    v=VerificationOwner(o,clock_domain='host:boot1',now_ns=lambda:clock[0])
    journal=AdmissionJournal(o)
    first=commit(o,scene()); v.consume(first); journal.evaluate(v)
    obs=scene(10,depth=3.)
    result=commit(o,obs,batch(obs,()))
    clock[0]=4_000_000_000
    v.consume(result)
    row=v._db.execute('SELECT accepted,reason,data FROM negatives').fetchone()
    assert row['accepted']==0 and row['reason']=='historical_or_expired'
    state=journal.evaluate(v).decisions[next(iter(o.snapshot().objects))]
    assert state.availability=='available'
    assert 'negative_recovery_gap' not in state.reason_codes
    v.close(); o.close()
