import json
from pathlib import Path

from tools.check_hydra_acceptance import evaluate_acceptance


def acceptance_bundle(root: Path):
    run = root / 'run'; run.mkdir()
    asset = run / 'graph.sparkdsg'; asset.write_bytes(b'native graph bytes')
    journal = run / 'journal.jsonl'; journal.write_text('{}\n')
    import hashlib
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = dict(schema_version=1, complete=True, graph_path=str(asset),
        graph_sha256=sha(asset), graph_bytes=asset.stat().st_size,
        graph_revision=1,input_prefix_sha256='a'*64, journal_path=str(journal), journal_sha256=sha(journal),
        selected_inputs=[dict(source={'frame_index':0},payload_sha256='b'*64,payload_bytes=10)])
    (run/'hydra-export-manifest.json').write_text(json.dumps(manifest))
    compare=dict(duration_s=90,complete=True,translation_m=10.,pending_source_fraction=.05,
        ordered_input_sha256='c'*64,source_sha256='d'*64,navigation_sha256='e'*64)
    data=dict(schema_version=1,runtime=dict(complete=True,timeout=False,native_steps=10,
        transform_contract_version='hydra-frame-v1',labelspace_sha256='f'*64,
        source_sha256='d'*64,navigation_sha256='e'*64,node_counts={'3':1}),
        ab_pairs=[dict(baseline=compare,hydra=dict(compare,translation_m=9.2,
            pending_source_fraction=.08)) for _ in range(3)])
    (run/'acceptance.json').write_text(json.dumps(data))
    evidence=root/'native-evidence';evidence.mkdir()
    object_dir=evidence/'h3-same-class-objects';object_dir.mkdir()
    obj=object_dir/'objects.sparkdsg';obj.write_bytes(b'objects graph')
    obj_sha=sha(obj)
    (object_dir/'result.json').write_text(json.dumps(dict(
        reloaded_objects=2,steps=[dict(accepted=True,object_nodes=2,ids=['O(0)','O(1)']) for _ in range(8)],
        graph_asset=str(obj),graph_sha256=obj_sha,valid_detection_count=2)))
    for name,rooms in [('h3-two-room',2),('h3-open-room',1)]:
        room_dir=evidence/name;room_dir.mkdir()
        graph=room_dir/f'{name}.sparkdsg';graph.write_bytes(name.encode())
        (room_dir/'result.json').write_text(json.dumps(dict(
            room_gate_pass=True,room_nodes=rooms,room_gate_expected=rooms,
            reloaded_layers={'4':rooms},graph_asset=str(graph),graph_sha256=sha(graph))))
    return run,evidence


def test_hydra_acceptance_requires_native_reload_export_and_three_nonregressing_pairs(tmp_path):
    run,evidence=acceptance_bundle(tmp_path)
    assert evaluate_acceptance(run,evidence)==[]


def test_hydra_acceptance_fails_closed_for_missing_room_or_mismatched_inputs(tmp_path):
    run,evidence=acceptance_bundle(tmp_path)
    room=evidence/'h3-two-room'/'result.json'
    data=json.loads(room.read_text());data['room_gate_pass']=False;room.write_text(json.dumps(data))
    acceptance=json.loads((run/'acceptance.json').read_text())
    acceptance['ab_pairs'][1]['hydra']['ordered_input_sha256']='0'*64
    (run/'acceptance.json').write_text(json.dumps(acceptance))
    errors=evaluate_acceptance(run,evidence)
    assert any('two-room' in item for item in errors)
    assert any('ordered source' in item for item in errors)
