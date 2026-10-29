import importlib
import json
from dataclasses import replace
import numpy as np
import pytest
from contract_helpers import observation


def obs_module():
    return importlib.import_module('neusymnav.contracts.observations')


def test_observation_owns_arrays_and_cannot_reenable_write():
    rgb = np.zeros((2, 3, 3), np.uint8)
    obs = observation(rgb=rgb)
    rgb[:] = 255
    assert not obs.rgb.any()
    for value in (obs.rgb, obs.depth_m, obs.valid_depth, obs.K, obs.T_world_camera):
        with pytest.raises(ValueError): value.setflags(write=True)


@pytest.mark.parametrize('changes', [dict(rgb=np.zeros((2, 3), np.uint8)),
    dict(depth_m=np.ones((3, 2), np.float32)), dict(valid_depth=np.ones((2, 3), np.uint8)),
    dict(K=np.zeros((3, 3))), dict(K=np.diag([2., 2., 2.])),
    dict(T_world_camera=np.diag([-1., 1., 1., 1.])), dict(modality='guess'),
    dict(calibration_id=''), dict(pose_version=-1), dict(capture_monotonic_ns=True)])
def test_invalid_observation_rejected(changes):
    with pytest.raises(ValueError): observation(**changes)


def test_invalid_depth_is_unknown_but_valid_depth_must_be_measured():
    depth = np.array([[np.nan, 0., np.inf], [1., 2., 3.]], np.float32)
    obs = observation(depth_m=depth, valid_depth=np.array([[False]*3, [True]*3]))
    assert not obs.valid_depth[0].any()
    with pytest.raises(ValueError): observation(depth_m=depth)
    with pytest.raises(ValueError):
        observation(valid_depth=np.zeros((2, 3), bool), no_return=np.ones((2, 3), bool))


def test_detection_source_mask_shape_duplicate_and_depth_only_rejected():
    m = obs_module()
    obs = observation()
    d = m.Detection('d1', 'Raw Chair', 'chair', .8, np.ones((2, 3), bool))
    batch = m.DetectionBatch(obs.key, obs.geometry_hash, 'taxonomy-v1', (d,), 'complete', False)
    m.validate_detection_batch(obs, batch)
    assert batch.allows_negative_evidence
    with pytest.raises(ValueError): replace(batch, detections=(d, d))
    with pytest.raises(ValueError): m.validate_detection_batch(obs, replace(batch, detections=(replace(d, mask=np.ones((1, 3), bool)),)))
    with pytest.raises(ValueError): m.validate_detection_batch(observation(modality='depth_only'), batch)
    with pytest.raises(ValueError): m.validate_detection_batch(replace(obs, pose_version=1), batch)
    assert not replace(batch, cap_reached=True).allows_negative_evidence
    assert not replace(batch, completion='partial').allows_negative_evidence
    m.validate_detection_batch(obs, replace(batch, detections=()))


def test_geometry_hash_binds_source_sensor_calibration_pose_and_pixels():
    obs = observation()
    m = obs_module()
    for changed in [replace(obs, key=m.FrameKey('episode', 'other', 0)),
                    replace(obs, calibration_id='cal:v2'), replace(obs, pose_version=1),
                    replace(obs, capture_monotonic_ns=101), replace(obs, K=obs.K * np.array([[2,1,1],[1,1,1],[1,1,1]])),
                    replace(obs, depth_m=np.full((2,3), 2, np.float32)),
                    replace(obs, rgb=np.ones((2,3,3), np.uint8))]:
        assert changed.geometry_hash != obs.geometry_hash
    assert observation().geometry_hash == obs.geometry_hash


def test_appearance_space_dimension_and_batch_binding():
    m = obs_module()
    feature = m.AppearanceFeature('clip:checkpoint:preprocess:v1', np.array([1., 2.], np.float32))
    with pytest.raises(ValueError): feature.require_compatible(m.AppearanceFeature('other', feature.vector))
    with pytest.raises(ValueError): feature.require_compatible(m.AppearanceFeature(feature.space_id, np.ones(3, np.float32)))
    features = {'d1': feature}
    batch = m.AppearanceBatch(observation().key, observation().geometry_hash, features)
    features.clear()
    assert 'd1' in batch.features
    with pytest.raises(TypeError): batch.features['d2'] = feature


def test_serialization_roundtrip_preserves_arrays_and_rejects_unknown_schema():
    m = obs_module()
    serialization = importlib.import_module('neusymnav.contracts.serialization')
    obs = observation(valid_depth=np.zeros((2,3), bool), depth_m=np.full((2,3), np.nan, np.float32))
    restored = serialization.loads(serialization.dumps(obs))
    assert isinstance(restored, m.Observation)
    assert restored.geometry_hash == obs.geometry_hash
    np.testing.assert_array_equal(restored.valid_depth, obs.valid_depth)
    assert np.isnan(restored.depth_m).all()
    with pytest.raises(ValueError): restored.rgb.setflags(write=True)
    payload = json.loads(serialization.dumps(obs))
    payload['schema_version'] = 999
    with pytest.raises(ValueError): serialization.loads(json.dumps(payload))


def test_nav_grid_unknown_free_and_calibration():
    g = importlib.import_module('neusymnav.contracts.graphs')
    nav = g.NavSnapshot('episode', 0, observation().key, 100, 'host:boot1', .1,
                        (0., 0.), np.array([[-1, 0, 100]], np.int8),
                        np.array([[False, True, True]]), np.array([[0., 1., .2]], np.float32),
                        'robot:v1', floor_z_m=1.2, floor_datum_source='scene:calibration', calibration_hash='a'*64)
    grid = g.RegionGrid.from_nav(nav)
    np.testing.assert_array_equal(grid.values, [[-1, 0, 100]])
    assert grid.preprocessing_policy == 'extended_unknown_boundary'
    with pytest.raises(ValueError): replace(nav, states=np.array([[0, 1, 2]], np.int8))
    with pytest.raises(ValueError): replace(nav, floor_datum_source='')
    with pytest.raises(ValueError): nav.states.setflags(write=True)


def test_object_aliases_cannot_cycle_or_dangle():
    g = importlib.import_module('neusymnav.contracts.graphs')
    state = g.ObjectState('00000000-0000-0000-0000-000000000001', 'floor1',
            np.zeros(3), np.array([[0.,0.,0.],[1.,1.,1.]]), 'candidate', (), 0,
            observation().key, 100, 100, 'host:boot1')
    objects = {state.object_id: state}
    snapshot = g.ObjectSnapshot('episode', 0, observation().key, objects, {'old':state.object_id})
    objects.clear()
    assert snapshot.resolve_id('old') == state.object_id
    with pytest.raises(ValueError): replace(snapshot, aliases={'a':'b', 'b':'a'})
    with pytest.raises(ValueError): replace(snapshot, aliases={'a':'absent'})
    with pytest.raises(ValueError): replace(state, last_seen_ns=99)


def test_motion_command_deadline_and_hierarchy_revisions():
    n = importlib.import_module('neusymnav.contracts.navigation')
    cmd = n.MotionCommand(observation().key, 2, 100, 200, 'host:boot1', 0., 0., 'stop', 90)
    assert cmd.is_valid(199, 'host:boot1')
    assert not cmd.is_valid(200, 'host:boot1')
    with pytest.raises(ValueError): cmd.is_valid(150, 'other')
    with pytest.raises(ValueError): replace(cmd, deadline_monotonic_ns=99)
    g = importlib.import_module('neusymnav.contracts.graphs')
    with pytest.raises(ValueError):
        g.HierarchySnapshot('episode', 1, 1, 4, 1, {}, (), {}, 3, 0)


def test_taxonomy_preserves_raw_and_unknown_and_exact_score():
    m = obs_module()
    taxonomy = m.Taxonomy.load('configs/taxonomy-v1.json')
    assert taxonomy.canonicalize('couch') == 'sofa'
    assert taxonomy.canonicalize('unlisted active scene category') is None
    assert taxonomy.exact_match('couch', 'sofa') is False
    assert taxonomy.exact_match('couch', 'couch') is True


def test_all_public_contracts_serialization_roundtrip_and_nested_immutability():
    from neusymnav.contracts import (AppearanceFeature, AppearanceBatch, ObjectObservation, Detection,
        DetectionBatch, ObjectState, ObjectSnapshot, CommitResult, Region, RegionSnapshot,
        HierarchyNode, HierarchyEdge, HierarchySnapshot, RegionGrid, NavSnapshot,
        NavigationDecision, MotionCommand, Taxonomy, dumps, loads)
    obs = observation()
    feature = AppearanceFeature('checkpoint:preprocess:v1', np.ones(3, np.float32))
    detection = Detection('d1', 'Chair', 'chair', .7, np.ones((2, 3), bool))
    batch = DetectionBatch.from_observation(obs, (detection,), vocabulary_id='taxonomy:v1')
    projected = ObjectObservation(obs.key, 'd1', obs.geometry_hash, np.ones((1, 3)),
                                  (0., 0., 0.), 'Chair', 'chair', .7, 'rgbd', feature)
    state = ObjectState('00000000-0000-0000-0000-000000000001', 'floor1', np.ones(3),
             np.array([[0.,0.,0.],[2.,2.,2.]]), 'active', ('asset:mask',), 1,
             obs.key, 100, 100, 'host:boot1', 'Chair', 'chair', np.eye(3), np.ones((1,3)),
             np.array([[0.,0.], [1.,0.], [1.,1.]]), feature)
    objects = ObjectSnapshot('episode', 1, obs.key, {state.object_id:state}, {'old':state.object_id})
    nav = NavSnapshot('episode', 2, obs.key, 100, 'host:boot1', .1, (1.,2.),
                      np.array([[-1,0,100]], np.int8), np.ones((1,3), bool), np.ones((1,3)),
                      'robot1', 1.2, 'scene:floor', 'f'*64)
    region = Region('r1', np.array([[0.,0.],[2.,0.],[1.,1.]]), ('r0',))
    regions = RegionSnapshot('episode', 1, 2, 'floor1', {'r1':region}, False)
    nested = {'label':'Chair', 'other':{'list':[1,2]}}
    node = HierarchyNode(state.object_id, 'object', nested)
    nested['other']['list'].append(3)
    assert node.attributes['other']['list'] == (1,2)
    with pytest.raises(TypeError): node.attributes['other']['bad'] = 1
    edge = HierarchyEdge(state.object_id, 'r1', 'membership', 'assigned',
                          {'basis':'footprint'}, 1, 2, 1)
    hierarchy = HierarchySnapshot('episode', 3, 1, 2, 1,
                 {state.object_id:node, 'r1':HierarchyNode('r1','region')}, (edge,),
                 {'membership':'assigned'}, 5, 20)
    messages = [obs, obs.key, feature, detection, batch, projected,
                AppearanceBatch(obs.key, obs.geometry_hash, {'d1':feature}), state, objects,
                CommitResult(objects, ('event1',)), nav, RegionGrid.from_nav(nav), region, regions,
                node, edge, hierarchy, NavigationDecision(None, (), 0., 0., 2, 'blocked'),
                MotionCommand(obs.key, 2, 100, 200, 'host:boot1', 0., 0., 'stop', 100),
                Taxonomy.load('configs/taxonomy-v1.json')]
    for message in messages:
        wire = dumps(message)
        restored = loads(wire)
        assert type(restored) is type(message)
        assert dumps(restored) == wire
        assert type(message).from_dict(message.to_dict()).to_json() == wire


def test_projection_and_appearance_reject_foreign_results():
    from neusymnav.contracts import (AppearanceFeature, AppearanceBatch, ObjectObservation,
        Detection, DetectionBatch, validate_appearance_batch, validate_object_observations)
    obs = observation()
    d = Detection('d1', 'Chair', 'chair', .8, np.ones((2,3), bool))
    batch = DetectionBatch.from_observation(obs, (d,), vocabulary_id='taxonomy:v1')
    feature = AppearanceFeature('space:v1', np.ones(2, np.float32))
    appearance = AppearanceBatch(obs.key, obs.geometry_hash, {'d1':feature})
    validate_appearance_batch(obs, batch, appearance)
    with pytest.raises(ValueError):
        validate_appearance_batch(obs, batch, replace(appearance, features={'invented':feature}))
    with pytest.raises(ValueError):
        validate_appearance_batch(obs, batch, replace(appearance, geometry_hash='0'*64))
    obj = ObjectObservation(obs.key, 'd1', obs.geometry_hash, np.ones((1,3)),
                            (0.,0.,0.), 'Chair', 'chair', .8, 'rgbd', feature)
    validate_object_observations(obs, batch, (obj,))
    for changed in [replace(obj, detection_id='absent'), replace(obj, geometry_hash='0'*64),
                    replace(obj, camera_position=(1.,0.,0.)), replace(obj, raw_label='wrong')]:
        with pytest.raises(ValueError): validate_object_observations(obs, batch, (changed,))
    with pytest.raises(ValueError): validate_object_observations(obs, batch, (obj,obj))
    with pytest.raises(ValueError): replace(obj, points_world=np.empty((0,3)))


def test_certified_no_return_and_far_plane_are_exclusive():
    valid = np.zeros((2,3), bool)
    mask = np.array([[True,False,False],[False,False,False]])
    obs = observation(valid_depth=valid, no_return=mask, no_return_range_m=5.)
    assert obs.no_return[0,0]
    with pytest.raises(ValueError): replace(obs, valid_depth=np.ones((2,3),bool))
    with pytest.raises(ValueError): replace(obs, far_plane=mask, far_plane_range_m=6.)
    with pytest.raises(ValueError): observation(valid_depth=valid, far_plane=mask)
    with pytest.raises(ValueError): observation(no_return_range_m=5.)


def test_wire_rejects_unknown_type_fields_unsafe_dtype_and_bad_array_length():
    from neusymnav.contracts import dumps, loads
    original = json.loads(dumps(observation()))
    import copy
    changed = copy.deepcopy(original)
    changed['payload']['type'] = '__import__'
    with pytest.raises(ValueError): loads(json.dumps(changed))
    changed = copy.deepcopy(original)
    changed['payload']['fields']['unexpected'] = 1
    with pytest.raises(ValueError): loads(json.dumps(changed))
    for dtype, data in [('O', ''), ('|u1','AA==')]:
        changed = copy.deepcopy(original)
        arr = changed['payload']['fields']['rgb']['ndarray']
        arr['dtype'], arr['data'] = dtype, data
        with pytest.raises(ValueError): loads(json.dumps(changed))


def test_hierarchy_rejects_dangling_endpoints_and_revision_skew():
    from neusymnav.contracts import HierarchyNode, HierarchyEdge, HierarchySnapshot, Region, RegionSnapshot
    nodes = {'o':HierarchyNode('o','object'), 'r':HierarchyNode('r','region')}
    edge = HierarchyEdge('o','r','membership','ambiguous',{'basis':'overlap'},3,4,5)
    HierarchySnapshot('episode',6,3,4,5,nodes,(edge,),{},7,8)
    with pytest.raises(ValueError): HierarchySnapshot('episode',6,3,4,5,{'o':nodes['o']},(edge,),{},7,8)
    with pytest.raises(ValueError): HierarchySnapshot('episode',6,2,4,5,nodes,(edge,),{},7,8)
    region = Region('r',np.array([[0.,0.],[1.,0.],[0.,1.]]),(),('missing',))
    with pytest.raises(ValueError): RegionSnapshot('episode',1,2,'floor1',{'r':region},False)


def test_numpy_certified_range_hash():
    obs = observation(valid_depth=np.zeros((2,3),bool), no_return=np.ones((2,3),bool),
                       no_return_range_m=np.float32(5.))
    assert len(obs.geometry_hash) == 64
    assert obs.geometry_hash == replace(obs, no_return_range_m=5.).geometry_hash


def test_taxonomy_boolean_version_rejected(tmp_path):
    from neusymnav.contracts import Taxonomy
    payload = json.loads(open('configs/taxonomy-v1.json').read())
    payload['schema_version'] = True
    path = tmp_path / 'taxonomy.json'
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError): Taxonomy.load(path)


def _string_tuple_message(field):
    from neusymnav.contracts import CommitResult, ObjectSnapshot, ObjectState, Region, Taxonomy
    key = observation().key
    if field == 'committed_event_ids':
        return CommitResult(ObjectSnapshot('episode', 0, key, {}, {}), ('x',))
    if field == 'evidence_refs':
        return ObjectState('00000000-0000-0000-0000-000000000001', 'floor1',
                np.zeros(3), np.array([[0.,0.,0.],[1.,1.,1.]]), 'candidate', ('x',),
                0, key, 100, 100, 'host:boot1')
    if field in ('predecessor_ids', 'adjacency'):
        return replace(Region('r', np.array([[0.,0.],[1.,0.],[0.,1.]])), **{field:('x',)})
    return Taxonomy('taxonomy:v1', ('x',), {}, 'static independent vocabulary')


@pytest.mark.parametrize('field', ['committed_event_ids', 'evidence_refs', 'predecessor_ids', 'adjacency', 'categories'])
@pytest.mark.parametrize('malformed', ['abc', '', b'', {'x':42}, {}, 42])
def test_string_tuple_constructor_rejects_scalar_and_mapping_containers(field, malformed):
    message = _string_tuple_message(field)
    with pytest.raises(ValueError):
        replace(message, **{field:malformed})


@pytest.mark.parametrize('field', ['committed_event_ids', 'evidence_refs', 'predecessor_ids', 'adjacency', 'categories'])
@pytest.mark.parametrize('malformed_wire', ['abc', '', {'mapping':{'x':42}}, {'mapping':{}}, 42])
def test_string_tuple_wire_rejects_scalar_and_mapping_containers(field, malformed_wire):
    from neusymnav.contracts import from_dict
    wire = _string_tuple_message(field).to_dict()
    wire['payload']['fields'][field] = malformed_wire
    with pytest.raises(ValueError):
        from_dict(wire)


@pytest.mark.parametrize('field', ['committed_event_ids', 'evidence_refs', 'predecessor_ids', 'adjacency', 'categories'])
@pytest.mark.parametrize('valid', [(), ('x',), ('x','y'), [], ['x'], ['x','y']])
def test_string_tuple_valid_list_tuple_roundtrip(field, valid):
    message = _string_tuple_message(field)
    if field == 'categories' and not valid:
        with pytest.raises(ValueError): replace(message, **{field:valid})
        return
    changed = replace(message, **{field:valid})
    assert getattr(changed, field) == tuple(valid)
    assert getattr(type(changed).from_dict(changed.to_dict()), field) == tuple(valid)
