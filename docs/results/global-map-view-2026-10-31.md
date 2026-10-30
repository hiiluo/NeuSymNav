# Full accumulated occupancy view — 2026-10-31

User correction: previous wheel/pan controls only transformed the local navigation
window around the robot. Zooming out could not show absent map data. The UI now
receives a distinct accumulated measured occupancy overview from the mapper.
The navigation/room snapshot window is unchanged.

## Implementation

Every integration classifies the canonical dirty cell evidence using the same
planar, body-height and floor-support rules as NavSnapshot. Copy-on-write 2D
overview tiles retain history independently of active 3D-tile eviction. Old
published references remain immutable. Corrections can replace free/occupied
cells with unknown; unknown-only tiles do not consume the tile budget. Reset
clears the history. A lost update keeps its old source timestamp and marks future
history incomplete until reset, without failing control.

The tile state budget is 4096 tiles (16MiB at the selected64×64 tile size).
The UI publication worker builds a raster of at most1,000,000 cells over the
whole known extent, coarsening by integer powers of two if required. Occupied
wins; a coarser free cell requires all underlying cells to be free. Sparse gaps
and partially unknown coarse cells remain unknown. Bounds do not recenter or
crop to the robot to meet the budget. The caption exposes resolution and an
INCOMPLETE flag if the history budget/update contract was exceeded.

MapOverview is a distinct display-only DTO with source NavSnapshot, geometry,
readonly state raster and versioned policy. It never enters control, planning or
room decomposition. Pipeline publishes immutable tile pointers; dense assembly
and serialization run on the UI lane. Global history is read before latest local
navigation; an older overview may coexist with a newer live robot pose with
separate ages, while future/backward/cross-context map sources are rejected.
Legacy publications without overview remain readable and display their local map.

The map widget uses global bounds for raster, world coordinates and overlays.
**Toàn bộ map** (or double-click) fits the accumulated extent. **Về robot** centers
once at local scale. Wheel zoom and dragging preserve a chosen world area as the
robot moves; they do not enable continuous follow. A reviewed edge case where
wheel-up after robot focus could zoom out on a very large global map was
reproduced RED and corrected with monotonic bounds including local focus scale.

## Verification evidence

Evidence root `.runtime/global-map-view-20261031/`.

- Mapping focused20passed/exit0: four real integrations compared to canonical
  dirty cells, movement beyond local windows, eviction, reset, corrections,
  immutable history, unknown coarsening, tile/output budgets and failure source age.
- UI RED3fail/exit1; integrated focused139passed/19.76s/exit0 across14 mapper,
  global-view, local-map, transport, publication and navigation/UI test files.
- Large-map Focusrobot wheel-up RED1fail/exit1, then corrected and verified.
- Preflight ready=true/issues=[]/exit0. Maintained18 UI script checksums updated.
- Independent probes cover failed-provider retained source/time and growing age,
  plus Event-blocked dense assembly leaving graph handoff/local nav independent.
- Whole-suite result and final independent acceptance are appended below.

## Native bounded run

Ran once with the frozen selected GPU CG+Visual profile:

```sh
bash tools/run_map_demo.sh 00861 45 runs/demo-global-map-view-45s-20261031
```

45s requested; wrapper56.38s, exit1, outcome incomplete. Error null, no failed
workers,794rawframes,9committed object batches, no pending work; UI clean shutdown,
0dropped publications/0publication errors. The resource monitor had1RSS read error,
so its completion gate fails; do not describe this run as fully successful or
P10-validated. All392 functional source/config/test/patch pins remained unchanged.

There are46 sampled UI publications,0parse errors, all overview.complete=true.
The final global raster is101×135 at5cm: **6.75×5.05m**, against local81×81:
**4.05×4.05m**. The initial global extent66×119 grows during the run. Final global
known cells4769. Independent artifact audit found1126known cells outside the final
local window (789free/337occupied);267known cells from the first sampled global
publication outside the final local window remain known. This verifies retained
measured history, rather than merely a larger unknown border.

Actual archived publication rendered through Qt, exit0. Inspected dedicated
1000×650 MapWidget images `native-whole-map.png`, `native-robot-focus.png`, plus
`native-whole-map-dashboard.png`. `native-render-audit.json` records bounds,
resolution, source revision, complete status and retained point-cloud/Object
positions. These are archived runtime data; screenshot source age includes
shutdown. No semantic room accuracy or live GUI performance claim follows.

## Final integration audit

Initial full CPU attempt:2209passed/2failed/2skipped/9deselected,122.77s. Retained
`full-cpu.log`. The two failures were resolved:

- Added buttons initially consumed vertical space needed by the existing graph
  splitter gesture. Buttons now share the existing robot legend row; original
  minimum map height and graph splitter assertions are retained.
- The projection-reuse test intercepted every NumPy column_stack call, including
  new2-column overview index grouping. It now checks homogeneous3-column pixel
  ray reconstruction and explicitly exercises the legacy path to prove the probe
  still detects the unwanted original reconstruction. Mapping logic is unchanged.

The two affected suites pass17tests, exit0,1.46s (`final-regressions.log`). A final
frozen full CPU suite is retained separately; result appended once completed.
Only the desktop control-row layout and that test changed after the native run;
all mapping/transport/data-path sources remain identical to the measured run.
Final native Qt rendering after the layout adjustment exits0
(`native-render-final.log`).

Independent scoped ACCEPT:59tests and native history/provenance audit exit0,
`review/review.md`/`native-audit.json`. Confirmed whole-map extent, retained measured
cells outside local window, source/robot binding, conservative history and both
actual render modes. Native overall remains INCOMPLETE/RSS1; no P10, semantic room
accuracy, global room membership or controlled performance claim. No sibling
edit, install/download/training, commit or push.

## Final frozen gate

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -m pytest tests -q -rs -m 'not native'
```

Exit0: **2211passed,2skipped,9deselected**,121.33s; `full-cpu-final.log`.
Skips remain optional Numba dispatch and explicit GPU-raycast test gate. The
post-correction independent review also ran22tests/exit0/1.59s and kept scoped
ACCEPT. `final-source-hashes.json` pins392files; `post-native-deltas.json` records
only the reviewed layout/test changes. Final diffcheck0. No unresolved finding
in this display/overview scope. No commit or push.

Restart the GPU demo to load the new mapper/UI:

```sh
bash tools/run_map_demo.sh 00861 300
```
