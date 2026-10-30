import copy
import pytest
from neusymnav.evaluation.quality_semantic_gt import semantic_dataset


def test_offline_only_semantic_overlay_preserves_geometry_defaults(tmp_path):
    original=dict(stages=dict(paths={'.glb':['a/*.basis.glb','b/*.basis.glb']},
        default_attributes=dict(shader_type='flat',up=[0,0,1],front=[0,1,0],origin=[0,0,0])),
        objects={},light_setups={},scene_instances=dict(default_attributes=dict(default_lighting='no_lights'),paths={'.json':['a/*.json']}))
    saved=copy.deepcopy(original)
    scene=tmp_path/'a/s.basis.glb';semantic=tmp_path/'a/s.semantic.glb';annotation=tmp_path/'a/s.semantic.txt'
    result=semantic_dataset(original,tmp_path,scene,semantic,annotation)
    assert original==saved
    assert result['stages']['paths']=={'.glb':[str(scene)]}
    attrs=result['stages']['default_attributes']
    assert all(attrs[k]==v for k,v in saved['stages']['default_attributes'].items())
    assert attrs['semantic_asset']==str(semantic)
    assert attrs['semantic_descriptor_filename']==str(annotation)
    assert attrs['has_semantic_textures'] is True
    assert result['scene_instances']['paths']['.json']==[str(tmp_path/'a/*.json')]
    assert result['scene_instances']['default_attributes']==original['scene_instances']['default_attributes']


def test_bad_source_dataset_rejected(tmp_path):
    with pytest.raises(ValueError):semantic_dataset({},tmp_path,tmp_path/'x',tmp_path/'y',tmp_path/'z')
