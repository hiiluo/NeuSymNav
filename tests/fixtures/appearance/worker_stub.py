"""Small protocol peer for bounded-timeout, crash, and spoof tests."""
from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import struct
import sys
import time


def read_exact(stream, size):
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream):
    size = struct.unpack("!I", read_exact(stream, 4))[0]
    return json.loads(read_exact(stream, size))


def write_frame(stream, payload):
    data = json.dumps(payload, separators=(",", ":")).encode()
    stream.write(struct.pack("!I", len(data)) + data)
    stream.flush()


def vector_payload():
    vector = struct.pack("<512f", 1.0, *([0.0] * 511))
    return base64.b64encode(vector).decode("ascii")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True)
    parser.add_argument("--child-pid-file")
    args = parser.parse_args()
    mode = args.mode
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    if mode == "startup_stall":
        time.sleep(30)
        return
    while True:
        try:
            request = read_frame(stdin)
        except EOFError:
            return
        if request.get("op") == "close":
            return
        if request.get("op") == "initialize":
            config = request["config"]
            metadata = {
                "model_name": config["model_name"],
                "checkpoint_sha256": config["checkpoint_sha256"],
                "pretrained": config["pretrained"],
                "state_dict_strict": config["state_dict_strict"],
                "preprocessing_id": config["preprocessing_id"],
                "crop_recipe_id": config["crop_recipe_id"],
                "transform_repr_sha256": ("b" if mode == "transform" else "a") * 64,
                "runtime": {"python": "fixture", "python_implementation": "fixture",
                            "open_clip_torch": "fixture", "torch": "fixture",
                            "torchvision": "fixture", "Pillow": "fixture", "numpy": "fixture"},
                "feature_dimension": config["feature_dimension"],
            }
            write_frame(stdout, {"op": "ready", "metadata": metadata})
            if mode in ("write_stall", "write_stall_child"):
                # Advertise readiness, then deliberately stop consuming stdin.
                # A subsequent large host request fills the child pipe.
                if mode == "write_stall_child":
                    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
                    if args.child_pid_file:
                        with open(args.child_pid_file, "w", encoding="ascii") as marker:
                            marker.write(str(child.pid))
                time.sleep(30)
                return
            continue
        if request.get("op") != "encode":
            write_frame(stdout, {"op": "error", "reason": "unknown operation"})
            continue
        if mode == "crash":
            os._exit(17)
        if mode == "timeout":
            time.sleep(3)
        source = dict(request["source"])
        geometry_hash = request["geometry_hash"]
        if mode == "spoof":
            source["frame_index"] += 1
        if mode == "spoof_hash":
            geometry_hash = "0" * 64
        detections = request["detections"]
        status = {}
        features = {}
        for index, detection in enumerate(detections):
            detection_id = detection["detection_id"]
            if mode == "partial" and index:
                status[detection_id] = {"status": "missing", "reason": "fixture_missing"}
            else:
                status[detection_id] = {"status": "available"}
                features[detection_id] = vector_payload()
        write_frame(stdout, {"op": "features", "source": source,
                             "geometry_hash": geometry_hash, "features": features,
                             "status": status})


if __name__ == "__main__":
    main()
