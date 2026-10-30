"""Independent analytic oracles for the offline semantic trust boundary."""
import importlib

import numpy as np
import pytest


def module():
    try:
        return importlib.import_module('neusymnav.evaluation.quality_semantic_gt')
    except ModuleNotFoundError:
        pytest.fail('offline semantic GT implementation missing')


def test_world_basis_and_optical_basis_are_both_inverted():
    # Source Habitat identity at (1,2,3), converted to canonical optical.
    canonical = np.array([[1,0,0,1],[0,0,1,-3],[0,-1,0,2],[0,0,0,1]],float)
    actual = module().canonical_optical_to_habitat(canonical)
    np.testing.assert_allclose(actual, [[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]],atol=1e-12)


@pytest.mark.parametrize('pose', [np.zeros((4,4)), np.diag([1,1,-1,1]), np.full((4,4),np.nan)])
def test_invalid_pose_never_reaches_renderer(pose):
    with pytest.raises(ValueError): module().canonical_optical_to_habitat(pose)


def test_intrinsics_reject_half_pixel_and_non_square_focal_drift():
    m=module(); k=np.array([[320,0,319.5],[0,320,239.5],[0,0,1.]])
    assert m.validate_calibration(k,640,480)==pytest.approx(90)
    for y,x in [(0,2),(1,1)]:
        bad=k.copy(); bad[y,x]+=.5
        with pytest.raises(ValueError): m.validate_calibration(bad,640,480)


def images():
    return np.full((20,20,3),100,np.uint8),np.full((20,20),2,np.float32),np.ones((20,20),bool)


def test_alignment_checks_both_color_and_depth_and_nonvacuous_support():
    m=module();rgb,depth,valid=images()
    report=m.validate_alignment(rgb,depth,valid,rgb.copy(),depth.copy())
    assert report['valid_depth_pixels']==400 and report['depth_mae_m']==0
    for altered_rgb,altered_depth,altered_valid in [(255-rgb,depth,valid),(rgb,depth+1,valid),(rgb,depth,~valid),(rgb,np.full_like(depth,np.nan),valid)]:
        with pytest.raises(ValueError): m.validate_alignment(rgb,depth,altered_valid,altered_rgb,altered_depth)


def test_semantic_exclusions_are_exhaustive_and_doors_remain_in_scope(tmp_path):
    m=module(); p=tmp_path/'scene.semantic.txt'
    p.write_text('HM3D Semantic Annotations\n1,aaaaaa,"door",0\n2,bbbbbb,"wall",0\n3,cccccc,"chair",0\n4,dddddd,"couch",0\n')
    annotations=m.parse_annotations(p)
    ids=np.array([[0,1,1,2],[3,4,4,99]],np.int32)
    objects,exclusions=m.extract_instances(ids,annotations,{'categories':['door','chair','sofa'],'aliases':{'couch':'sofa'}},min_visible_pixels=2)
    assert [(x['id'],x['label'],x['bbox']) for x in objects]==[('hm3d:1','door',[1,0,3,1]),('hm3d:4','sofa',[1,1,3,2])]
    assert exclusions==[dict(instance_id=0,label=None,pixels=1,reason='background'),dict(instance_id=2,label='wall',pixels=1,reason='unsupported_taxonomy'),dict(instance_id=3,label='chair',pixels=1,reason='small'),dict(instance_id=99,label=None,pixels=1,reason='unmapped_id')]
    assert sum(int(x['mask'].sum()) for x in objects)+sum(x['pixels'] for x in exclusions)==8


def test_negative_semantic_background_and_unknown_descriptor_are_reported(tmp_path):
    m=module();p=tmp_path/'a';p.write_text('HM3D Semantic Annotations\n1,aaaaaa,"unknown",0\n')
    objects,excluded=m.extract_instances(np.array([[-1,4294967295,1]],np.int64),m.parse_annotations(p),{'categories':['chair'],'aliases':{}},min_visible_pixels=1)
    assert objects==[]
    assert [e['reason'] for e in excluded]==['background','unsupported_taxonomy','background']


@pytest.mark.parametrize('rows',['1,aaaaaa,"door",0\n1,bbbbbb,"chair",0\n','0,aaaaaa,"door",0\n','1,zzzzzz,"door",0\n'])
def test_bad_annotation_ids_cannot_change_instance_denominators(tmp_path,rows):
    p=tmp_path/'a';p.write_text('HM3D Semantic Annotations\n'+rows)
    with pytest.raises(ValueError):module().parse_annotations(p)


def prepared_fixture(tmp_path, count=1):
    import hashlib,json
    from test_quality_export import make_ledger,run_export
    from dataclasses import replace
    import test_quality_export
    factory=test_quality_export.scene
    def calibrated_source(*args,**kwargs):
        value=factory(*args,**kwargs); k=value.K.copy(); k[0,2]=k[1,2]=15.5
        return replace(value,K=k)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(test_quality_export,'scene',calibrated_source)
        assets=make_ledger(tmp_path,count=count,merge=count>1)
    exported=run_export(tmp_path,assets)
    def desc(path):return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    for name in ['scene.basis.glb','dataset.json','scene.semantic.glb']:(tmp_path/name).write_text(name)
    annotation=tmp_path/'scene.semantic.txt';annotation.write_text('HM3D Semantic Annotations\n1,aaaaaa,"chair",0\n')
    config=dict(episode=dict(id='episode',primary_sensor_id='rgbd'),detector=dict(taxonomy=desc(assets[2])),sensor_config=dict(scene=desc(tmp_path/'scene.basis.glb'),scene_dataset=desc(tmp_path/'dataset.json'),primary=dict(depth_min_m=.1,depth_max_m=10.)))
    config_path=tmp_path/'config.json';config_path.write_text(json.dumps(config))
    return assets,exported,config_path,desc(config_path)['sha256'],tmp_path/'scene.semantic.glb',annotation


def test_prepare_binds_verified_source_assets_and_freezes_request(tmp_path):
    import json
    assets,exported,config,checksum,semantic,annotation=prepared_fixture(tmp_path)
    result=module().prepare_request(exported['predictions'],assets[0],config,checksum,semantic,annotation,tmp_path/'prepared')
    request=json.loads(result.read_text())
    assert len(request['frames'])==1 and request['frames'][0]['frame']['frame_id']=='rgbd:0'
    checked=module().verify_request(result)
    assert checked['predictions']['binding']['scene_id']=='synthetic-test-scene'
    source=tmp_path/'prepared'/request['frames'][0]['arrays']['path']
    source.write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='SHA'):module().verify_request(result)


def test_wrong_frozen_config_is_rejected_without_output(tmp_path):
    assets,exported,config,checksum,semantic,annotation=prepared_fixture(tmp_path)
    with pytest.raises(ValueError,match='SHA'):
        module().prepare_request(exported['predictions'],assets[0],config,'0'*64,semantic,annotation,tmp_path/'prepared')
    assert not (tmp_path/'prepared').exists()


def test_materialization_keeps_semantic_identity_across_frames_and_rejects_misalignment(tmp_path):
    rgb,depth,valid=images();ids=np.ones((20,20),np.int32)
    source=dict(rgb=rgb,depth=depth,valid=valid)
    m=module();frame=dict(frame_id='s:1',frame_index=1,capture_monotonic_ns=1,source_sha256='a'*64,geometry_hash='b'*64,width=20,height=20)
    annotated,report=m.materialize_frame(frame,source,rgb,depth,ids,{1:'door'},{'categories':['door'],'aliases':{}},tmp_path,0)
    assert annotated['annotated'] is True and annotated['objects'][0]['id']=='hm3d:1'
    assert report['included_instances']==1 and report['excluded']==[]
    with pytest.raises(ValueError,match='alignment'):
        m.materialize_frame(frame,source,rgb,depth+1,ids,{1:'door'},{'categories':['door'],'aliases':{}},tmp_path,1)
    assert not (tmp_path/'000001-0000.npy').exists()


def test_capture_config_provenance_cannot_be_substituted(tmp_path):
    import hashlib,json
    path=tmp_path/'recording.json';path.write_text(json.dumps(dict(episode_id='episode',source_provenance=dict(config_sha256='a'*64))))
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='capture config'):
        module().verify_capture_binding(path,digest,'b'*64,'recorded')
    assert module().verify_capture_binding(path,digest,'a'*64,'recorded')['episode_id']=='episode'


def test_effective_float32_projection_roundoff_is_representable_without_halfpixel_drift():
    k=np.array([[319.99996185302734,0,319.5],[0,319.9999809265137,239.5],[0,0,1.]])
    assert module().validate_calibration(k,640,480)==pytest.approx(90,abs=.0001)


@pytest.mark.parametrize('mutation',['swapped_arrays','primary','frame_order','frame_metadata','source_digest','hfov'])
def test_request_cannot_detach_source_metadata_arrays_or_camera_from_frozen_inputs(tmp_path,mutation):
    import json
    assets,exported,config,checksum,semantic,annotation=prepared_fixture(tmp_path,count=2)
    path=module().prepare_request(exported['predictions'],assets[0],config,checksum,semantic,annotation,tmp_path/'prepared')
    request=json.loads(path.read_text())
    if mutation=='swapped_arrays':
        request['frames'][0]['arrays'],request['frames'][1]['arrays']=request['frames'][1]['arrays'],request['frames'][0]['arrays']
    elif mutation=='primary':request['primary']['depth_max_m']=99
    elif mutation=='frame_order':request['frames'].reverse()
    elif mutation=='frame_metadata':request['frames'][0]['frame']['capture_monotonic_ns']+=1
    elif mutation=='source_digest':request['frames'][0]['source']=request['frames'][1]['source']
    elif mutation=='hfov':request['frames'][0]['hfov_deg']+=1
    path.write_text(json.dumps(request))
    with pytest.raises(ValueError):module().verify_request(path)


def test_rehashed_prepared_pose_still_must_equal_original_typed_observation(tmp_path):
    import hashlib,json
    assets,exported,config,checksum,semantic,annotation=prepared_fixture(tmp_path)
    path=module().prepare_request(exported['predictions'],assets[0],config,checksum,semantic,annotation,tmp_path/'prepared')
    request=json.loads(path.read_text());descriptor=request['frames'][0]['arrays'];array_path=path.parent/descriptor['path']
    with np.load(array_path,allow_pickle=False) as archive:arrays={key:archive[key] for key in archive.files}
    arrays['pose'][0,3]+=3
    np.savez_compressed(array_path,**arrays);descriptor['sha256']=hashlib.sha256(array_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(request))
    with pytest.raises(ValueError,match='source arrays'):module().verify_request(path)
