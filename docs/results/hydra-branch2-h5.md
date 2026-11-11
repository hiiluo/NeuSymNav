# Hydra branch2 H5 — coordinator admission and navigation isolation

Date: 2026-11-04. H5 implementation is in isolated worktree `Kiet_branch2`.

## Implemented

- Added `scene_graph.backend` values `legacy` and `hydra`, with default `legacy`.
  Hydra profiles require pinned Hydra config/labelspace hashes, an explicit
  camera calibration, and a SHA-pinned worker interpreter/script/setup file.
  Configuration rejects Hydra alongside legacy region, Rebuild/M5, appearance,
  association and room-pipeline workers.
- Added a child launcher that sources the branch2 Hydra workspace setup inside
  the child process only. The launcher passes the native worker into
  `HydraSession`; the Python binding remains child-only.
- Added `HydraGraphRuntime`: it rasterizes the detector's existing batch, adapts
  the exact RGB-D observation/calibration, and calls nonblocking `session.offer`.
  It does not invoke a detector or allocate object identity.
- Added a separate Hydra branch in `Pipeline._graph_run`. Durable source and
  detector results are journaled before graph admission. Hydra initialization,
  offer, and close run on the graph thread without holding the coordinator lock.
  Legacy object owner, verification, region composer and Rebuild room factories
  are not constructed. Hydra failure is reported under `telemetry.hydra` and
  does not mark the shared navigation health failed or fall back to M5.

## Correctness verification

- RED/GREEN focused suite:
  `.venv/bin/python -m pytest tests/test_hydra_runtime.py tests/test_hydra_input.py tests/test_hydra_labels.py tests/test_hydra_session.py -q`
  — **25 passed**, exit 0.
- The coordinator fake-worker tests prove that a throwing Hydra offer leaves
  global health healthy, records incomplete Hydra shutdown, and does not call
  the legacy owner. A slow offer runs on the graph thread while `submit` returns
  under 100 ms. This is a CPU isolation test, not a live sensor benchmark.
- H0 navigation regression command (same 12 test files) — **135 passed**, exit
  0. All 11 source files under `src/neusymnav/navigation/` retain their H0
  SHA-256 hashes.
- `git diff --check` — exit 0.
- A broader configuration/launcher check ran 39 passed and 3 failed. The three
  failures are the existing shipped UI script SHA assertions for `baseline`,
  `geometry-only`, and `appearance`; they report the profile's expected hash
  `2e6cec…` versus current `ui_worker.py` hash `1b98b4…`. Hydra work did not edit
  the UI worker or those legacy profiles; these failures remain unresolved and
  are not counted as passing evidence.

## Evidence boundary

**Implemented:** selector, configuration exclusion, graph-thread admission and
graph-local failure reporting.

**Correctness-verified:** focused Hydra runtime/session/input suite and unchanged
H0 navigation/controller/MotionGuard regressions.

**Runtime-validated:** not yet at the NeuSymNav coordinator. H4's isolated native
child lifecycle/replay remains the only native worker runtime evidence. This
task did not validate a simulator launch, UI publication, or navigation while a
real Hydra child stalls/crashes; H6/H7 remain necessary.
