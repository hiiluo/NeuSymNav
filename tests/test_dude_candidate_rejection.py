"""Candidate geometry rejection cannot hide schema faults or kill healthy IPC."""
from copy import deepcopy
from dataclasses import replace
import json
import sys

import numpy as np
import pytest

from neusymnav.contracts import FrameKey, NavSnapshot, RegionGrid
from neusymnav.regions import DuDeConfig, DuDeWorkerClient, RegionBackend

# Exact raw_id=0 outer from retained runtime11 00802 native response.
# Wire SHA is pinned in runtime11-region-diagnosis/artifact-manifest.json.
NATIVE_RETRACE = [[2.8000001907348633,4.849999904632568],[2.8000001907348633,5.300000190734863],
 [2.75,5.349999904632568],[2.75,6.25],[2.8000001907348633,6.300000190734863],
 [2.8000001907348633,6.5],[2.75,6.449999809265137],[2.700000286102295,6.449999809265137],
 [2.6500000953674316,6.399999618530273],[2.5500001907348633,6.399999618530273],
 [2.5999999046325684,6.349999904632568],[2.5999999046325684,6.300000190734863],
 [2.6500000953674316,6.25],[2.6500000953674316,5.5],[2.5999999046325684,5.449999809265137],
 [2.5999999046325684,5.300000190734863],[2.4000000953674316,5.099999904632568],
 [2.4000000953674316,4.949999809265137],[2.3000001907348633,4.849999904632568],[2.25,4.849999904632568]]
VALID = [[0.,0.],[1.,0.],[1.,1.],[0.,1.]]
CROSSING = [[0.,0.],[3.,0.],[0.,2.],[2.,2.]]


def nav(revision):
    states=np.zeros((10,10),np.int8)
    return NavSnapshot('e',revision,FrameKey('e','depth',revision),100,'clock',.5,(-1.,-2.),states,
        np.ones(states.shape,bool),np.full(states.shape,2.),'robot',0.,'calibration','a'*64)


def region(outer=VALID,raw_id=0):
    return {'raw_id':raw_id,'outer':deepcopy(outer),'centroid_xy':[.5,.5],'area_m2':1.,
            'holes_supported':False,'adjacent_raw_ids':[]}


def channel(tmp_path,responses):
    """Real persistent pipe protocol; each request consumes exactly one response."""
    p=tmp_path/'worker'
    p.write_text('#!'+sys.executable+'\n'+'''import json,sys
responses=json.loads('''+repr(json.dumps(responses))+''')
for line in sys.stdin:
 q=json.loads(line)
 if q['op']!='integrate':break
 entry=responses.pop(0)
 r={'protocol_version':1,'protocol_status':'ok','request_id':q['request_id'],
 'input_revision':q['revision'],'status':'success','branch':'captured-test',
 'frame_id':q['frame_id'],'units':'meters',
 'coordinate_convention':'world_x=origin_x+col*resolution; world_y=origin_y+row*resolution',
 'regions':entry['regions'],'diagnostics':{'preprocessing_policy':'extended_unknown_boundary'}}
 r.update(entry.get('override',{}))
 print(json.dumps(r),flush=True)
''')
    p.chmod(0o755)
    return p


@pytest.mark.parametrize('ring',[NATIVE_RETRACE,CROSSING,[[0.,0.],[1.,1.],[2.,2.]]],ids=['native-retrace','crossing','zero-area'])
def test_invalid_geometry_rejects_then_next_valid_update_same_process(tmp_path,ring):
    with DuDeWorkerClient(channel(tmp_path,[{'regions':[region(ring)]},{'regions':[region()]}])) as c:
        pid=c._proc.pid
        with pytest.raises(ValueError,match='simple and nonzero'):
            c.integrate(RegionGrid.from_nav(nav(1)))
        assert c._proc.poll() is None
        response,observations=c.integrate(RegionGrid.from_nav(nav(2)))
        assert c._proc.pid==pid and response['input_revision']==2
        assert observations[0].polygon.outer==tuple(map(tuple,VALID))


def test_real_backend_retains_accepted_pin_then_recovers_after_bad_candidate(tmp_path):
    responses=[{'regions':[region()]},{'regions':[region(NATIVE_RETRACE)]},{'regions':[region()]}]
    with RegionBackend(channel(tmp_path,responses),floor_id='f') as b:
        first=b.update(nav(1));accepted=b.accepted_nav;tracks=b.processor.tracker.snapshot()
        rejected=b.update(nav(2))
        assert rejected.stale and rejected.regions==first.regions
        assert rejected.revision==first.revision and rejected.source_map_revision==1
        assert b.accepted_nav is accepted and b.processor.tracker.snapshot()==tracks
        assert b.processor.tracker.accepted_update_index==1
        assert b.client._proc.poll() is None
        recovered=b.update(nav(3))
        assert not recovered.stale and recovered.revision==2 and recovered.source_map_revision==3
        assert b.accepted_nav.revision==3 and b.processor.tracker.accepted_update_index==2


@pytest.mark.parametrize('mutation,match',[
    ({'raw_id':True},'raw IDs'),
    ({'raw_id':2},'raw IDs'),
    ({'adjacent_raw_ids':[True]},'adjacency'),
    ({'adjacent_raw_ids':[2]},'adjacency'),
    ({'holes_supported':True},'holes'),
    ({'outer':[[0.,0.],[float('nan'),0.],[1.,1.]]},'finite'),
    ({'outer':[[0.,0.],[float('inf'),0.],[1.,1.]]},'finite'),
    ({'outer':[[0.,0.],[True,0.],[1.,1.]]},'real number'),
    ({'outer':[[0.,0.],['1',0.],[1.,1.]]},'real number'),
    ({'outer':[[0.,0.],[1.,0.,2.],[1.,1.]]},'exactly'),
    ({'outer':[[0.,0.],[1.,0.]]},'outer polygon'),
    ({'outer':[[0.,0.]]*1025},'vertex cap'),
    ({'centroid_xy':[float('nan'),0.]},'finite'),
    ({'centroid_xy':[True,0.]},'real number'),
    ({'area_m2':float('inf')},'finite'),
    ({'area_m2':False},'real number'),
],ids=['bool-id','wrong-id','bool-adjacency','unknown-adjacency','holes','nan-xy','inf-xy','bool-xy','str-xy','shape-xy','short-ring','long-ring','nan-centroid','bool-centroid','inf-area','bool-area'])
def test_later_malformed_record_is_fatal_even_after_invalid_geometry(tmp_path,mutation,match):
    later=region(raw_id=1);later.update(mutation)
    with DuDeWorkerClient(channel(tmp_path,[{'regions':[region(CROSSING),later]}])) as c:
        with pytest.raises(ValueError,match=match):c.integrate(RegionGrid.from_nav(nav(1)))
        assert c._proc.poll() is not None
        with pytest.raises(ValueError,match='error state'):c.integrate(RegionGrid.from_nav(nav(2)))


@pytest.mark.parametrize('config',[DuDeConfig(max_regions=1),DuDeConfig(max_vertices=7)])
def test_count_caps_are_fatal_before_candidate_classification(tmp_path,config):
    with DuDeWorkerClient(channel(tmp_path,[{'regions':[region(CROSSING),region(raw_id=1)]}]),config) as c:
        with pytest.raises(ValueError,match='count|cap'):c.integrate(RegionGrid.from_nav(nav(1)))
        assert c._proc.poll() is not None


@pytest.mark.parametrize('override',[{'protocol_version':True},{'input_revision':False},{'units':'pixels'},
    {'diagnostics':[]},{'diagnostics':{'preprocessing_policy':'source'}}])
def test_envelope_malformation_is_fatal_with_invalid_geometry(tmp_path,override):
    with DuDeWorkerClient(channel(tmp_path,[{'regions':[region(CROSSING)],'override':override}])) as c:
        with pytest.raises(ValueError):c.integrate(RegionGrid.from_nav(nav(1)))
        assert c._proc.poll() is not None
