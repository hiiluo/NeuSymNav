# Local M2 profiler and backprojection-stride comparison — 00805 — 2026-11-03

## Scope

Local diagnostics only. Input was the complete raw recording from
`live-30s-fps025`; its trajectory path length is 0.0478 m, so this is a
near-static room view. Rebuild source/binaries remained read-only and pinned.
No Kaggle resources, acceptance thresholds, or M5 validators were changed.

## 1. M2 cost breakdown

Three primary RGB-D frames were sampled evenly from the same 65-frame recording
(frame indices 0, 32, 64). Each frame was 640×480 with about 305,000 valid /
backprojected points. Lightweight wall timers, without cProfile, measured:

| `OctoMapWorker.integrate` part | Total over 3 updates | Per update |
| --- | ---: | ---: |
| Integrate wrapper | 8.523 s | 2.841 s |
| Point validation | 0.033 s | 0.011 s |
| ASCII request write to worker pipe | 4.129 s | 1.376 s |
| Response read/decode | 1.306 s | 0.435 s |
| Remaining wrapper work | 3.056 s | 1.019 s |

“Remaining wrapper work” is the integrate duration minus validation, pipe write,
and response read. It includes Python list/string construction and formatting,
encoding, locks, and any other work in that method. It is not a pure serializer
timer. The pre-existing stage timer p50 across these three frames was M1 63 ms,
M2 3.063 s, M3 36 ms; this short sample has high variation and is diagnostic.

A separate cProfile run on the same three frames counted 916,026 point-generator
calls and 916,023 `ScanPoint.__post_init__` calls (about 305k/frame). It also
counted 916,026 formatted-point generator calls in `OctoMapWorker.integrate`.
The profiler materially slowed execution; its wall times are diagnostic-only.
These call counts and source locations identify Python object creation and
per-point ASCII formatting as hotspots. They do not establish the native
OctoMap share of M2.

## 2. Full-recording stride comparison

All 65 primary RGB-D frames were replayed for each stride. Resolution, depth
range, source/binary pins, M4/M5 policy, and frame sequence were held constant.
Only `backprojection_stride` changed. Full sequence stride 1 is the reference.

| Stride | Wall time | Speedup vs 1 | Median M1–M3 | Median M2 | Median points/frame |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 369.08 s | 1.00× | 5.324 s | 2.968 s | 305,441 |
| 2 | 109.76 s | 3.36× | 1.444 s | 0.815 s | 76,378 |
| 4 | 39.79 s | 9.27× | 0.460 s | 0.257 s | 19,098 |

Quality against the stride 1 M3/M5 output:

| Comparison | Stride 2 | Stride 4 |
| --- | ---: | ---: |
| M3 known-cell recall | 0.9981 | 0.9961 |
| M3 occupied-cell recall | 0.8912 | 0.7415 |
| M3 occupied-cell precision | 0.9924 | 0.9732 |
| M3 occupied IoU | 0.8851 | 0.7267 |
| M3 free-cell recall | 0.9977 | 0.9960 |
| M5 fresh valid regions | 1 / 1 | 1 / 1 |
| M5 polygon IoU | 0.9659 | 0.9420 |
| M5 area | 8.144 m² vs 8.085 m² | 8.524 m² vs 8.085 m² |

Stride 2 is the stronger local candidate: it reduced full replay wall time by
3.36× and retained one fresh M5 polygon with 0.966 polygon IoU. It still lost
about 10.9% of the reference occupied cells. Stride 4 is substantially faster,
but its 0.741 occupied recall and 0.727 occupancy IoU show meaningful geometry
loss despite a valid M5 polygon. A valid polygon alone does not certify that
thin walls, doorways, or room boundaries were retained.

## Artifacts and verification

- M2 phase timing/profile: `.runtime/local-room-fps-experiment-00805-20261103/m2-phase-timing-3frames/`
- cProfile call counts: `.runtime/local-room-fps-experiment-00805-20261103/m2-profile-3frames/`
- Full stride comparison JSON and M3 rasters:
  `.runtime/local-room-fps-experiment-00805-20261103/stride-comparison-65frames/`
- Both measurement commands exited 0; all 65 updates completed for each stride,
  each session shutdown cleanly, and M5 was fresh with one valid region for all
  three variants. The comparison tool does not run acceptance.

## 3. Bounded live stride-2 demo

To check the explicit stride setting in the live runner, copied the pinned local
00805 config into `.runtime/` and changed only
`workers.room_pipeline.backprojection_stride` from 1 to 2. No tracked runtime
default, acceptance rule, Rebuild source, or Kaggle bundle changed. Preflight
returned `ready=true`, `issues=[]` (exit 0).

The first 60-second attempt ran with the machine's configured X display, which
is unavailable in this execution environment. The room run completed and M5
was fresh with one valid region, but strict acceptance correctly rejected it
because the UI process exited `-6`. The saved `ui/desktop.log` records
`could not connect to display :0`.

Repeated the same bounded demo with `QT_QPA_PLATFORM=offscreen`. The run
completed with clean shutdown and strict acceptance **accepted** (checker exit
0): M3 accepted/latest r22; M5 r11; one valid M5 region; no stale or replay
requirement; raw recording 186/186 frames complete. There were 92 primary
RGB-D room candidates and 22 processed updates; median service was 2.749 s.
The captured pose path was only 0.0066 m, so this is still a near-static view,
not a traversal test. The accepted snapshot is saved at
`.runtime/local-room-fps-experiment-00805-20261103/stride2-live-demo-60s/stride2-accepted-snapshot.png`.

This confirms that a pinned 00805 live run can execute stride 2 and produce an
accepted fresh M5 result under offscreen Qt. It does **not** show whether stride
2 preserves room/doorway boundaries over meaningful movement. Keep stride 1 as
the production default until a same-recording stride 1/2 comparison covers
substantial translation and turns.

## 4. Same-recording stride 1/2 replay with a camera turn

The first bounded live stride-2 attempt had a complete raw recording despite
the Qt display startup failure. Its recording certificate contains all
218/218 sensor frames, including 108 primary RGB-D frames. From the primary
camera transforms, the XY path was 0.0663 m and accumulated absolute yaw change
was about 101.2°. This includes a clear view rotation but little translation.

Replayed all 108 primary frames in order through fresh pinned M1–M5 sessions,
changing only `backprojection_stride`. Both sessions processed all 108 frames
and closed cleanly.

| Metric | Stride 1 | Stride 2 | Stride 2 vs 1 |
| --- | ---: | ---: | ---: |
| Replay wall time | 824.53 s | 241.65 s | 3.41× faster |
| M1–M3 median update time | 7.526 s | 1.984 s | 3.79× faster |
| M2 median update time | 4.217 s | 1.093 s | 3.86× faster |
| Processed updates | 108 | 108 | same sequence |
| M5 regions | 1 fresh | 1 fresh | same count |

Quality against stride 1:

| M3/M5 metric | Result |
| --- | ---: |
| Known-cell recall | 0.9987 |
| Occupied-cell recall | 0.8938 |
| Occupied-cell precision | 0.9862 |
| Occupied-cell IoU | 0.8827 |
| Free-cell recall | 0.9992 |
| M5 polygon IoU | 0.9576 |
| M5 area | 8.074 m² vs 8.255 m² |

The turn-only trajectory retained most known/free geometry and the M5 outline,
but stride 2 omitted about 10.6% of reference occupied cells. It does not
establish wall/doorway retention while crossing rooms. The offline comparison
tool does not run the strict acceptance checker; its M5 counts/freshness are
diagnostic only. Separately, the bounded live stride-2 run above passed strict
acceptance with one fresh valid M5 polygon.

Artifacts and command:

- A/B occupancy image:
  `.runtime/local-room-fps-experiment-00805-20261103/stride-comparison-turning-108frames/m3-side-by-side.png`
- Full report, per-stride M3 rasters, and session journals:
  `.runtime/local-room-fps-experiment-00805-20261103/stride-comparison-turning-108frames/`
- `PYTHONPATH=. PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 .venv/bin/python tools/compare_rebuild_room_strides.py --recording .runtime/local-room-fps-experiment-00805-20261103/stride2-live-demo-60s/run/keyframes/recording --config .runtime/rebuild-rgbd-m1-m5-v1/configs/map-00805.json --strides 1 2 --out .runtime/local-room-fps-experiment-00805-20261103/stride-comparison-turning-108frames` → exit 0.
- Strict acceptance on the separate live stride-2 run → accepted=true, exit 0.
- `git diff --check` → exit 0.

## Conclusion and next gate

**Implemented:** diagnostic-only phase profiler and stride comparison utility;
no production default or Rebuild source was changed.

**Correctness-verified:** Python syntax/CLI checks and M3/M5 same-recording
comparison completed against the pinned stride 1 reference.

**Runtime-validated:** 3-frame M2 phase timing; 3-frame cProfile call counts;
65-frame full-sequence replay at strides 1, 2, and 4; bounded 00805 live
stride-2 demo with strict acceptance; same-recording 108-frame stride 1/2 turn
replay.

**Not established:** performance or room-boundary retention on a trajectory
covering meaningful new space (translation was only 0.0663 m); long-run
stability; generality to other maps.

Next local gate: repeat the stride 1/2 comparison on one recording with
substantial translation through a doorway/hallway and multiple room boundaries.
Keep stride 1 as the production default until that comparison shows acceptable
occupied geometry retention and strict live acceptance remains green.
