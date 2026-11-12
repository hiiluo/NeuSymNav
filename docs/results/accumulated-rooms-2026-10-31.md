# Accumulated room geometry — 2026-10-31

Recent local runs ended with one region because the room worker received only
an 81×81 local raster (4.05×4.05 m at 5 cm), even when the display showed a larger
accumulated map. The fix feeds exact raw occupancy history to the region lane,
keeping the local motion map independent. It does not lower DuDe thresholds or
invent additional Room nodes.

## Behavior and provenance

The region lane builds a full-resolution historical NavSnapshot from immutable
measured tiles and the mapper's exact robot geometry. Only previously classified
FREE cells receive floor support and conservative float64 clearance at robot
height; unknown/occupied are never promoted. Every input retains source frame,
capture time, clock, calibration, floor, robot identity and map revision.

Dense room extent is capped at one million cells, raw tiles retain the existing
4096-tile/16 MiB budget. Missing/stale/incomplete/oversized history yields stale
geometry and unavailable membership; an empty startup fallback is not labeled
as accumulated history. Native geometry changes reset DuDe state while Python
canonical tracking matches against the whole retained geometry. Corrections to
occupied/unknown are retained rather than preserving obsolete free areas.

Local navigation/control and fresh place admission are unchanged. Published
place paths may be revalidated against historical classification and retain
`motion_certificate=false`. Floor/region nodes and geometry-supported edges carry
input scope and historical evidence. Bounded region telemetry records input
extent, raw output count, status/branch, acceptance, native resets and rejects.

## Verification

Artifacts are under `.runtime/accumulated-rooms-20261031/`:

- `focused.log`: 118 targeted mapping/region/hierarchy/runtime tests passed,
  exit0 /11.77s, before the final startup-provenance correction.
- `focused-final.log`: 22 accumulated/cadence regressions passed, exit0 /4.93s,
  including explicit clock advancement for coalesced publication and scope
  generation consistency. Earlier clock-frozen fixture timeouts are retained;
  no runtime cadence/TTL was relaxed to address them.
- `full-cpu.log`: 2228 passed/1 skipped/9 deselected, exit0 /173.26s, preceding
  final provenance/fixture deltas. Frozen final result follows below.
- `review/final-review.md`: independent P06 ACCEPT, source hash checks, separate
  53 P06/map/runtime,30 display/global/UI,16 accumulated and6 post-fixture tests
  pass. This records the startup provenance finding and its correction.
- `native_validation_result.json`: actual pinned CPU DuDe worker e41f...
  processed synthetic two-chamber occupancy. Native1→2 geometry expansion resets
  once; stage2 has separate chamber centers; stage3 retains left region ID outside
  right-only local window; stage4 replaces left/hall with occupied and removes
  its region without another reset. Twelve assertions pass, exit0. Independent
  review reran this same oracle; it is not an independent scene/algorithm.
- `native_validation_stage2.png` and `native_validation_stage4.png`: inspected
  actual native polygon/raster renders. These are synthetic measured-state
  fixtures, not simulator ground truth or room-accuracy scores.

Command for the CPU suite:

```sh
QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs -m 'not native'
```

No semantic-room quality/coverage, simulator doorway safety, throughput or P10
certification follows from the synthetic cuts. Existing native worker and model
assets are unchanged; no downloads, training or sibling-source edits.

## Final gates and real runtime

Frozen final CPU gate: **2229 passed,1 skipped,9 deselected /175.58s, exit0**
(`full-cpu-final-verified.log`). Skip: explicit GPU-raycast authorization gate.
The preceding `full-cpu-final.log` failed one existing execution-proof case with
`completed decoded resolution unsupported or changed`; the isolated rerun also
failed. That test reused a 20ms launcher fixture but requires decoded capture
provenance. Only its wrapper now runs for1s; all seed/resolution/source binding
and native=false assertions remain. Main52proof/wiring tests pass0/8.39s;
independent targeted proof test passes0/3.56s. No runtime timing contract changed.
The shared20ms helper is unchanged for its other callers. These earlier failures
are retained; they are not folded into the final pass count.

Independent review also accepted test-only100ms fake-clock advancement for
coalesced publication and the atomic scope/map-generation regression. Final
source and test hashes are recorded in `final-source-sha256.txt`; the proof
fixture's separate review/hash is under `review/execution-proof*`.

Actual CPU-native origin-reset probe (`origin-reset-result.json`) shifts raster
origin by(-0.05,-0.05) while padding its bounds, keeping world free space fixed.
Native reset acknowledged once; all three output pieces overlap their preceding
world geometry by >0.999999 intersection/max-area, exit0. This checks actual
coordinate consistency on the original local binary without relaxing tolerance.

Live command, after CPU work stopped:

```sh
bash tools/run_map_demo.sh 00805 60 runs/demo-accumulated-rooms-60s-20261031
```

Exit0/completed/errornull,435frames,215accepted room updates/one initial
no-observed-free rejection,14native resets, clean workers, no observer errors or
sampled cap breach. Room input76×101@5cm versus control81×81, exact same final
source/revision. The accumulated input retains175known occupied cells outside
the final local window; no outside-local FREE cell was measured in this short
run. Sampled body travel lower bound0.52448m, aggregate actuation complete=false.
Two object commits, no first assigned membership. Evidence: `live-result.json`,
`live60.log`, and the run's source-bound exports/UI publication.

The real60s run still ends with **one region**. It validates the larger historical
input, persistence path and runtime wiring, not multi-room accuracy on that map.
The two-room cutting evidence is the native controlled fixture above. Last live
native branch is `accept_reuse_adjusted_no_differential`, so its final
kernel_invoked=false is expected reuse on unchanged geometry, not a missing
native worker. No room-count forcing or threshold tuning was performed.
