# Local demo environment — 2026-10-30

User requested preparing all dependencies before further code development.
This checkout is on Ubuntu 24.04 / Intel Raptor Lake-P UHD, not the NVIDIA
RTX3060 development host described in historical reports. Default sandbox hides
`/dev/dri`; approved desktop execution exposes Intel `renderD128`. Actual native
render reports Mesa Intel Graphics / OpenGL 4.6 / Mesa 25.2.8.

## Run

From the NeuSymNav directory in a desktop terminal:

```sh
bash tools/run_local_demo.sh --preflight
bash tools/run_local_demo.sh 45
```

Optional second argument: a new output directory. The UI starts in a separate
process. Model initialization and shutdown add wall time beyond the requested
capture duration. The local config is `configs/demo.local.json` (ignored).
Historical `run_gpu_demo.sh` configurations belong to a different machine.

## Prepared dependencies and assets

- `.venv`: Python 3.12.3, editable NeuSymNav, development dependencies, NumPy
  1.26.4, SciPy 1.17.1, Numba 0.61.2 / llvmlite 0.44.0, PyQt5 5.15.11.
- `.runtime/detector26`: Python 3.12.3, Torch 2.7.1+cpu, torchvision 0.22.1+cpu,
  Ultralytics 8.4.24, NumPy 1.26.4, CLIP from pinned Ultralytics commit
  `7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40`. No CUDA package needed.
- Sensor reuses `/home/kiettran05/miniconda3/envs/habitat/bin/python` read-only:
  Python 3.9 / Habitat-Sim 0.3.3; all three control-source pins match production
  qualification. `gpu_device_id=-1` selects Mesa EGL without NVIDIA matching.
- `local-assets/models/`: official YOLOE-26m and MobileCLIP2 weights downloaded
  from [Ultralytics assets v8.4.0](https://github.com/ultralytics/assets/releases/tag/v8.4.0).
  Both SHA256 values match the project's previously pinned recipes. Prompt setup
  uses the explicit local encoder and tokenizer; no runtime auto-install enabled.
  See [upstream YOLOE documentation](https://docs.ultralytics.com/models/yoloe/).
- `local-assets/scenes/hm3d-00802/` and `local-assets/native/`: copied from the
  available local 3DSG handoff bundle, keeping its native libraries/notices.
  Native worker protocol and extended unknown-boundary preprocessing probe pass.
  No source repository is used as a Python import root.
- Actual downward-depth floor measurement: 1,200 samples over three captures;
  median -0.0045672655 m, p05/p95 -0.0052400/-0.0038948 m. RGB-D primary render
  verified visually. Calibration and asset/interpreter/script hashes are pinned
  in the local config. Map remains empty initially; navmesh is not map evidence.
- Local CPU mapper, primary RGB-D 640×480, navigation depth 240×180, appearance
  off; requested primary/navigation cadence 5/10 Hz. Requested rates are not
  achieved-rate claims. Safety TTL/footprint/unknown gates and source unchanged.

Exact package snapshots, sensor Conda explicit URLs, calibration, model download
logs, local copy manifest and machine-readable result are under
`.runtime/setup-20261030/`. These ignored local dependencies are not included
by a fresh Git clone.

## Evidence and limits

- Preflight: ready true, issues empty, exit 0 (`preflight.json`).
- Native DuDe request/preprocessing probe: exit 0 (`native-probe.json`).
- Initial 20 s smoke: exit 0/completed, actual Qt/Intel RGB-D/YOLOE and 12 objects;
  modern Habitat source's agent hash failed planar qualification, blocking motion.
  Retained under `runs/setup-demo-intel-20261030/`.
- Final 45 s smoke with stock Habitat: exit 0/completed, 291 frames, 12 objects,
  139 executed control results, 0.4064409 m observed body translation lower bound;
  clean shutdown, measurement completion true, zero observer errors/cap breaches.
  Evidence `runs/setup-demo-intel-stock-20261030/`, `demo45.log`, `result.json`.
- Aggregate actuation completeness remains false: one accepted command lacks
  retained proof. No accepted region/membership appeared during this short run.
  This confirms a functioning local demo, not full P10 or realtime acceptance.
- Initial CPU suite: 1 failed, 1924 passed, 1 skipped, 3 deselected; exit 1.
  The 20 ms fixture test `test_actual_cpu_worker_ack_binds_to_real_launcher_attempt_provenance`
  failed when no final decoded source was registered. Isolated rerun passed
  (1 pass/exit 0); grouped proof/wiring rerun failed (1 fail/51 pass/exit 1).
  All evidence retained; no source/test change to mask this timing-sensitive check.

A preliminary import of an external editable Habitat installation unexpectedly
triggered its automatic native rebuild. That process group was stopped; later
probes disabled rebuild. A project-local copy of that modern CPU build remains
for diagnostics and is not selected. No source pipeline, safety contract, model
training, driver install, commit or publication was performed.

Final idle CPU rerun: **1924 passed, 1 skipped, 3 deselected, 1 failed**, exit 1
in 124.26 s (`final-cpu-suite.log`). The earlier execution-proof test passed in
this run; the failure moved to
`test_pair_preserves_distinct_frame_indices_calibration_and_single_source_mapping`,
which timed out waiting three seconds for two commits. This is unresolved
scheduling-sensitive test evidence, not a fully green correctness gate.
Core/UI and detector dependency checks both pass (`uv pip check`, exit 0).
`bash -n tools/run_local_demo.sh`, final config/smoke SHA binding and
`git diff --check` pass, exit 0. Production source and tests remain unchanged.

The final capture-pair failure passed when rerun alone: 1 passed/exit 0 in
0.87 s (`capture-pair-rerun.log`). Both full-suite failures are retained;
isolated passes do not promote the full-suite gate to green.
