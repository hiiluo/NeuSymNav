# Rebuild RGB-D progress audit response — 2026-11-02

Reviewed `.runtime/rebuild-rgbd-progress-audit-20261102/report.md` and checked
the findings against current source, tests and plan R0–R8. Corrections below are
implemented in this workspace only. No subagent was called; Rebuild and 3DSG
trees were read-only.

## Findings and disposition

| Finding | Action |
| --- | --- |
| A. M5 accepted-map revision could be newer than latest M3 | `RoomPipelinePublication` now rejects it and requires `request_revision >= latest_map.revision`. |
| B. A failure/replay-required publication could appear fresh | Contract now requires stale regions whenever failure/replay is present. Worker responses must match the admitted frame metadata and prefix, next request/map revision, startup source/binary/config hashes; mismatch poisons the session and retains the old publication stale. |
| C. Old accepted M5 result had no retained M3 raster | Publication now carries `accepted_map` as a full immutable `RoomMapSnapshot` and validates episode/domain/clock/calibration/source order/resolution/source and worker/config pins. Session retains the exact prior map on M5 reject. UI adds Latest/Accepted M3 selection and auto-selects Rebuild view for this profile. |
| C. Rebuild M5 did not feed hierarchy/object membership | Added a distinct `source_region` node kind and Rebuild M5 membership projection. It reuses NeuSymNav canonical object IDs, tags map/M5 revisions and map domain, and computes membership only from accepted M5 polygons. Hierarchy edges retain their independent Rebuild map-domain revisions and survive schema serialization. Stale/replay/floor mismatch yields unavailable; M3 is never converted to `NavSnapshot` or a motion certificate. Publisher rejects hierarchy/source mismatch. |
| D. Profile range was 8 m without source evidence | Changed `RebuildRGBDConfig` and R6 runner default to 5 m, matching the audited `NativeRGBDMappingStage` default. This still does not prove parity with a live 3DSG caller. |
| D. Cumulative OctoMap node/voxel cap absent | Remains open. The pinned native API reports per-update key counts but no aggregate node count. The 10 GiB process-tree guard is sampled every 50 ms and is not a strict internal OctoMap cap. No fake cap was added. |
| R7 source oracle absent | Added `tools/compare_rebuild_rgbd_source_oracle.py`, with bounded synthetic and admitted-recording modes. A five-frame Habitat-recorded prefix compares adapter/session output with directly invoked pinned Rebuild M1–M5 stages. |
| R8 integrated live evidence absent | A bounded 30-second Habitat smoke now completes with fresh M3/M5 publication. R8 acceptance and A/B/C quality campaign remain open. |

## Verification

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests/test_room_pipeline_contract.py tests/test_rebuild_rgbd_input.py tests/test_rebuild_room_session.py tests/test_rebuild_room_display.py tests/test_room_hierarchy.py tests/test_hierarchy.py tests/test_runtime_scheduling.py tests/test_launcher.py tests/test_display_snapshot.py tests/test_ui_offscreen.py tests/test_room_debug_ui.py -q -rs` → **111 passed, exit 0**.
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python tools/compare_rebuild_rgbd_source_oracle.py --frames 3 --out runs/rebuild-rgbd-source-oracle-20261102-final` → **exit 0**, three sequential native frames; clean shutdown, 3/3 admitted and processed.
- Oracle compares M3 revision, shape, origin, resolution and states exactly; height-valid masks exactly and values at `atol=1e-7`; M5 persistent IDs and polygons exactly. Its report records 1 M5 region for each synthetic frame. Artifact: `runs/rebuild-rgbd-source-oracle-20261102-final/parity-report.json`.
- `bash -n tools/run_rebuild_rgbd_map_demo.sh` → exit 0.
- `bash tools/run_rebuild_rgbd_map_demo.sh 00805 --preflight` → exit 0, `ready: true`, `issues: []`, `native_runtime_validated: false`; generated config now uses 5 m max range. Hashes remain the pinned M2/M3, M4 and 50-file source closure.
- `git diff --check` → exit 0.

Final focused verification for the current checkpoint, including the source-
preserving replay and sensor calibration regression, supersedes the earlier
counts above. The final command was:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests/test_room_pipeline_contract.py tests/test_rebuild_rgbd_input.py tests/test_rebuild_room_session.py tests/test_rebuild_room_display.py tests/test_room_hierarchy.py tests/test_hierarchy.py tests/test_runtime_scheduling.py tests/test_launcher.py tests/test_display_snapshot.py tests/test_ui_offscreen.py tests/test_room_debug_ui.py tests/test_sensor_adapter.py tests/test_sensor_execution_metadata.py -q -rs
```

Result: **141 passed in 27.03s, exit 0**. A fresh 00805 preflight returned `ready: true`,
`issues: []`, `native_runtime_validated: false`, exit 0; the generated config
SHA-256 is `1b30db9cb8c6e1e7127b2aa1b6453ea985a049f3531005c6eab67c7787f97335`.
`bash -n tools/run_rebuild_rgbd_map_demo.sh` and `git diff --check` both exit 0.
No pass is inferred for native empty-episode behavior, absolute memory limits,
or the remaining R8 acceptance gates.

## M5 invalid-polygon failure and 180-second live follow-up

The user-run recording `runs/rebuild-rgbd-live-00805-240s/` reproduced a
133-vertex M5 ring with repeated/retraced edges: finite and nonzero-area, but
self-intersecting. Before correction, host-side rejection poisoned the RGB-D
session after M3/M5 state had advanced. The worker now validates the ring before
committing its M5 guard/tracker trial state. Invalid source geometry rejects
only M5, keeps the previous accepted pair stale, and leaves M3 publication
available; no polygon repair or geometry relaxation is applied.

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests/test_rebuild_room_worker.py tests/test_rebuild_room_session.py tests/test_rebuild_rgbd_input.py tests/test_room_pipeline_contract.py -q -rs` → **25 passed in 5.96s, exit 0**.

The 180-second visible run was launched outside the sandbox after an X11 probe
confirmed that the sandbox itself could not connect to display `:0`. Qt reached
`NEUSYMNAV_UI_READY`, displayed live publications with zero UI publication
drops, and shut down cleanly. The live worker stayed healthy for 29 processed
M3 revisions, but the native M5 output in this sequence had no valid polygon;
final state was `regions_stale=true`, `replay_required=false`, with no accepted
M5 pair. All 984 sensor frames were recorded. 462 of 491 room offers were
dropped by the bounded queue. The run summary is `incomplete`/exit 1 because the
resource sampler marked one missing process sample and one truncated sample;
all runtime workers shut down and no cap breach was reported. Artifact:
`runs/rebuild-rgbd-live-00805-180s-visible-20261102/`. This confirms the worker
failure is contained, not that the source M5 segmentation produced a valid room
for this sequence.

The same focused run includes hierarchy tests for fresh assigned membership,
stale unavailable membership, separate `source_region` nodes and rejection of a
hierarchy/source-publication domain mismatch.

The first oracle attempt failed because its comparator expected height masks in
unknown cells, contrary to the contract. That failed run is retained at
`runs/rebuild-rgbd-source-oracle-20261102-3f/`; the comparator now applies the
M3 unknown-height rule, and the final 3-frame run passes. This synthetic oracle
does not establish live sensor, historical-caller parameter parity, functional
room quality, or control behavior under load.

## Current plan state

R1 corrections are correctness-verified but still lack independent review. R5
accepted-pair retention/display and separate raw M5 hierarchy/object-membership
projection are implemented and correctness-verified; they do not alter the
control-map membership edge or stable-room source. R7 has this synthetic
source-oracle probe; broader recorded-input/caller parity remains. R8 and quality
comparison remain open.
The implementation-plan cross-check is P07 scheduling/failure independence,
P08 atomic display/source tags, and P09 explicit profile/preflight/export.

## Integrated runtime and recorded-source follow-up

`docs/results/rebuild-rgbd-live-smoke-2026-11-02.md` records three bounded
attempts. The first stopped before sensor startup at the inherited 10-second
deadline. The second completed capture but was incomplete because Qt could not
connect to display `:0`; it also exposed a calibration ID that changed with
robot pose. The R6 profile now allows 60 seconds for Habitat startup, and
`habitat_worker.py` hashes only the static mount at 1e-6 identity precision;
world pose arrays remain unmodified. Offscreen Qt was used in the headless
smoke.

Final 30-second run exit 0: 136 recorded sensor inputs, complete recording and
clean teardown. The room lane offered 67 frames, processed 7/7 admitted frames,
and rejected 60 at the bounded queue. Latest/accepted M3 revision 7 is paired
with fresh M5 revision 3 and one raw source region. Sampled RSS peak was
2,375,446,528 bytes, no sampled cap breach; resource proof remains sampled.
`native_runtime_validated` stays false and no quality score is claimed.

The first recorded replay attempt found a second R3 issue: the old wire stored
normalized depth with invalid samples replaced by NaN, while `geometry_sha256`
covered the original invalid values. The R2 wire now carries raw source depth,
source validity and optional mask provenance next to the sanitized M1 arrays;
replay reconstructs the exact source hash. Regression coverage verifies
finite invalid depth plus empty no-return masks. Five frames from the earlier
live wire (whose first five hashes reconstruct) then pass direct source oracle
parity; the last two old-format frames were excluded because raw invalid values
were not retained. A three-frame recorded synthetic replay also passes.

Follow-up verification after these changes:

- `tests/test_rebuild_rgbd_input.py tests/test_rebuild_room_session.py` →
  **15 passed**, exit 0.
- Synthetic recorded replay command is documented in the live smoke report;
  3/3 frames, direct M3/M5 parity, clean shutdown, exit 0.
- Five-frame Habitat prefix oracle → `parity_pass`, 5/5 replayed, clean
  shutdown, exact M3 states/origin/resolution/revisions and height masks,
  heights `atol=1e-7`, exact M5 IDs/polygons, exit 0.
- Updated R6 preflight → `ready: true`, `issues: []`, exit 0; config SHA
  `1b30db9cb8c6e1e7127b2aa1b6453ea985a049f3531005c6eab67c7787f97335`.
- Integrated Habitat command → exit 0, `outcome=completed`; `native_runtime_validated=false`.
- `git diff --check` → exit 0.

Open gates remain: independent R1 review, empty native episode, cumulative
OctoMap node/voxel cap, full seven-frame recorded parity with the new lossless
wire, historical caller parity, queue throughput policy, visible UI inspection,
and fixed A/B/C quality campaign. The successful smoke is not R8 acceptance.

The 180-second visible follow-up isolated the polygon source and added an
acceptance gate. The M4 response itself contained a weakly-simple ring (133
vertices, 127 unique, 6 retraced undirected edges, 18 non-adjacent intersections);
M5 copied the same ordered vertices. The pinned native contour predicate checks
only count, area and bounds, so the ring is emitted as M4 success. The M5
diagnosis report records exact hashes, source locations and what remains
uncertain about the internal DuDe bridge origin. `tools/check_rebuild_rgbd_demo_acceptance.py`
requires a completed run with a nonempty fresh M5 snapshot paired to latest M3
and validates every polygon. The visible 180-second run is rejected; the prior
30-second offscreen smoke passes the structural M5 gate with one valid region.
The offscreen run is not counted as the requested visible demonstration.
