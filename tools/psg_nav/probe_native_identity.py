"""Replay one pinned RGB-D view while changing only its object category raster."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from neusymnav.backends.hydra.worker import _PipelineOwner
from tools.probe_hydra_detail import selected_prefix


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--expected-prefix", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--labels", type=int, nargs="+", required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_bytes())["scene_graph"]["hydra"]
    config_root = Path(config["config_root"])
    (frame, prefix), = selected_prefix(args.journal, 1)
    if prefix != args.expected_prefix:
        raise ValueError("first accepted prefix differs from the experiment lock")
    support = frame.labels == 53  # Television mask in the first pinned 00806 frame.
    if int(support.sum()) != 10025 or np.count_nonzero(frame.labels) != 10025:
        raise ValueError("expected the pinned 00806 television raster")

    args.output.mkdir(parents=True, exist_ok=False)
    owner = _PipelineOwner(config_root, args.output / "native")
    owner._initialize(frame)
    rows = []
    for index, label in enumerate(args.labels):
        raster = frame.labels.copy()
        raster[support] = label
        timestamp = frame.capture_monotonic_ns + index * 1_000_000_000
        start = perf_counter()
        if not owner.pipeline.step(timestamp, frame.world_t_body, frame.world_R_body_wxyz,
                                   frame.depth_m, raster, frame.rgb):
            raise RuntimeError(f"native step rejected for label {label}")
        elapsed_ms = (perf_counter() - start) * 1000
        graph = owner.pipeline.graph
        objects = []
        if graph.has_layer(2):
            for node in graph.get_layer(2).nodes:
                attrs = node.attributes
                box = attrs.bounding_box
                corners = np.asarray(box.corners()) if box.is_valid() else None
                objects.append({
                    "id": str(node.id),
                    "label": int(attrs.semantic_label),
                    "position": attrs.position.tolist(),
                    "active": bool(attrs.is_active),
                    "aabb": None if corners is None else [
                        corners.min(axis=0).tolist(), corners.max(axis=0).tolist(),
                    ],
                })
        rows.append({
            "step": index + 1,
            "label": label,
            "timestamp_ns": timestamp,
            "native_step_ms": elapsed_ms,
            "objects": sorted(objects, key=lambda obj: obj["id"]),
        })
    report = {
        "scope": "diagnostic intervention on the semantic raster of one recorded view",
        "config_sha256": sha256(args.config),
        "dataset_config_sha256": sha256(config_root / "datasets" / "neusymnav.yaml"),
        "labelspace_config_sha256": sha256(config_root / "label_spaces" / "neusymnav_label_space.yaml"),
        "source_journal_sha256": sha256(args.journal),
        "source_prefix_sha256": prefix,
        "source_frame_index": frame.source_key.frame_index,
        "native_binding_sha256": owner.native_binding_hash,
        "native_build_sha256": owner.binding_hash,
        "mask_pixels": int(support.sum()),
        "rows": rows,
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
