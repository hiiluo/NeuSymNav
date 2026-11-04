#!/usr/bin/env python3
"""Require a fresh, valid M5 region before calling an RGB-D demo successful."""
from __future__ import annotations

import argparse
import base64
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from neusymnav.regions.geometry import valid_ring


def _decode_polygon(value):
    if not isinstance(value, dict) or set(value) != {"ndarray"}:
        raise ValueError("polygon is not a serialized ndarray")
    encoded = value["ndarray"]
    if not isinstance(encoded, dict) or set(encoded) != {"data", "dtype", "shape"}:
        raise ValueError("polygon ndarray fields are malformed")
    dtype = np.dtype(encoded["dtype"])
    shape = encoded["shape"]
    if dtype.str not in {"<f8", "<f4"} or not isinstance(shape, list) or len(shape) != 2:
        raise ValueError("polygon ndarray dtype or shape is unsupported")
    if (any(type(size) is not int or size <= 0 for size in shape)
            or shape[1] != 2 or shape[0] > 1024):
        raise ValueError("polygon ndarray dimensions exceed the ring contract")
    raw = base64.b64decode(encoded["data"], validate=True)
    if len(raw) != math.prod(shape) * dtype.itemsize:
        raise ValueError("polygon ndarray byte length mismatch")
    polygon = np.frombuffer(raw, dtype=dtype).reshape(shape)
    if not np.isfinite(polygon).all():
        raise ValueError("polygon contains non-finite coordinates")
    return tuple(tuple(float(value) for value in point) for point in polygon)


def evaluate_run(run_dir: str | Path) -> dict:
    root = Path(run_dir).expanduser().resolve(strict=True)
    reasons: list[str] = []
    try:
        summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        room_wire = json.loads((root / "room-pipeline.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"accepted": False, "run_dir": str(root), "reasons": [f"run artifacts unreadable: {exc}"]}

    if summary.get("outcome") != "completed":
        reasons.append(f"run outcome is {summary.get('outcome')!r}, not 'completed'")
    if summary.get("recording_certificate", {}).get("complete") is not True:
        reasons.append("sensor recording is incomplete")
    runtime = summary.get("runtime", {})
    if runtime.get("clean_shutdown") is not True:
        reasons.append("runtime did not shut down cleanly")
    if runtime.get("room_pipeline_failed") is not None or runtime.get("replay_required") is True:
        reasons.append("room pipeline failed or requires replay")
    if summary.get("cleanup", {}).get("ui", {}).get("status", {}).get("failed") is not None:
        reasons.append("UI process failed")
    if summary.get("export_issue") is not None:
        reasons.append(f"export issue: {summary['export_issue']}")

    payload = room_wire.get("payload", {}) if isinstance(room_wire, dict) else {}
    fields = payload.get("fields", {}) if isinstance(payload, dict) else {}
    latest = fields.get("latest_map", {})
    accepted = fields.get("accepted_map", {})
    regions = fields.get("regions", {})
    if not isinstance(latest, dict) or not isinstance(latest.get("fields"), dict):
        reasons.append("latest M3 map is missing")
        latest_fields = {}
    else:
        latest_fields = latest["fields"]
    accepted_fields = accepted.get("fields", {}) if isinstance(accepted, dict) else {}
    region_fields = regions.get("fields", {}) if isinstance(regions, dict) else {}
    accepted_revision = fields.get("accepted_map_revision")
    latest_revision = latest_fields.get("revision")
    if accepted_revision is None or accepted_fields.get("revision") != accepted_revision:
        reasons.append("accepted M3 snapshot is missing or revision-mismatched")
    if accepted_revision != latest_revision:
        reasons.append("final M5 source is not paired with the latest M3 revision")
    if fields.get("regions_stale") is not False or region_fields.get("stale") is not False:
        reasons.append("final M5 regions are stale or unavailable")
    if region_fields.get("source_map_revision") != accepted_revision:
        reasons.append("M5 source map revision differs from its accepted M3")

    region_values = region_fields.get("regions", {}).get("mapping", {})
    if not isinstance(region_values, dict) or not region_values:
        reasons.append("final M5 snapshot contains no region")
        region_values = {}
    valid_count = 0
    for region_id, region in region_values.items():
        try:
            polygon = _decode_polygon(region.get("fields", {}).get("polygon"))
            if not valid_ring(polygon):
                raise ValueError("ring is not simple and nonzero")
            valid_count += 1
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            reasons.append(f"M5 region {region_id!r} is invalid: {exc}")

    return {
        "accepted": not reasons,
        "run_dir": str(root),
        "outcome": summary.get("outcome"),
        "latest_m3_revision": latest_revision,
        "accepted_m3_revision": accepted_revision,
        "m5_revision": region_fields.get("revision"),
        "valid_m5_regions": valid_count,
        "reasons": reasons,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    result = evaluate_run(args.run_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
