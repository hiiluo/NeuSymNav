#!/usr/bin/env python3
"""Make review images and a compact acceptance report from a completed run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


COLORS = {
    "building": (124, 150, 255), "floor": (76, 198, 180),
    "region": (77, 174, 122), "source_region": (246, 181, 62),
    "place": (125, 180, 245), "object": (218, 167, 255),
}
LAYER = {"building": 0, "floor": 1, "region": 2, "source_region": 2, "place": 3, "object": 4}


def room_map_image(publication, path: Path) -> None:
    room_map = publication.latest_map
    states = room_map.states
    h, w = states.shape
    rgb = np.empty((h, w, 3), dtype=np.uint8)
    rgb[states == -1] = (68, 82, 101)
    rgb[states == 0] = (58, 145, 111)
    rgb[states == 100] = (245, 91, 79)
    canvas = Image.fromarray(rgb[::-1].copy(), "RGB")
    draw = ImageDraw.Draw(canvas)
    overlays = 0
    if (publication.regions is not None and not publication.regions_stale
            and publication.accepted_map_revision == room_map.revision
            and publication.regions.source_map_revision == room_map.revision):
        ox, oy = room_map.origin_xy
        res = room_map.resolution_m
        for region in publication.regions.regions.values():
            pts = []
            for x, y in region.polygon:
                px = (float(x) - ox) / res
                py = h - 1 - (float(y) - oy) / res
                pts.append((px, py))
            if len(pts) >= 3:
                draw.line(pts + [pts[0]], fill=(255, 201, 63), width=2)
                overlays += 1
    header = f"M3 r{room_map.revision} | M5 r{publication.m5_revision} | regions drawn {overlays}"
    draw.rectangle((0, 0, min(w, len(header) * 7 + 12), 20), fill=(15, 24, 38))
    draw.text((6, 5), header, fill=(245, 245, 245), font=ImageFont.load_default())
    scale = min(1.0, 1400 / max(w, h))
    if scale < 1:
        canvas = canvas.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.NEAREST)
    canvas.save(path)


def hierarchy_image(snapshot, path: Path, max_nodes: int = 300) -> dict:
    nodes = sorted(snapshot.nodes.values(), key=lambda n: (LAYER[n.kind], n.kind, n.node_id))
    omitted = max(0, len(nodes) - max_nodes)
    nodes = nodes[:max_nodes]
    included = {node.node_id for node in nodes}
    layers = {i: [node for node in nodes if LAYER[node.kind] == i] for i in range(5)}
    width, row_h, top, margin_x = 1700, 76, 70, 180
    max_rows = max(1, max(map(len, layers.values())))
    height = max(560, top + max_rows * row_h + 80)
    image = Image.new("RGB", (width, height), (12, 20, 34))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    coords = {}
    layer_names = ["building", "floor", "region/source region", "place", "object"]
    for layer, members in layers.items():
        x = margin_x + layer * ((width - 2 * margin_x) // 4)
        draw.text((x, 38), layer_names[layer], fill=(190, 211, 237), font=font)
        for index, node in enumerate(members):
            y = top + index * row_h
            coords[node.node_id] = (x, y)
    for edge in snapshot.edges:
        if edge.source_id not in included or edge.target_id not in included:
            continue
        x1, y1 = coords[edge.source_id]
        x2, y2 = coords[edge.target_id]
        color = (78, 190, 170) if edge.status == "assigned" else (232, 175, 65) if edge.status == "ambiguous" else (105, 120, 141)
        draw.line((x1 + 10, y1 + 13, x2 + 10, y2 + 13), fill=color, width=2)
    for node in nodes:
        x, y = coords[node.node_id]
        color = COLORS[node.kind]
        draw.rounded_rectangle((x, y, x + 310, y + 28), radius=5, fill=(25, 37, 55), outline=color, width=2)
        attrs = node.attributes
        label = str(attrs.get("category") or attrs.get("raw_region_id") or attrs.get("floor_id") or node.node_id)
        label = f"{node.kind}: {label}"[:48]
        draw.text((x + 8, y + 8), label, fill=(239, 243, 250), font=font)
    footer = f"Hierarchy r{snapshot.revision} | objects r{snapshot.object_revision} | map r{snapshot.map_revision} | nodes {len(snapshot.nodes)}"
    if omitted:
        footer += f" | image shows first {max_nodes}; {omitted} omitted"
    draw.text((24, height - 28), footer, fill=(160, 185, 215), font=font)
    image.save(path)
    return {"hierarchy_revision": snapshot.revision, "nodes": len(snapshot.nodes),
            "edges": len(snapshot.edges), "nodes_rendered": len(nodes), "nodes_omitted_from_image": omitted}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_ROOT,
                        help="NeuSymNav checkout containing src/ and tools/")
    args = parser.parse_args()
    project_root = args.project_root.expanduser().resolve(strict=True)
    for import_root in (project_root, project_root / "src"):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))
    from neusymnav.contracts.serialization import loads
    from tools.check_rebuild_rgbd_demo_acceptance import evaluate_run
    run_dir = args.run_dir.resolve(strict=True)
    output = args.output.resolve() if args.output else run_dir / "review"
    output.mkdir(parents=True, exist_ok=True)
    acceptance = evaluate_run(run_dir)
    result = {"acceptance": acceptance}
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text())
    result["run"] = {
        "outcome": summary.get("outcome"),
        "runtime_clean_shutdown": summary.get("runtime", {}).get("clean_shutdown"),
        "room_pipeline_revisions": summary.get("room_pipeline_revisions"),
        "room_metrics": summary.get("runtime", {}).get("metrics", {}).get("room_pipeline"),
    }
    completeness_path = run_dir / "room-pipeline/session/completeness.json"
    if completeness_path.is_file():
        completeness = json.loads(completeness_path.read_text())
        result["room_session"] = {key: completeness.get(key) for key in (
            "runtime_complete", "recording_complete", "admitted_frames", "recorded_frames",
            "processed_frames", "process_tree_rss_peak_bytes", "failure_reason", "incomplete_reason")}
    room_path = run_dir / "room-pipeline.json"
    if room_path.is_file():
        publication = loads(room_path.read_text())
        room_map_image(publication, output / "rebuild_m3_m5.png")
        result["rebuild_map"] = {
            "latest_m3_revision": publication.latest_map.revision,
            "accepted_m3_revision": publication.accepted_map_revision,
            "m5_revision": publication.m5_revision,
            "regions_stale": publication.regions_stale,
            "region_count": 0 if publication.regions is None else len(publication.regions.regions),
        }
    hierarchy_path = run_dir / "hierarchy.json"
    if hierarchy_path.is_file():
        hierarchy = loads(hierarchy_path.read_text())
        result["hierarchy_image"] = hierarchy_image(hierarchy, output / "hierarchy_graph.png")
    (output / "review.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    print(f"review_artifacts={output}")
    return 0 if acceptance["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
