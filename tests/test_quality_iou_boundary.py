import math

from neusymnav.evaluation.association_quality import evaluate_association
from neusymnav.evaluation.detection_quality import evaluate_detection


def frame():
    return dict(frame_id='f',gt=[dict(id='g',label='chair',bbox=[0,0,3,1])],
        pred=[dict(id='p',identity='track',label='chair',score=.9,bbox=[1,0,4,1])])


def test_association_exact_half_inclusive_and_nextafter_rejected():
    assert evaluate_association([frame()])['online']['idf1']['value']==1
    assert evaluate_association([frame()],iou_threshold=math.nextafter(.5,1))['online']['idf1']['value']==0


def test_detection_exact_half_inclusive_and_nextafter_rejected():
    f=frame(); del f['pred'][0]['identity']
    result=evaluate_detection([f])
    assert result['operating_point']['tp']==1
    assert result['bbox_ap']['ap50']==1
    assert evaluate_detection([f],iou_threshold=math.nextafter(.5,1))['operating_point']['tp']==0


def test_overflow_union_keeps_exact_half_without_relaxation():
    w,h=math.ldexp(1.,510),math.ldexp(1.,512)
    f=frame(); f['gt'][0]['bbox']=[0,0,3*w,h]; f['pred'][0]['bbox']=[w,0,4*w,h]
    assert evaluate_association([f])['online']['idf1']['value']==1
    assert evaluate_association([f],iou_threshold=math.nextafter(.5,1))['online']['idf1']['value']==0
    del f['pred'][0]['identity']
    assert evaluate_detection([f])['bbox_ap']['ap50']==1
    assert evaluate_detection([f],iou_threshold=math.nextafter(.5,1))['operating_point']['tp']==0
