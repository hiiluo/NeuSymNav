#!/usr/bin/env python3
"""Check the timing-only C ABI on a private Hydra library."""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("library", type=Path)
    parser.add_argument("--policy", choices=("enabled", "disabled"), required=True)
    args = parser.parse_args()

    library = ctypes.CDLL(str(args.library.resolve(strict=True)), mode=ctypes.RTLD_GLOBAL)
    configure = library.nsn_room_stability_configure
    configure.argtypes = [ctypes.c_char_p]
    configure.restype = ctypes.c_int
    policy = {"enabled": args.policy == "enabled"}
    if configure(json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()) != 0:
        raise AssertionError("existing room-stability configure ABI rejected explicit policy")

    reset = library.nsn_hydra_room_timing_reset
    reset.argtypes = []
    reset.restype = None
    read = library.nsn_hydra_room_timing_read
    read.argtypes = []
    read.restype = ctypes.c_char_p
    reset()
    raw = read()
    if raw is None:
        raise AssertionError("timing read ABI returned null")
    payload = json.loads(raw.decode("utf-8"))
    expected = {"getBestComponents", "findRooms"}
    if payload.get("schema_version") != 1 or set(payload) != expected | {"schema_version"}:
        raise AssertionError(f"unexpected timing ABI JSON shape: {payload!r}")
    for name in sorted(expected):
        counters = payload[name]
        if set(counters) != {"calls", "nanoseconds"}:
            raise AssertionError(f"unexpected {name} counter shape: {counters!r}")
        if counters != {"calls": 0, "nanoseconds": 0}:
            raise AssertionError(f"reset did not clear {name}: {counters!r}")
    print(json.dumps({"policy": args.policy, "timing": payload}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
