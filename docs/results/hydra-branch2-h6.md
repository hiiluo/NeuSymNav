# Hydra branch2 H6 — native graph projection and export

Date: 2026-11-04. Work is in the isolated `Kiet_branch2` worktree.

## Implemented

- Added a bounded schema-1 projection for native Spark-DSG node IDs, layer IDs,
  native parent/topology edges, graph revision, selected source, and input-prefix
  provenance. Dangling edges are discarded and stale/failure/replay-required
  status remains explicit.
- Added the graph summary to accepted worker replies and session snapshots. The
  worker extracts native graph layers after accepted steps; summary payloads are
  bounded to 16 MiB. The coordinator publishes a separate Hydra projection and
  an explicit `unavailable_hydra_backend` state for legacy M3/M5 hierarchy
  consumers. Navigation snapshots remain separately identified as NavMap data.
- Added Hydra graph rendering, layer filtering, selectable native nodes, and
  selected-node provenance in the desktop UI. DTO registration includes a
  backward default for older publications.
- `HydraGraphRuntime.close()` verifies native graph size and SHA, pairs selected
  frame journal records with accepted results, writes a bounded JSON export
  manifest atomically, and marks incomplete or inconsistent exports incomplete.

## Correctness verification

- RED/GREEN and integration command:
  `.venv/bin/python -m pytest tests/test_hydra_runtime.py tests/test_hydra_projection.py tests/test_hydra_session.py tests/test_hydra_input.py tests/test_hydra_labels.py tests/test_ui_encoding_budget.py tests/test_display_snapshot.py -q`
  — **43 passed**, exit 0.
- Tests cover graph namespace/provenance, missing nodes and dangling edges,
  stale state, publication/DTO round-trip, offscreen layer filter and selection,
  exact accepted-input hashes, verified native-asset hashes, and incomplete export.
- Existing H4 native artifact was checked through the new exporter. The exported
  manifest is
  `.runtime/hydra_ws/artifacts/h4-worker-smoke/native-output/hydra-export-manifest.json`,
  SHA-256 `61a4f89f533bc04df89143e4b7128bfc084ef3577d30ac3c64d4e17c20b3d22b`.
  Its graph asset matches SHA-256
  `c551766bb50ae2421b9825c2cf5c42471938e28fdf3bc7f7abac4784c1029979` and the
  selected input prefix matches the H4 native save/reload/replay evidence in the
  H4 report. The fixture contains no object/place/room nodes; H3 native fixtures
  separately exercise those layers.
- `git diff --check` is part of final verification and is recorded below.
- Final full CPU suite after completing H7 checker and preflight-probe tests:
  **2416 passed, 10 skipped, 3 failed**, exit 1 in 186.54 s. All three
  failures are the pre-existing `baseline`, `geometry-only`, and `appearance`
  UI worker checksum assertions (`expected 2e6cec…`, current script
  `310ae171…`). The H6 work does not change those shipped profile pins; see H5.
- The focused final command including the corrected room-pipeline fixture,
  H7 checker, and all H6/H5/H2–H4 UI tests: **54 passed**, exit 0 in 6.26 s. The exact H0
  navigation/controller/MotionGuard command: **135 passed**, exit 0 in 8.82 s.
- `git diff --check`: exit 0.

## Evidence boundary

**Implemented:** graph summary, UI projection and selection, export manifest.

**Correctness-verified:** focused CPU tests and exact manifest verification of an
existing native Spark-DSG artifact; H4 separately proves Spark-DSG reload.

**Runtime-validated:** graph projection was not connected to a live NeuSymNav
coordinator or visible desktop session. `DISPLAY=:0` is set, but `xdpyinfo`
exited 1 because no X server is available. The display test ran offscreen.
The UI currently renders native graph nodes/topology and does not render the
native mesh/cloud asset. Live selection of a real room with its place membership
and objects is not demonstrated.

## Commands and artifacts

- Focused H6/H5/H2–H4/UI test command above: exit 0.
- H4 native graph, journal and native reload evidence: see
  [H4 report](hydra-branch2-h4.md).
- Export manifest: `.runtime/hydra_ws/artifacts/h4-worker-smoke/native-output/`.
- Full-suite stdout was not persisted as a separate log file.

