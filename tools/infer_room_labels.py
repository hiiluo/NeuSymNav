#!/usr/bin/env python3
"""Run the rules baseline and opt-in local room SLM on one frozen request."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from neusymnav.contracts.room_semantics import validate_room_label
from neusymnav.evaluation.room_labels import RULE_BASELINE_VERSION, rule_baseline
from neusymnav.rooms.prompt import OUTPUT_SCHEMA_SHA256
from neusymnav.rooms.requests import RoomLabelRequest
from neusymnav.rooms.slm_backend import LlamaCppRoomLabelBackend, RoomSlmBackendConfig


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-json', required=True,
        help='serialized immutable RoomLabelRequest created from one native graph snapshot')
    parser.add_argument('--config', default='configs/room-label-slm.experimental.json')
    parser.add_argument('--out', required=True, help='new or replaceable offline prediction JSON path')
    args = parser.parse_args(argv)

    request_path = Path(args.request_json)
    config_path = Path(args.config)
    request = RoomLabelRequest.from_json(request_path.read_text())
    config = RoomSlmBackendConfig.from_json(config_path)

    baseline_proposal = rule_baseline(request)
    baseline_result = validate_room_label(baseline_proposal, request.context)
    backend = LlamaCppRoomLabelBackend(config)
    model_proposal = backend.infer(request)
    model_result = validate_room_label(model_proposal, request.context)

    root = Path(__file__).resolve().parents[1]
    rule_path = root / 'src/neusymnav/evaluation/room_labels.py'
    output = {
        'schema_version': 1,
        'request_id': request.request_id,
        'request_key': request.key.to_dict(),
        'source_manifest': dict(request.source_manifest),
        'context': {
            'context_hash': request.key.context_hash,
            'geometry_hash': request.key.geometry_hash,
            'object_count': request.context.distinct_object_count,
            'included_object_ids': [item.native_id for item in request.context.objects],
            'truncated': request.context.truncated,
            'inference_block_reason': request.inference_block_reason,
        },
        'rule': {
            'request_id': request.request_id,
            'version': RULE_BASELINE_VERSION,
            'rules_sha256': hashlib.sha256(rule_path.read_bytes()).hexdigest(),
            'proposal': baseline_proposal.to_dict(),
            'result': baseline_result.to_dict(),
        },
        'model': {
            'request_id': request.request_id,
            'model_id': config.model_id,
            'model_manifest_hash': config.model_manifest_hash,
            'model_sha256': config.model_sha256,
            'prompt_sha256': model_proposal.prompt_sha256,
            'schema_sha256': OUTPUT_SCHEMA_SHA256,
            'runtime_sha256': config.runtime_sha256,
            'proposal': model_proposal.to_dict(),
            'result': model_result.to_dict(),
            'metrics': dict(backend.last_metrics),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, sort_keys=True, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
