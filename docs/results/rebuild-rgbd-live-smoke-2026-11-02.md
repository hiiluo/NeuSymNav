# Rebuild RGB-D integrated live smoke — 2026-11-02

Plan scope: bounded R8 smoke to exercise the opt-in Habitat → Rebuild M1–M5
lane. This is an integration probe, not the fixed A/B/C quality campaign or R8
acceptance. All runs used local scene 00805, seed 0, and a 30-second requested
duration. Rebuild/3DSG sources stayed read-only.

## Attempts and fixes

1. `runs/rebuild-rgbd-live-smoke-00805-30s-20261102/` exited 1 before sensor
   startup. Habitat did not send `ready` before the base profile's 10-second
   worker deadline; no sensor frame or M1–M5 request was admitted. Clean process
   teardown; sampled RSS peak 543,236,096 bytes.
2. `runs/rebuild-rgbd-live-smoke-00805-30s-startup60-20261102/` ran the full
   duration but was incomplete. Habitat started, but UI Qt could not connect to
   display `:0` and exited `-6`. Its recording completed (160 sensor records),
   while the room lane processed three frames and had no accepted M5 map. The
   recorded primary calibration ID changed on 76/79 captures while the robot
   moved. The sensor worker hashed the static mount after inverting native
   world transforms, making floating-point pose noise look like a calibration
   change. This run is retained as a failed diagnostic, not a pass.
3. Fixed both reproduced causes: the RGB-D profile gives Habitat startup 60
   seconds, and `habitat_worker.py` quantizes only the recovered static
   agent-to-sensor mount to 1e-6 for calibration identity. Per-frame world pose
   remains unchanged; the worker script hash is pinned in
   `configs/demo-00805.local.json`. The headless smoke sets
   `QT_QPA_PLATFORM=offscreen` so the UI process runs without an X display.

## Completed bounded smoke

Command:

```bash
QT_QPA_PLATFORM=offscreen PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
bash tools/run_rebuild_rgbd_map_demo.sh 00805 30 \
runs/rebuild-rgbd-live-smoke-00805-30s-stablecal-offscreen-20261102
```

Exit 0; `summary.json` reports `outcome=completed`, no runtime error, clean
sensor/UI/worker teardown, and a complete 136-record RGB-D/depth recording
(80,383,165 bytes). Habitat acknowledged seed 0 and actual primary/downward
resolutions 480×640 and 180×240. UI ran with the offscreen Qt backend; this
does not prove visible desktop rendering.

The room lane offered 67 primary frames, admitted and processed 7, and rejected
60 because its bounded queue was full. All seven admitted M1–M5 updates drained
cleanly. The final publication had M3 latest revision 7, accepted M3 revision
7, M5 revision 3, one raw M5 region, `regions_stale=false`, and
`replay_required=false`. M3 was 71×109 at 5 cm resolution (4,166 unknown,
3,446 free, 127 occupied cells). The published hierarchy included one
`source_region`; it assigned no object membership in this run.

Sampled process-tree RSS peak was 2,375,446,528 bytes with no sampled cap
breach. Resource sampling completed, but remains sampled rather than an
absolute memory ceiling; no usable GPU-memory provider was available.
`native_runtime_validated` remains false because the strict P10/resource and
acceptance gates are not satisfied by this smoke.

## Recorded source oracle

The admitted room-session recording contains seven frames. A five-frame prefix
was replayed through a fresh NeuSymNav session and compared with directly
invoked pinned Rebuild M1–M5 stages, using the same frame inputs and profile.
Command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
.venv/bin/python tools/compare_rebuild_rgbd_source_oracle.py \
  --recording runs/rebuild-rgbd-live-smoke-00805-30s-stablecal-offscreen-20261102/room-pipeline/session \
  --recording-frames 5 \
  --out runs/rebuild-rgbd-source-oracle-20261102-live00805-prefix5-retry
```

Exit 0, `parity_pass`; 5/5 prefix frames processed, clean shutdown. M3 states,
revision, origin, resolution and height masks matched exactly; height values
matched at `atol=1e-7`; M5 persistent IDs and polygons matched exactly. The
prefix sequence SHA-256 is
`bec3b04f861dbe8dbf048beb554bba8f5293dc8d6f0f2700c7a2a55c64ca41bf`. Report:
`runs/rebuild-rgbd-source-oracle-20261102-live00805-prefix5-retry/parity-report.json`.

The fifth-frame checkpoint is M3/M5 revision 5/1 with one region. The live
recording's last two older wire frames could not reconstruct their original
geometry hash because the wire stored depth already normalized to NaN while the
hash covered raw invalid sensor values. The adapter wire now retains raw source
depth/validity and optional empty mask provenance alongside the normalized M1
input. Regression coverage proves exact replay for finite invalid depth and
empty certified masks. A separate three-frame recorded synthetic replay also
passes: `runs/rebuild-rgbd-source-oracle-20261102-synthetic-recorded-replay/`.

## Plan status after smoke

Implemented and correctness-verified: startup profile allowance, stable static
calibration identity, source-preserving replay wire, and bounded recorded
source-oracle mode. Runtime-integrated: one completed 30-second smoke with
fresh M3/M5 publication. Still open: R1 independent review, native empty-episode
behavior, cumulative OctoMap node/voxel cap, historical 3DSG caller parameter
parity, full seven-frame recorded parity, queue sampling/throughput review,
visible UI inspection, room-quality A/B/C measurements, and R8 acceptance.

## 180-second visible follow-up after M5 failure handling

The previous live recording reproduced an M5 response containing a 133-vertex
ring that self-intersected and retraced several edges. The signed area was
nonzero, but the polygon was not a valid simple ring. The worker had checked
only finite coordinates and vertex count, so the host discovered the malformed
geometry after M1–M5 state had already advanced and poisoned the room session.

The worker now applies the shared simple-ring validator before committing M5
guard/tracker state. It runs M5 against a trial copy; invalid output is rejected,
the previous accepted M5 pair is retained stale, and the latest M3 map is still
published. It does not simplify or repair native geometry. Regression checks
cover a self-crossing ring, valid polygon serialization and native rejection.

Visible run command:

```bash
env -u QT_QPA_PLATFORM PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
bash tools/run_rebuild_rgbd_map_demo.sh 00805 180 \
runs/rebuild-rgbd-live-00805-180s-visible-20261102
```

The X11 display probe succeeded outside the sandbox; Qt wrote `NEUSYMNAV_UI_READY`
and closed without UI error. The bounded run captured 984 sensor frames with a
complete recording and clean sensor/UI/worker teardown. The room lane admitted
29 of 491 offers, processed all 29, and dropped 462 at its bounded queue. M3
reached revision 29; this sequence produced no accepted M5 polygons, leaving
`regions_stale=true`, `replay_required=false`, and no M3/M5 accepted pair. This
is expected fail-closed behavior for the malformed native geometry, not a room
segmentation success. Sampled RSS peak was 2,300,522,496 bytes. The overall run
summary is `incomplete`/exit 1 because resource sampling was incomplete (one
missing process sample and one truncated sample); `native_runtime_validated`
remains false. Artifact: `runs/rebuild-rgbd-live-00805-180s-visible-20261102/`.
The direct M4/M5 diagnosis and acceptance decision are in
`docs/results/rebuild-rgbd-m5-invalid-polygon-diagnosis-2026-11-02.md`; the
machine-readable gate is `tools/check_rebuild_rgbd_demo_acceptance.py`.
