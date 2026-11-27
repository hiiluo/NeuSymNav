"""Verify the opt-in native journal on sealed RGB-D pipeline input."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

import yaml

from neusymnav.backends.hydra.room_stability import _hydra_paths_from_maps, _read_process_maps
from neusymnav.backends.hydra.worker import _PipelineOwner, _graph_summary
from tools.probe_hydra_detail import selected_prefix


CONFIG = Path('runs/reasoninggraph/m1-live-20261127/config.json')
JOURNAL = Path('runs/hydra-attribute-query/hna-live-00806-8yoan0t4/host-off/hydra/journal.jsonl')


def step(pipeline, frame):
    return pipeline.step(frame.capture_monotonic_ns, frame.world_t_body,
                         frame.world_R_body_wxyz, frame.depth_m, frame.labels, frame.rgb)


def digest(summary):
    return hashlib.sha256(json.dumps(summary, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def pinned_config(output):
    config = json.loads(CONFIG.read_bytes())['scene_graph']['hydra']
    frozen = Path(config['config_root'])
    isolated = output / 'probe-config'
    shutil.copytree(frozen, isolated, dirs_exist_ok=True)
    dataset = isolated / 'datasets/neusymnav.yaml'
    data = yaml.safe_load(dataset.read_text())
    # This profile loads an older private libhydra.so by absolute path.
    # It cannot share a process with a binding built against the patched ABI.
    data.pop('neusymnav_room_stability', None)
    dataset.write_text(yaml.safe_dump(data, sort_keys=False))
    return isolated, hashlib.sha256(dataset.read_bytes()).hexdigest()


def run(output, frames, expected_library, journal):
    config, config_sha256 = pinned_config(output)
    import hydra_python._hydra_bindings  # Load only the binding selected by the isolated runner.

    assert _hydra_paths_from_maps(_read_process_maps()) == {expected_library.resolve(strict=True)}
    inputs = selected_prefix(journal, frames)
    owner = _PipelineOwner(config, output / 'journal-probe-native')
    owner._initialize(inputs[0][0])
    assert owner.room_stability_bridge is None
    pipeline = owner.pipeline
    assert pipeline.object_event_batch is None
    disabled = []
    for index, (frame, prefix) in enumerate(inputs, 1):
        assert step(pipeline, frame)
        assert pipeline.object_event_batch is None
        disabled.append(digest(_graph_summary(pipeline.graph, graph_revision=index,
                                              input_prefix_sha256=prefix)))
    pipeline.reset()
    pipeline.enable_object_event_journal()
    assert pipeline.object_event_batch is None

    batches = []
    first_epoch = None
    for index, (frame, prefix) in enumerate(inputs, 1):
        result = owner.process_frame(frame)
        assert result['accepted'] and result['graph_revision'] == index
        assert result['input_prefix_sha256'] == prefix
        assert digest(result['graph_summary']) == disabled[index - 1]
        batch = pipeline.object_event_batch
        assert batch['step'] == index and batch['timestamp_ns'] == frame.capture_monotonic_ns
        assert batch['status'] == 'complete'
        first_epoch = first_epoch or batch['epoch']
        assert batch['epoch'] == first_epoch
        batches.append({**batch, 'accepted_revision': index, 'accepted_prefix_sha256': prefix,
                        'graph_summary_sha256': disabled[index - 1]})
    first_creation = next(
        batch['step'] for batch in batches
        if {'owner': 'frontend', 'operation': 'create', 'source': 'O(0)', 'target': None}
        in batch['events']
    )
    pipeline.reset()
    assert pipeline.object_event_batch is None
    for index, (frame, _) in enumerate(inputs[:first_creation], 1):
        assert step(pipeline, frame)
        reset_batch = pipeline.object_event_batch
        assert reset_batch['step'] == index and reset_batch['epoch'] != first_epoch
        assert reset_batch['events'] == batches[index - 1]['events']
    with journal.open('rb') as stream:
        journal_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    counts = Counter(f"{event['owner']}:{event['operation']}" for batch in batches for event in batch['events'])
    result = dict(input_journal_sha256=journal_sha256, native_binding_sha256=owner.native_binding_hash,
                  config_sha256=config_sha256, room_stability_bridge=False,
                  accepted_prefixes=frames, graph_summary_parity=frames, events=dict(counts),
                  batches=batches, reset_batch=reset_batch)
    (output / 'journal-probe.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'batches'}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-library', type=Path, required=True)
    parser.add_argument('--journal', type=Path, default=JOURNAL)
    parser.add_argument('--frames', type=int, choices=range(1, 65), default=3, metavar='1..64')
    args = parser.parse_args()
    run(args.output, args.frames, args.expected_library, args.journal)
