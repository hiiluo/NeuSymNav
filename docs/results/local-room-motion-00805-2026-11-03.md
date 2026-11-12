# Local motion throughput experiment — 00805 — 2026-11-03

## Change under evaluation

The 180-second stride-2 run was spending nearly every owner-thread iteration on a
640×480 primary RGB-D capture as well as navigation depth. Its requested primary
rate was 5 Hz, but the loop only completed about 1.9 iterations/s, so primary
capture was due on every iteration. A temporary, ignored profile kept navigation
at 10 Hz and reduced primary RGB-D to 1 Hz. A second profile experimentally
raises the Navigator's nominal speed from 0.15 to the existing hard limit of
0.20 m/s. Configuration validation rejects values above 0.20. The MotionGuard
limit, action horizon, source freshness, navigation depth resolution, Rebuild
source/binaries, stride 2 and strict acceptance checker remain unchanged.

Profile:
`.runtime/local-room-motion-00805-20261103/primary-1hz-smoke-60s/config-00805-stride2-primary1hz.local.json`

## Measurements

| Run | Primary RGB-D frames | Navigation frames/poses | Executed commands | Observed translation lower bound |
| --- | ---: | ---: | ---: | ---: |
| Previous stride-2 baseline, 180 s | 340 | 341 | 66 | 0.0100 m |
| Primary 1 Hz smoke, 60 s | 52 | 174 | 98 | 0.1574 m |
| Primary 1 Hz, 180 s | 153 | 429 | 81 | 0.1211 m |
| Primary 1 Hz / nominal 0.15 m/s, 300 s | 252 | 733 | 126 | 0.1960 m |
| Primary 1 Hz / nominal 0.20 m/s, 300 s | 257 | 746 | 192 | 0.2661 m |

The two 300-second runs differ only in configured nominal Navigator speed. The
0.20 m/s profile increased the measured translation lower bound by about 36%
and executed 192 commands versus 126. The largest commanded linear speed rose
from 0.108 to 0.117 m/s; curvature, acceleration and source-age caps still
prevented commands from reaching 0.20 m/s.

The 180-second experimental run reached a navigation-map revision of 388. At
shutdown its latest M3 revision 69 was accepted; M5 revision 63 was paired with
that latest M3, fresh, and contained one valid polygon. Rebuild processed 69 of
153 primary candidates (84 queue drops), compared with 46 of 340 candidates in
the previous 180-second baseline. The final navigation decision was `tracking`
with `route_available=true`; 17 decisions stopped for stale depth. Of 427
control invocations, 81 executed and 319 returned `navigation_source_pending`.
The navigation lane is faster, but the exact current capture is still not ready
for control on most iterations.

## Verification and limits

- Local preflight: `ready=true`, `issues=[]`, exit 0.
- 60-second smoke strict checker: exit 1 because the sandbox Qt UI could not
  connect to `DISPLAY=:0`; M3/M5 were fresh and one M5 polygon was valid.
- 180-second offscreen run: raw recording complete (582/582); all workers shut
  down cleanly; UI process clean. Strict checker: exit 1 solely because run
  outcome was `incomplete`, not because of M3/M5 geometry or freshness.
- Resource measurement completion was false: RSS support 552/587, 32 truncated
  samples, and 75 missing-process observations in provider diagnostics. The
  outcome therefore remains incomplete under the current measurement contract.
- The offscreen run did not display a live window. It is runtime evidence for
  faster movement and fresh M5, not an acceptance pass or room-traversal proof.
- The 300-second nominal-0.20 run recorded 1,003/1,003 frames and shut down the
  workers and UI cleanly. Latest M3 r143 was accepted, M5 r136 was fresh, and two
  valid regions passed polygon checks. The checker rejected only the `incomplete`
  run outcome: RSS support was 1,003/1,028 samples (21 truncated; four
  missing-process observations in the resource report). The 0.15 m/s comparison
  run also had fresh M5 with two valid regions, but was incomplete.

## Rejected navigation-stride candidate

A separate 60-second offscreen smoke changed only the NavMapper
`sampling_stride` from 1 to 2 on top of the primary-1-Hz profile. It reached 390
navigation captures and 388 control calls (about 6.5/6.5 Hz), but every one of
the 381 matched control decisions stopped with
`robot_not_on_observed_free_cell`; there was no accepted motion, no reachable
frontier, and no room M3 acceptance/M5 region at shutdown. The strict checker
rejected it for missing accepted M3 and stale/absent M5. This configuration is
discarded for demos; do not combine the navigation stride change with the
primary-cadence improvement.

Artifacts:

- 60-second smoke: `.runtime/local-room-motion-00805-20261103/primary-1hz-smoke-60s/run/`
- 180-second run: `.runtime/local-room-motion-00805-20261103/primary-1hz-smoke-60s/primary-1hz-live-demo-180s/run/`
- 300-second nominal-0.15 run: `.runtime/local-room-motion-00805-20261103/primary-1hz-smoke-60s/primary-1hz-live-demo-300s/run/`
- 60-second nominal-0.20 smoke: `.runtime/local-room-motion-00805-20261103/primary1hz-speed02-smoke60/run/`
- 300-second nominal-0.20 run: `.runtime/local-room-motion-00805-20261103/primary1hz-speed02-demo300/run/`

Reproduce a visible local run on a desktop with a working Qt display:

```bash
env -u QT_QPA_PLATFORM PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMBA_NUM_THREADS=1 \
NEUSYMNAV_DEMO_CONFIG=.runtime/local-room-motion-00805-20261103/primary1hz-speed02-smoke60/config-00805-primary1hz-speed02.local.json \
bash tools/run_local_demo.sh 300 \
.runtime/local-room-motion-00805-20261103/primary1hz-speed02-demo300/visible-run
```

The 300-second command is for a visible exploratory demo on a desktop with a
working display. With the current resource-sampler gaps, a longer run may still
be marked incomplete and fail strict acceptance. Do not raise the 0.2 m/s limit,
300 ms source TTL or 100 ms action horizon. Primary capture at 1 Hz is an
experiment, not a new production default; room-boundary coverage during
meaningful traversal remains unverified.
