# Rebuild room backend comparison — 2026-11-02

User-authorized scope: a runnable, explicit Rebuild segmentation backend using
existing readonly local assets, with portal candidates hidden by default. One
Luna6.0High implemented the adapter/config/launcher/wrapper; main independently
reviewed the backend seam, implemented the UI toggle and ran actual native checks.
No source sibling modifications, model downloads, installs, training or publish.

## What is changed

`RebuildRegionBackend` uses actual `DudeM5RegionStage` + original M5 guard/tracker
and original native M4 worker, with source preprocessing. External package is
loaded in a private namespace and source imports/updates suppress bytecode writes.
The entire 50-file external Python closure and binary are SHA256-pinned. Original
M5 owns canonical region IDs; there is no second M5 tracker. Publication validation
uses a transactional trial of the source M5 processor. Rejections keep the accepted
map/region source pair. Native reset on raster origin/shape/resolution change does
not reset the M5 tracker. Backend/source/worker/preprocessing/timing diagnostics
and an actual-profile suffix identify the selected path. Control and safety map
remain unchanged; this is M4/M5 on a common measured raster, not replacement of
RGB-D mapping by OctoMap or the whole 3DSG pipeline.

Portal data remain available but the map, 3D and Room stability list hide them by
default. `Portals (debug)` explicitly restores them. Rebuild mode appears in the
window subtitle. Existing zoom/orbit/popup/splitter controls are retained.

## Cold native comparison on identical inputs

Repro: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python
.runtime/rebuild-backend-20261102/compare.py` (exit0). Results and images are in
`.runtime/rebuild-backend-20261102/comparison.json` and `*-comparison.png`.

| Input | NeuSymNav raw/final M5 regions | Rebuild M5 regions | Matched polygon IoU |
| --- | ---: | ---: | --- |
| Saved 00805 09:35 source map486 | 1 | 1 | 0.7587 |
| Saved 00805 09:13 source map1682 | 2 | 2 | 0.8618 / 0.9234 |
| Synthetic two chambers plus corridor | 3 | 3 | 1.0000 for all three |

Both backends accepted each cold input. This does not reproduce the historical
incremental update sequence. Pixel values, unknown, resolution and origin were
held fixed. Binary AND preprocessing differ: default NeuSymNav uses
`extended_unknown_boundary`, Rebuild uses `source`. Differences are consequently
backend-profile effects, not isolated proof of an improved DuDe kernel. Inspection
shows Rebuild outlines can extend further at unknown borders; region geometry is
not certification of free space. No Room labels/GT were used and no accuracy
improvement is claimed. Native calls were sequential, no GPU benchmark/training.

## Verification history and usage

Adapter/region focused33pass0, launcher28pass0, related combined89pass0; UI12pass0.
A main focused command initially named a nonexistent test file (exit4/no tests),
then the corrected95-test run caught a real missing-worker-config KeyError in a
legacy launcher test. Fixed default lookup, no test weakening; failure retained.
Final whole CPU suite and live results are recorded below when complete.

```bash
bash tools/run_rebuild_map_demo.sh 00805 --preflight
bash tools/run_rebuild_map_demo.sh 00805 600
```

The wrapper derives a pinned ignored profile from `configs/demo-00805.local.json`
and delegates to the existing local runner, preserving display scale, GL/cache and
thread configuration. Existing `tools/run_map_demo.sh` remains the comparison
baseline. RoomOwner remains a separate post-segmentation policy: two Rebuild
regions may still be held in one stable Room. Raw region polygons/graph show the
source M5 segmentation; do not use stable-Room count alone to compare backends.

## Actual Rebuild live smoke

Command: `QT_QPA_PLATFORM=offscreen bash tools/run_rebuild_map_demo.sh 00805 30
runs/demo-rebuild-00805-30s-20261102`, explicitly approved outside sandbox for native
sensor/GL access. Exit0, completed, errornull,254frames, cleanworkers/no failed
runtime workers. Actual profile contains `:rooms-rebuild_m4_m5`; runtime diagnostics
identify the exact external source closure, M4 worker path/hash and `source` policy.

130 region requests:125accepted,5rejected (1initialno-free,4non-simple/nonzero
polygon validation failures),14native extent resets. Final source map130, raster
76x101@.05m, one source M5 region and one tentative Room. The four invalid polygon
updates retained the previous accepted geometry/IDs; no gate was weakened and no
source fix is claimed. Final native branch was valid reuse/no differential; native
invocation is recorded. `live-result.json` and original run preserve diagnostics.

This establishes actual selected-backend integration and clean bounded execution,
not that Rebuild improves room segmentation. The run's overall
`native_runtime_validated` remains false under the existing P10 measurement gate.
No direct performance comparison follows from different live frame counts or the
last-operation timing. The controlled same-input cold comparison above is the
basis for geometric differences.

## Final verified snapshot

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src QT_QPA_PLATFORM=offscreen
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 .venv/bin/python -m pytest tests -q -rs
-m 'not native'` exited0: **2267passed,1skipped,9deselected**,148.19s. The skip is
the explicit GPU-slot authorization gate; deselected native tests are not claimed
pass. Actual source-worker calls and live smoke above are separate evidence.
Eight final code/test/wrapper hashes verify unchanged; diffcheck0. Evidence root
`.runtime/rebuild-backend-20261102/`: full-cpu.log, final-source.sha256,
comparison.json/images, live-result.json/log, worker/source-pins.json and focused
logs. Main independent source review caught config fallback/read-only bytecode/
raw-count/environment issues which were fixed before final run. No safety, native
threshold, GT comparison or test assertion was weakened. No commit/push performed.
