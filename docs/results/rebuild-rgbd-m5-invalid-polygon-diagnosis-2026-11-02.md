# Rebuild RGB-D M5 invalid polygon diagnosis — 2026-11-02

## Finding

M5 did **not** create the self-intersection. The recorded room input at source
frame 39 produces one raw M4 contour with status `success` and branch
`accept_incremental`. M5 guard/tracker returns the exact same ordered vertices.
The raw M4 polygon and tracked M5 candidate have identical SHA-256
`b38a47ff5093ecc534ffd6c95eef1f019cb1500ec62b1b4acd50c4b93e993f9b`.

The ring has 133 vertices, 127 unique vertices, signed area 7.0475003 m²,
18 non-adjacent edge intersections and 6 undirected edges traversed twice in
opposite directions. The repeated path is a weakly-simple bridge: it contributes
area but retraces a chain, so a nonzero shoelace/contour area does not imply a
simple room boundary.

## Source path

The pinned M4 wrapper calls DuDe decomposition, collects each final polygon
piece, then traverses its `ply_vertex` linked list into a contour. During that
conversion it constructs integer `cv::Point` values from `Point2d` positions;
this can quantize fractional decomposition vertices. Its
`isValidContourForPolygon` predicate checks vertex count, nonzero area and a
nonempty bounding box; it does not test repeated edges or non-adjacent segment
intersections. The incremental stable-contour sanitizer and worker serializer
use the same area/bounds checks. The M4 worker therefore emits this contour as a
successful region.

M5's `DudeM5RegionStage` turns that outer contour into a `RegionObservation`;
`RegionUpdateProcessor` applies count/area/unknown-space guards, and
`RegionTracker` copies `observation.polygon` into `CanonicalRegion`. No M5 stage
operation changes the vertices.

An instrumented private M4 copy traced the frame-39 ring at each native
boundary. OpenCV `findContours` on the preprocessed mask returned the same 133
vertices and 127 unique vertices as the public M4 response. The `c_polygon`
passed into DuDe and its final piece had that same invalid ring. All 133
`Point2d` coordinates were integral, and conversion to `cv::Point` changed no
coordinate. The final piece contained one ring, so this was not a hole encoding
or a DuDe decomposition cut. The bridge was already created by contour
extraction from the binary mask.

The offending frame-39 mask had three 2x2 diagonal-only foreground contacts at
M4 grid cells `(90,43)`, `(86,44)`, and `(79,45)`. They coincide with the
repeated bridge path. OpenCV's 8-connected `findContours` treats those pixel
contacts as one component and emits a weakly-simple boundary. This pins the
frame-39 cause to ambiguous digital topology during M4 contour extraction,
before DuDe and M5. NeuSymNav does not rewrite the ring.

Frame 60 exposes a second path to the same failure. On a private candidate that
removed one foreground pixel at each detected diagonal-only contact, the
incremental M4 output at frame 39 became valid and M5 accepted it. At frame 60,
however, `Expanded_contour` contained a valid 116-vertex ring; drawing that ring
into a binary `Temporal_Image` and extracting it again produced a self-
intersecting 112-vertex contour before it entered DuDe. DuDe's input and final
piece were identical to that invalid re-extracted contour. This shows the
one-pixel contact rule is not a sufficient general fix; the contour→raster→
contour round trip also needs a topology-safe implementation or replacement.
The instrumented second 71x108 mask had no exact 2x2 diagonal-only contact, yet
its OpenCV contour was still invalid with three non-adjacent edge contacts. The
preceding 58x108 mask produced a valid 121-vertex contour. This candidate is
diagnostic only; the mask pixel-removal policy must not be treated as the final
algorithm.

Relevant read-only pinned source locations:

- `native/dude/worker.cpp:109-124`: raw contour size/area/bounds gate and JSON
  serialization.
- `ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2/include/wrapper.cpp:16-27,408-443`:
  the DuDe final-piece predicate, linked-list traversal, and `Point2d` to
  integer `cv::Point` conversion at lines 431-435; mask contour extraction at
  line 177.
- `ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2/include/inc_decomp.cpp:700-770`:
  incremental expanded-contour rasterization and wrapper round-trip.
- `ref_OccuSG/OccuSG/src/incremental_dude_ros2/incremental_dude_ros2/include/inc_decomp.cpp:274-286`:
  incremental contour sanitizer uses the same area/bounds criterion.
- `src/standalone_sg/regions/dude_client.py:242-260`,
  `src/standalone_sg/regions/pipeline.py:25-80`, and
  `src/standalone_sg/regions/tracker.py:145-174`: ingestion, M5 guard and
  polygon-preserving tracking.

The Rebuild source and binaries remained read-only at pins M4
`7868c892f3584faa17712e1ede0660006d97531b05be5c258fe303015f1ef959` and source
tree `60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0`.

## Caller/config parity and saved-mask replay

The visible run's `run-profile.json` pins M4 to `decomp_threshold_m=1.5`,
`safety_distance_m=0.5`, and `preprocessing_policy=source`. These match the
Rebuild `DuDeConfig` defaults and the parameters recorded by its M4 local demo;
the Rebuild native RGB-D smoke and Habitat replay instantiate the same defaults
(the Habitat replay exposes only the preprocessing policy override, defaulting
to `source`). The source worker uses the same default policy. Thus no M4
configuration mismatch was found, and no threshold/safety change was made.
This verifies parity with those checked-in Rebuild callers, not every historical
3DSG launch path or an independently pinned old live run.

The exact admitted recording prefix was replayed with pinned M2/M3 and M4
hashes through source frame 39, with `debug_capture_preprocessing` enabled.
The 58x108 M3 grid at 5 cm and origin `[-1.25,-1.75]` produced a 2,977-pixel
preprocessed-free mask, 994 black pixels and 3,675 M3 unknown cells. M4 again
returned one `success` / `accept_incremental` region with the same 133-vertex
ring; M5 receives that ring without an intervening geometry repair. A saved
overlay puts the raw M4 contour on the actual preprocessed mask. It shows the
repeated path at the M4 region boundary; the recorded protocol cannot tell
whether the path existed before M4's `Point2d`→integer-`cv::Point` conversion.
The preceding admitted frames 0, 1, 2 and 20 returned `accept_empty_free_space`
with zero regions, so this was newly created by the frame-39 incremental M4
path rather than a retained previous region.

Replay artifacts are in
`.runtime/rebuild-rgbd-m5-invalid-polygon-20261102/`: `frame-39-preprocessing.npz`
(exact M3 values, source masks and M4 coordinates), `frame-39-mask-contour.png`
and `.svg` (overlay), `frame-39-mask-contour.json` (config/pins/summary), and
`replay-prefix-m4-branches.json` (first region/branch history),
`diagnosis.json` (ring topology metrics).

Private source-copy instrumentation and candidate-only evidence are in
`.runtime/rebuild-m4-vertex-diagnostic/`. The instrumented M4 reproduced the
frame-39 output exactly. A private candidate with a diagonal-contact heuristic
was pinned locally as `aba23d17...`; its exact full-prefix replay completed
29/29 frames, exit 0, but accepted only frame 39. At final M3 rev29, M5 remained
rev1 bound to M3 rev5 and stale. Candidate evidence does not change the
official Rebuild pin or NeuSymNav config.

## NeuSymNav handling and demo gate

NeuSymNav now validates M5 geometry before committing the guard/tracker trial.
An invalid polygon rejects that M5 update, rolls back M5 state, retains the last
accepted M3/M5 pair as stale, and continues publishing M3. The host does not
repair or simplify the ring.

`tools/check_rebuild_rgbd_demo_acceptance.py` is the demo acceptance gate. It
requires a completed run, clean workers, a complete recording, a fresh nonempty
M5 snapshot paired with the latest M3, and valid simple/nonzero polygons.
Applied to `runs/rebuild-rgbd-live-00805-180s-visible-20261102/`, it returns
`accepted=false`, exit 1: latest M3 revision 29 but no accepted M3/M5 pair or M5
region; the overall summary is also incomplete due resource-sampler gaps.
Applied to the previous 30-second offscreen smoke, it returns `accepted=true`,
one valid fresh M5 region at M5 revision 3 / M3 revision 7. That offscreen smoke
does not count as the requested visible 180-second demo.

The exact admitted-prefix replay with the candidate correction still fails the
final fresh-M5 gate, so no additional visible 180-second demo was launched. A
corrected and newly pinned Rebuild M4 must replace the mask contour extraction
and contour→raster→contour round-trip with topology-safe processing; validating
only frame 39 or rejecting invalid output is insufficient.

## Follow-up candidate: direct incremental contour path

A second private source-copy candidate bypassed the incremental
contour→raster→contour round-trip when `Expanded_contour` passed a strict simple
ring check, while retaining the existing full-decomposition path otherwise.
The source-copy binary SHA-256 is
`44fc4a9dd2e1a50c8c057279b516312f568c4162a4c83ba6771dcb8c417b23b8`.
The exact replay accepted valid, fresh M5 regions at source frames 39 and 60
(M5 revisions 1 and 2 bound to M3 revisions 5 and 6). At source frame 81 the
`fallback_full_decomposition` branch produced an M5 polygon rejected by the
unchanged simple/nonzero validator. All later updates retained M5 revision 2
bound to M3 revision 6 while M3 advanced through revision 29. The run therefore
fails the same latest-M3 acceptance criterion. This candidate is also
diagnostic-only and is not a fix suitable for pinning or live use.

This narrows the missing source fix: making only the incremental contour path
topology-safe is insufficient. The full-decomposition fallback and the shape it
returns must also be traced and corrected upstream. No NeuSymNav validator or
polygon semantics were changed to make this candidate pass. Replay summary is
in `.runtime/rebuild-m4-vertex-diagnostic/direct-contour-full-replay.json`.

## Rebuild source fix and exact replay

After the user explicitly authorized editing Rebuild, the M4 source was updated
at the upstream contour boundary. A strict simple-ring predicate now rejects
self-intersections before DuDe output is accepted. Weakly-simple OpenCV contours
with repeated vertices are split into simple loops; the largest valid loop is
retained for that contour. Diagonal-only 2x2 foreground contacts are resolved
deterministically by removing the less-connected foreground pixel (coordinate
order breaks ties). Already-simple incremental contours are passed directly to
DuDe so rasterization and `findContours` do not recreate a weakly-simple ring.
Invalid fallback geometry is rejected and M4 preserves the last stable result.
M5 validation was not relaxed and NeuSymNav does not repair polygons.

The edited source files are `wrapper.cpp`, `wrapper.hpp`, and `inc_decomp.cpp`
under Rebuild's `ref_OccuSG/.../include/`. Their originals are backed up in
`.runtime/rebuild-m4-vertex-diagnostic/original-source-backup/`. Rebuild's CMake
uses generated source snapshots; these were synchronized before the official
build. Build completed successfully. The new Rebuild M4 binary hash is
`5e34759d1c32197ee207c408579604fb797e86839d034d5752ac42b222a9608d`; M2/M3 and
the pinned Python source closure are unchanged.
Updated source-file SHA-256 values: `wrapper.cpp`
`aba44097619c9667662d64160c2af0a873af0c956985960180342ca2b317a729`,
`wrapper.hpp` `f5c43d8a938ceec1d70a6a07af3e640a7ad0b9d51ce2ea5cadcbe72016507cff`,
`inc_decomp.cpp` `3afb2537b7ca1160f10854f90ab95ebbf2ef02fc892b73af3eabdb1787d74f14`.

Using that exact binary hash, all 29 admitted frames from the saved recording
were replayed through NeuSymNav's source worker. M5 accepted 24 updates; source
frame 81 was rejected safely and retained stale M5 temporarily. Later updates
recovered. Final checkpoint: latest M3 revision 29, accepted M3 revision 29,
M5 revision 24, two valid regions, not stale. The worker's `valid_ring` check
ran before every M5 commit. Full replay artifact:
`.runtime/rebuild-m4-vertex-diagnostic/clean-candidate-full-replay.json`.
The synthetic direct-source vs adapter oracle passed 3/3 frames with exact M3
and M5 parity at
`.runtime/rebuild-m4-vertex-diagnostic/source-oracle-clean/parity-report.json`.

One visible 180-second run was attempted with the newly pinned binary, but it
does not pass live acceptance. The environment has no reachable X server at
`DISPLAY=:0`, so the Qt viewer exited `-6`. Room lane processed 22/289 offers
and dropped 267; final M5 was stale at M3 revision 18 while latest M3 was 22.
`tools/check_rebuild_rgbd_demo_acceptance.py` exits 1 with `accepted=false` for
this run. Artifact:
`runs/rebuild-rgbd-live-00805-180s-after-m4-fix-20261102/`. This live
integration failure is separate from the passing exact recording replay. Do not
claim a successful visible demo until a reachable display is available and the
acceptance checker passes.

## Follow-up: M5 area-drop rejection in the 22-frame live replay

The exact 22 admitted frames were replayed with the first corrected M4 binary
(`5e34759d1c32197ee207c408579604fb797e86839d034d5752ac42b222a9608d`). At M3
rev18, M5 accepted one 7.71750023 m² region. At rev19, M4's
`fallback_full_decomposition` emitted one simple 0.11875000 m² polygon; M3 free
ratio rose slightly from 0.45846 to 0.45934. The unchanged M5 guard rejected
the 98.46% area drop. Candidate geometry and guard measurements are in
`.runtime/rebuild-m4-vertex-diagnostic/live-run-22frame-area-replay-with-m4-output.json`.

Native stderr localized the fallback: the incremental expanded-contour call
rejected all 4 contours; full fallback received 12 contours, rejected 11, and
kept one 47.5-pixel contour. The captured M4 mask has 3,633 foreground pixels,
with a largest 4-connected component of 3,503 pixels. This is contour
extraction/decomposition loss, not a defensible M5 guard failure. Artifact:
`.runtime/rebuild-m4-vertex-diagnostic/live-frame243-native-stderr.txt`.

As a containment fix, Rebuild M4 now preserves its stable geometry and rejects
fallback output when total candidate area is below 15% of previous stable area,
matching the already-pinned M5 85% maximum-drop limit. The exact 22-frame replay
with official binary
`b7c31163135740eb93a66ec56e2cb2abd0cb02e417bd75edbd97a34d9d83a164` confirms
frame243 is rejected without replacing M4 state. Frames257, 272, and 286 still
reject with `fallback_candidate_area_drop_too_large`; accepted M3/M5 remains
rev18/M5 rev13 against latest M3 rev22. Thus this change prevents M4 state
poisoning but does not yet produce a fresh M5 region for the live recording. No
additional visible demo was launched. The replay confirms containment only;
source-oracle parity and the 29-frame replay were not rerun against this latest
pin. The latest 22-frame artifact is
`.runtime/rebuild-m4-vertex-diagnostic/live-run-22frame-after-area-guard-replay-final.json`.

## Follow-up: recover the frame-243 contour (2026-11-02)

The saved frame-243 M4 mask was tested with a C++ OpenCV 4.6 probe to match the
Rebuild worker's OpenCV version. The 142-point large contour contains edge
touches represented by a vertex on the interior of another segment. Repeated
vertex splitting alone exposed a zero-area, two-point retraced child; treating
that child as a fatal split error discarded the valid loop. Rebuild's M4
`insertTouchVertices()` now materializes those contacts before splitting and
allows a degenerate child to be omitted while preserving valid sibling loops.
On the captured mask the splitter now returns one 3,327.5-pixel loop. The
existing fallback area guard remains active and NeuSymNav's M5 validity checks
are unchanged.

The official worker rebuilt with SHA-256
`6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693`; its
generated wrapper source matches the edited source. Replaying the exact 22
admitted frames now accepts M5 at revisions 5 through 22. At frame243/M3
revision 19, M4 takes `accept_incremental`, M5 accepts a valid 7.9975 m² region,
and the final M3 rev22 remains accepted and non-stale. Full per-frame output is
`.runtime/rebuild-m4-vertex-diagnostic/live-run-22frame-degenerate-loop-replay.json`.

Current-pin synthetic source parity passes 3/3. A fresh offscreen 30-second
RGB-D run processed all 7/7 admitted room frames, finished at M3 rev7/M5 rev3
with one valid region and no stale state, and shut down cleanly. The demo
acceptance checker reports `accepted=true`. A direct source oracle over the same
7 recorded frames passes exact M3 states/origin/revision/height masks and exact
M5 IDs/polygons. Artifacts:
`runs/rebuild-rgbd-currentpin-offscreen-00805-30s-20261102/` and
`runs/rebuild-rgbd-source-oracle-20261102-m4-topology-currentpin-recorded/parity-report.json/parity-report.json`.
The run profile and oracle both use M4 pin `6ff1fb5b…`; preflight is ready with
no issues. A second exact replay over the 29-frame admitted sequence
from the prior run profile also succeeds under the new binary: M5 accepts
revisions 5–29, ends with two valid regions at M3 rev29, and reports no M4
failures. Artifact:
`.runtime/rebuild-m4-vertex-diagnostic/live-run-29frame-topology-replay.json`.
No new visible demo was run because `xdpyinfo` cannot connect to `DISPLAY=:0`.
The source topology fix is correctness-verified against the captured mask,
22-frame and 29-frame replays, synthetic and recorded-source oracles, and is
runtime-validated in a bounded offscreen integration smoke. It is not yet
validated in a visible 180-second run. Do not call R8 accepted until a fresh
visible 180-second run passes the acceptance checker with a valid M5 region.
