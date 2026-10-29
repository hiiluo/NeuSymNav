from dataclasses import replace
import numpy as np
import pytest
from contract_helpers import observation
from neusymnav.contracts.observations import Detection, DetectionBatch, FrameKey


def scene(index=0, *, depth=2., stamp=None, shift=0.):
    pose = np.eye(4)
    pose[0, 3] = shift
    return observation(key=FrameKey('episode', 'rgbd', index),
        capture_monotonic_ns=1_000_000_000 + index * 100_000_000 if stamp is None else stamp,
        rgb=np.zeros((32, 32, 3), np.uint8), depth_m=np.full((32,32), depth, np.float32),
        valid_depth=np.ones((32,32), bool),
        K=np.array([[40.,0.,16.],[0.,40.,16.],[0.,0.,1.]]), T_world_camera=pose)


def batch(obs, boxes=((12,12,20,20),), **changes):
    ds=[]
    for i,(x0,y0,x1,y1) in enumerate(boxes):
        mask=np.zeros(obs.depth_m.shape,bool); mask[y0:y1,x0:x1]=True
        ds.append(Detection(str(i),'chair','chair',.9,mask))
    return DetectionBatch.from_observation(obs,tuple(ds),vocabulary_id='v1',**changes)


def test_delayed_projection_uses_capture_pose_and_axial_oracle():
    from neusymnav.perception.projector import Projector
    obs=scene(shift=10.)
    projected=Projector(min_points=1).project(obs,batch(obs))
    raw=[]
    for v in range(12,20):
        for u in range(12,20):
            raw.append([10+(u-16)*2/40,(v-16)*2/40,2.])
    # Pixel separation exceeds voxel size, so every independent oracle point remains.
    actual=np.array(sorted(map(tuple,projected[0].points_world)))
    np.testing.assert_allclose(actual,np.array(sorted(map(tuple,raw))),atol=1e-12)
    with pytest.raises(ValueError,match='source'):
        Projector().project(scene(1),batch(obs))


def test_projection_drops_invalid_depth_and_selects_median_component():
    from neusymnav.perception.projector import Projector
    obs=scene(); values=obs.depth_m.copy(); values[12:14,12:20]=4.
    obs=replace(obs,depth_m=values)
    cloud=Projector(min_points=1).project(obs,batch(obs))[0].points_world
    assert np.all(cloud[:,2]==2.)
    obs=replace(obs,valid_depth=np.zeros_like(obs.valid_depth))
    assert Projector(min_points=1).project(obs,batch(obs))==()


def test_fixture_detector_is_explicit_and_rejects_secondary_depth():
    from neusymnav.perception.detector import FixtureDetector
    obs=scene(); detector=FixtureDetector({obs.key:batch(obs)})
    assert detector.infer(obs).source==obs.key
    with pytest.raises(ValueError): detector.infer(replace(obs,modality='depth_only'))


def test_yoloe_lazy_local_assets_and_strict_result_source(tmp_path):
    from types import SimpleNamespace
    from neusymnav.perception.yoloe import YOLOEDetector
    from neusymnav.contracts.observations import Taxonomy
    checkpoint=tmp_path/'yoloe-11s-seg.pt'; checkpoint.write_bytes(b'fixture checkpoint, no native model')
    encoder=tmp_path/'mobileclip_blt.ts'; encoder.write_bytes(b'fixture encoder')
    taxonomy=Taxonomy('v1',('chair',),{},'fixture vocabulary')
    calls=[]
    class Model:
        def set_classes(self,terms,embeddings): calls.append(('classes',terms,embeddings))
        def predict(self,**options):
            calls.append(('predict',options))
            mask=np.zeros((1,32,32),float); mask[:,12:20,12:20]=1
            return [SimpleNamespace(orig_img=options['source'],orig_shape=(32,32),
                boxes=SimpleNamespace(cls=np.array([0.]),conf=np.array([.9])),
                masks=SimpleNamespace(data=mask))]
    model=Model()
    detector=YOLOEDetector(checkpoint,encoder,taxonomy,checkpoint_license='fixture',
        model_factory=lambda path: calls.append(('load',path)) or model,
        prompt_embedding_provider=lambda model,prompts:'offline embeddings',max_detections=1)
    assert calls==[]
    obs=scene(); result=detector.infer(obs)
    assert len(result.detections)==1 and result.cap_reached
    assert result.geometry_hash==obs.geometry_hash
    options=[v[1] for v in calls if v[0]=='predict'][0]
    assert options['retina_masks'] and options['imgsz']==480
    np.testing.assert_array_equal(options['source'],obs.rgb[...,::-1])
    with pytest.raises(FileNotFoundError):
        YOLOEDetector(tmp_path/'missing.pt',encoder,taxonomy,checkpoint_license='fixture')


def test_projection_components_and_voxels_match_independent_source_oracle():
    import json
    from pathlib import Path
    from neusymnav.perception.projector import Projector
    fixture=json.loads((Path(__file__).parent/'fixtures/objects/parity-v1.json').read_text())
    case=fixture['component']
    np.testing.assert_array_equal(Projector._median_depth_component(np.array(case['depths'])),case['keep'])
    case=fixture['voxel']; means,counts=Projector._voxelize(np.array(case['points']))
    np.testing.assert_allclose(means,case['means'],rtol=0,atol=1e-14)
    np.testing.assert_array_equal(counts,case['counts'])
