# Room graph and occupancy display — 2026-10-31

User-authorized scope: preserve measured point cloud, show only Floor→Room→Object,
track room centers, distinguish live occupancy from graph history, and correct
demonstrated room geometry defects. No training, downloads, sibling edits or push.

## Implemented

The three UI views project canonical hierarchy into Floor/Room/Object only.
Internal Building/Place records and canonical IDs remain available to nonvisual
consumers. Object nodes keep exact measured XYZ and bounds. Room XY follows the
accepted polygon's area centroid, with a bounded interior-clearance fallback for
concave geometry. Floor XY is area-weighted over its own rooms, including rooms
hidden by the node cap. Only Room/Floor display Z is raised. Parent lines require
assigned, consistent source-supported membership; unavailable objects remain
unassigned. Selection does not reintroduce hidden node kinds.

A dedicated bounded publication thread polls immutable latest navigation and
publishes at up to5Hz independently of graph/detector work. Before the first
canonical graph it can show an explicitly empty display-only hierarchy. The
hierarchy-pinned map remains separate for room relations. Robot/source/time/clock
must match the displayed map; old room outlines are labeled STALE. RGB, detector,
map and historical cloud retain separate source ages. This improves display
cadence, not sensor capture or canonical room-worker throughput.

Two reproduced geometry defects are corrected:

1. Exact collinear zero-area retraces in native room rings previously rejected
   otherwise usable geometry. Normalization removes only exact redundant
   vertices after raw schema validation; genuine crossings remain rejected.
   Two retained candidates retain bit-identical polygon area and identical
   inside/outside classification at all6561 sampled raster centers each.
2. Native sliding-window origin offsets near integer cell shifts were truncated
   because float ratios entered integer coordinates. The tracked, hash-bound
   local patch rounds only within floating-point tolerance of an integer.
   Original worker fails4 signed-axis regressions; patched worker passes them,
   preserving genuinely fractional-shift behavior.

The original ignored native source closure and old binary remain unchanged.
`tools/build_native.py` stages/verifies the durable local patch into a fresh
output tree. Configure/build both exit0. Selected worker SHA256:
`d64acf40d0e4c96676de7905589699085e646c467f5caf5cfa1503ab39b4372b`.
Three maintained GPU map profiles (00770/00802/00861) select this worker and5Hz UI.
Other maintained profiles receive only the updated UI script checksum.

## Correctness verification

Evidence root: `.runtime/room-graph-sync-20261031/`.

- UI fixture72passed; live-map frozen focused44passed; independent review76+95
  initial focused tests and54 measured-object/cloud/control tests passed.
- Main region integration79passed; cross-component focused141passed.
- Native candidate final7passed/2skipped(exit0); skips require an explicitly
  configured separate prebuilt comparison. An earlier candidate configuration
  independently ran9passed, including the three native parity checks.
- Patch-staging safety7passed, including original-closure preservation, required
  fresh output directory and rejection of undeclared file/CMake edits.
- Full CPU first attempt2178passed/9failed/2skipped/9native deselected. The9failures
  exposed legacy overlay fixtures without source-map metadata. Fixture updates
  retain the optional-overlay check and add a mismatched-map STALE regression;
  final overlay+patch focused17passed(exit0). Full final result recorded below.
- Preflight ready=true, issues=[], exit0; preflight does not validate native run.
- Synthetic Qt render: `ui/render.json`, `ui/spatial-detail.png`,
  `ui/dashboard-graph-focus.png`. Exact Object XYZ verified; kinds only
  floor/room/object. These are layout fixtures, not semantic room accuracy.

## Remaining limits

Room segmentation is not established as semantically correct by these tests.
Retained runs use local81×81 maps at5cm (4.05m square), while persistent objects
may lie outside that window. In the two audited retained snapshots all9/all13
object memberships were unavailable; even fresh valid room geometry did not
contain their full footprints (outside/boundary). We do not fabricate nearest-room
edges. Unknown holes and approximate decomposition are not free-space evidence.
Future quality work needs longer-lived room geometry/support across map windows
and an offline room-boundary benchmark with independent ground truth.

Point cloud remains accumulated committed RGB-D evidence and may lag Live RGB.
No runtime/P10 performance or semantic-room accuracy claim follows from a
screenshot, unit test or preflight.

## Native bounded validation

`bash tools/run_map_demo.sh 00861 60 runs/demo-room-graph-sync-60s-20261031`
ran once after CPU checks, with a single GPU workload. Wrapper exit0, wall74.614s;
summary outcome completed, error null;1038rawframes,16accepted/committed batches,
0missing, nofailed/pendingworkers, clean shutdown. UI0droppedpublications,
0publication errors; publication thread stopped. RSS/GPU sampled monitors had
0readerrors,0capbreaches. The CLI still records `native_runtime_validated=false`;
this bounded wiring run is not P10 or an absolute resource bound certificate.
All387pinned source/test/config/tool/patch files stayed unchanged during the run.

`native-samples.json` retains62 sampled publications (approximately1s sampling,
not every UI update),0readerrors. In53samples the live map is newer than the
hierarchy-pinned map;20consecutive sampled pairs advance map while hierarchy
revision stays unchanged. Age at publication, across all62samples including
shutdown/drain: median76.44ms, p95250.55ms. This is a descriptive display freshness
check on this run, not a controlled before/after performance comparison or UI FPS.
Final archived publication is2s old because capture has stopped.

`render_native.py` reads the actual archived publication and committed RGB-D
assets through the unchanged read-only cloud reader. Render exit0;
`native-render-audit.json` confirms20234points from16sources,1Floor/1Room/15Objects,
exact measured ObjectXYZ and roomXY matching accepted geometry. Native screenshots:
`native-dashboard.png`, `native-spatial.png`. All15Object memberships are unassigned;
only the supported Floor→Room edge is drawn. Thus native Room→Object completeness
is explicitly not established. Synthetic assigned-edge cases test rendering, not
semantic assignment accuracy. The native screenshots are archived views, not a
claim about live GUI performance.

Independent source/provenance/display review artifacts are under `review/`:
original and patched89file closures verified, baseline binary unchanged, exact
source/robot joins,62monotonic samples,20map-advance pairs and retained cloud
independently checked. No semantic GT was introduced into runtime.

## Final frozen gate

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -m pytest tests -q -rs -m 'not native'
```

Exit0: **2188passed,2skipped,9deselected**,121.02s;
`full-cpu-frozen.log`. Skips: optional Numba dispatch in this interpreter and
explicit GPU-raycast authorization gate; native tests were checked separately.
All387native-run functional pins remain identical after the final suite.
`git diff --check` exit0; `point_cloud.py` has no diff.
Independent reviewer final scoped ACCEPT: `review/review.md`,
`review/native-audit.json`, `review/final-source-hashes.json`. All4review findings
resolved. The acceptance is limited to the implemented source/wiring/origin fix
and archived native rendering; it does not certify semantic partition quality,
Room→Object completeness or P10. No commit or push performed.

Restart to use the changes:

```sh
bash tools/run_map_demo.sh 00861 60
```
