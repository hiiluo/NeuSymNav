"""Display-only detector sources never borrow the newest camera image."""
from dataclasses import replace
import numpy as np
import pytest
from neusymnav.contracts import FrameKey
from neusymnav.visualization.publisher import DisplayImage, DisplaySources
from test_display_snapshot import make_publisher


@pytest.fixture(scope='module', autouse=True)
def qt_app():
    from PyQt5 import QtWidgets
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def observation():
    from neusymnav.visualization.publisher import DisplayInstance, DisplayObservation
    image=DisplayImage('rgb',FrameKey('e','rgbd',1),10,'clock',np.full((32,48,3),60,np.uint8))
    mask=np.zeros((32,48),bool);mask[8:24,12:36]=True
    return DisplayObservation(image,(DisplayInstance('d1','chair',.92,mask),),1,'complete',False)


def test_masks_are_owned_and_render_only_on_their_source_image():
    from neusymnav.visualization.perception_overlay import render_observation
    item=observation();before=item.image.pixels.copy()
    raw=render_observation(item,boxes=False,masks=False)
    painted=render_observation(item,boxes=True,masks=True)
    assert np.array_equal(raw,before)
    assert not np.array_equal(painted,before)
    assert np.array_equal(item.image.pixels,before)
    assert np.array_equal(painted[-1,-1],before[-1,-1])
    with pytest.raises(ValueError):item.instances[0].mask.setflags(write=True)


def test_mask_shape_and_payload_caps_are_closed():
    from neusymnav.visualization.publisher import DisplayInstance, DisplayObservation
    item=observation()
    with pytest.raises(ValueError):replace(item,instances=(DisplayInstance('d','chair',.8,np.ones((2,2),bool)),))
    with pytest.raises(ValueError):replace(item,instances=item.instances*65,total_detections=65)
    with pytest.raises(ValueError):replace(item,total_detections=0)
    with pytest.raises(ValueError):DisplayInstance('x','chair',float('nan'),np.ones((2,2),bool))


def test_observation_ipc_roundtrip_and_old_sources_stay_compatible():
    import json
    from neusymnav.runtime.ui_transport import encode_publication,decode_publication
    publisher,hierarchy,metrics,*_=make_publisher()
    sources=replace(metrics['sources'],observation=observation())
    publisher.publish(hierarchy,{**metrics,'sources':sources})
    packet=encode_publication(publisher.read_latest());restored=decode_publication(packet)
    assert restored.sources.observation.image.source.frame_index==1
    assert restored.sources.rgb.source.frame_index==2
    assert np.array_equal(restored.sources.observation.instances[0].mask,observation().instances[0].mask)
    value=json.loads(packet);fields=value['payload']['fields']['sources']['fields'];fields.pop('observation');fields.pop('robot')
    assert decode_publication(json.dumps(value).encode()).sources.observation is None


def test_observation_cannot_cross_episode_or_host_clock():
    publisher,hierarchy,metrics,*_=make_publisher()
    item=observation()
    for image in [replace(item.image,source=FrameKey('wrong','rgbd',1)),replace(item.image,clock_domain='other')]:
        with pytest.raises(ValueError):publisher.publish(hierarchy,{**metrics,'sources':replace(metrics['sources'],observation=replace(item,image=image))})


def test_committed_reader_uses_exact_processed_source_and_checks_assets(tmp_path):
    from neusymnav.visualization.detector_observation import CommittedObservationReader
    from test_object_identity import owner,commit
    from test_projection import scene,batch
    o=owner(tmp_path);obs=scene();commit(o,obs,batch(obs))
    reader=CommittedObservationReader(o.assets.root,clock_domain=obs.clock_domain)
    item=reader.read(obs.key)
    assert item.image.source==obs.key
    assert item.total_detections==1
    assert np.array_equal(item.instances[0].mask,batch(obs).detections[0].mask)
    assert reader.read(replace(obs.key,frame_index=1)) is None
    assert reader.read(obs.key) is item
    source=o.ledger.batch_records()[0]['batch_asset']
    o.assets.path(source).write_bytes(b'corrupt')
    other=CommittedObservationReader(o.assets.root,clock_domain=obs.clock_domain)
    with pytest.raises(ValueError,match='checksum'):other.read(obs.key)
    o.close()


def test_overlay_enlargement_is_bounded_for_tall_valid_images():
    from neusymnav.visualization.publisher import DisplayObservation
    from neusymnav.visualization.perception_overlay import render_observation
    image=DisplayImage('rgb',FrameKey('e','rgbd',1),10,'clock',np.full((120,32,3),60,np.uint8))
    painted=render_observation(DisplayObservation(image,(),0,'complete',False))
    assert painted.shape[0]<=1080 and painted.shape[1]<=640
    assert np.all(painted==60)
