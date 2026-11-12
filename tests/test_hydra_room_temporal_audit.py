import pytest
from neusymnav.evaluation.room_temporal_audit import audit_revisions


def snap(rev,labels,positions=None,episode='ep'):
    positions=positions or {k:[float(i),0.,1.] for i,k in enumerate(labels)}
    return {'episode_id':episode,'graph_revision':rev,'input_prefix_sha256':str(rev)*64,
            'summary':{'nodes':[{'layer_id':3,'native_id':k,'parent_native_id':v,'position':positions[k]} for k,v in labels.items()]+[{'layer_id':4,'native_id':v,'parent_native_id':None,'position':[0.,0.,1.]} for v in sorted(set(labels.values())-{None})]},
            'place_edges':[]}


def test_label_rename_reports_id_churn_without_geometry_split():
    old={'a':'R0','b':'R0','c':'R1','d':'R1'}
    now={'a':'R2','b':'R2','c':'R3','d':'R3'}
    t=audit_revisions([snap(1,old),snap(2,now)])['transitions'][0]
    assert t['raw_room_id_change_count']==4
    assert t['pair_disagreement_count']==0
    assert t['split_events']==[] and t['merge_events']==[]


def test_split_and_merge_on_stable_place_support():
    labels={'a':'R0','b':'R0','c':'R0','d':'R0'}
    split={'a':'R0','b':'R0','c':'R1','d':'R1'}
    t=audit_revisions([snap(1,labels),snap(2,split),snap(3,labels)])['transitions']
    assert len(t[0]['split_events'])==1
    assert len(t[1]['merge_events'])==1
    assert t[0]['pair_disagreement_count']==4


def test_moving_representative_excluded_from_stable_geometry():
    old=snap(1,{'a':'R0','b':'R0'})
    now=snap(2,{'a':'R0','b':'R1'},{'a':[0.,0.,1.],'b':[4.,0.,1.]})
    t=audit_revisions([old,now])['transitions'][0]
    assert t['moved_common_place_count']==1
    assert t['stable_common_place_count']==1
    assert t['pair_count']==0


def test_new_room_from_new_support_is_not_a_split():
    a=snap(1,{'a':'R0','b':'R0'})
    b=snap(2,{'a':'R0','b':'R0','c':'R1','d':'R1'})
    t=audit_revisions([a,b])['transitions'][0]
    assert t['new_place_count']==2 and not t['split_events']


def test_rejects_cross_episode_and_missing_revision():
    with pytest.raises(ValueError,match='episode'):
        audit_revisions([snap(1,{'a':'R0'}),snap(2,{'a':'R0'},episode='other')])
    with pytest.raises(ValueError,match='contiguous'):
        audit_revisions([snap(1,{'a':'R0'}),snap(3,{'a':'R0'})])


def test_unassigned_pair_not_treated_as_a_room():
    t=audit_revisions([snap(1,{'a':None,'b':None}),snap(2,{'a':'R0','b':'R0'})])['transitions'][0]
    assert t['pair_disagreement_count']==1
    assert t['became_assigned_count']==2


def test_partition_pair_formula_matches_independent_exhaustive_oracle():
    from itertools import combinations,product
    from neusymnav.evaluation.room_temporal_audit import _partition_pairs
    ids=['a','b','c']
    for left in product((None,'R0','R1'),repeat=3):
        for right in product((None,'X0','X1'),repeat=3):
            a=dict(zip(ids,left));b=dict(zip(ids,right))
            expected=sum((a[x] is not None and a[x]==a[y])!=(b[x] is not None and b[x]==b[y]) for x,y in combinations(ids,2))
            assert _partition_pairs(a,b)['pair_disagreement_count']==expected
