import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('handoff_semantics', Path(__file__).parents[1] / 'tools/reasoninggraph/handoff_semantics.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_room_lookup_preserves_native_topology_and_missing(tmp_path):
    graph = {'nodes': [{'id': 1, 'layer': 4, 'attributes': {'name': '', 'semantic_label': 0,
             'bounding_box': {'type': 'INVALID'}}}, {'id': 2, 'layer': 3, 'attributes': {}}],
             'edges': [{'source': 1, 'target': 2}]}
    path = tmp_path / 'graph.json'
    path.write_text(json.dumps(graph))
    result = module.rooms(path, 1)
    assert result['rooms'][0]['neighbors'] == [{'id': 2, 'layer': 3}]
    assert result['rooms'][0]['bounding_box']['type'] == 'INVALID'
    assert module.rooms(path, 9)['status'] == 'no_evidence'
