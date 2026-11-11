# RoomFinder cost validation (artifact tooling)

This builds a **separate** private Hydra DSO from the byte-identical locked stable
RoomFinder TU. Only atomic counters, steady-clock RAII scopes and reset/read C ABI
are injected. It never overwrites the installed or stable runtime library.

From the Kiet_branch2 root:

```bash
python3 tools/native/hydra_room_stability_benchmark/build.py
```

Locked build/recording inputs, generated source/diff, commands, logs and timing DSO
are under `runs/hydra-objectnav/B1-stability-validation-20261107/benchmark-harness/`.
`replay_benchmark.py` in that directory accepts `--scene short60|long300`,
`--policy enabled|disabled`, `--output-dir NEW_DIRECTORY_UNDER_HARNESS_ROOT`.
Run through `src/neusymnav/backends/hydra/child.sh .runtime/hydra_ws/env.sh
.runtime/hydra_ws/.venv/bin/python` with OMP/BLAS/MKL thread counts1. The harness
uses the locked merge-.25 dataset (compression.5/component3/room10), loads and
configures the same timed DSO before binding imports, checks accepted source
payload/prefix hashes and unique mapped DSO, and records honest independent build
provenance instead of the production worker's legacy binding-only metadata.

C ABI: `void nsn_hydra_room_timing_reset()` and
`const char* nsn_hydra_room_timing_read()` return cumulative completed-call ns/counts.
`findRooms` includes `getBestComponents`: **do not sum them**. Whole-step wall/CPU
metrics cover production `process_frame`, including first-frame initialization and
graph summary. Periodic RSS includes input deserialization between steps and is
paused during diagnostic exports; sampled peak is not an absolute/process-tree peak.

The fixed OFF/ON/OFF/ON run controller is `run_abab.py` at the validation artifact
root. Existing output directories are rejected. Run only one benchmark at a time;
do not rebuild/change sources or run detector/simulator/tests during measurement.
See `docs/results/hydra-stability-validation-2026-11-07.md` for results/limitations.
The wrong-default-profile smoke is preserved as ineligible; it is not primary data.
