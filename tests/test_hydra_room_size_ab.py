import importlib.util
from pathlib import Path
import pytest

_spec = importlib.util.spec_from_file_location('size_ab', Path(__file__).resolve().parents[1]/'tools/run_hydra_room_size_ab.py')
ab = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ab)


def test_partition_comparison_ignores_room_label_renaming():
    assert ab.partition_comparison({'a':'R0','b':'R0','c':'R1'}, {'a':'R9','b':'R9','c':'R2'})['pair_disagreement_count'] == 0


def test_partition_comparison_counts_split_and_unassigned_separately():
    d=ab.partition_comparison({'a':'R0','b':'R0','c':'R0'}, {'a':'R1','b':'R2','c':None})
    assert d['pair_disagreement_count']==3
    assert d['unassigned_count']==1
    assert d['pair_disagreement_fraction']==1.


def test_partition_comparison_rejects_different_place_ids():
    with pytest.raises(ValueError,match='same place IDs'):
        ab.partition_comparison({'a':'R0'}, {'b':'R0'})


def test_unassigned_nodes_not_a_room():
    d=ab.partition_comparison({'a':None,'b':None}, {'a':'R0','b':'R0'})
    assert d['pair_disagreement_count']==1


def test_variant_only_changes_two_declared_fields():
    cfg={'frontend':{'x':1},'backend':{'update_functors':{'rooms':{'room_finder':{'min_component_size':10,'min_room_size':10,'plateau_ratio':.25}}}}}
    got=ab.variant_config(cfg,3,5)
    assert cfg['backend']['update_functors']['rooms']['room_finder']['min_room_size']==10
    assert got['frontend']==cfg['frontend']
    assert got['backend']['update_functors']['rooms']['room_finder']=={'min_component_size':3,'min_room_size':5,'plateau_ratio':.25}


def test_partition_metric_matches_exhaustive_pair_oracle():
    from itertools import combinations, product
    ids=['a','b','c']
    for ref in product((None,'R0','R1'),repeat=3):
        for cand in product((None,'R2','R3'),repeat=3):
            a=dict(zip(ids,ref));b=dict(zip(ids,cand))
            expected=sum((a[x] is not None and a[x]==a[y])!=(b[x] is not None and b[x]==b[y]) for x,y in combinations(ids,2))
            assert ab.partition_comparison(a,b)['pair_disagreement_count']==expected
