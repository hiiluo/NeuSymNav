# Hydra branch2 H4 — worker session, backpressure and recovery

Date: 2026-11-04. H0–H3 remain in the isolated `Kiet_branch2` worktree.

## Implemented

- `HydraSession` starts one child process per episode and exposes nonblocking
  `offer`, cached `snapshot`, and bounded `close`. The native binding imports only
  in `backends/hydra/worker.py` inside that child.
- Admission uses one in-flight frame and at most one pending frame. A newer live
  offer replaces the pending frame and records both source keys/reason; request
  bytes are measured after JSON protocol wrapping. In-flight plus pending must fit
  32 MiB. Offline replay is ordered and lossless.
- A journal records queue/replacement/drop, exact selected `HydraFrame` payload,
  accepted or rejected step, failure, and cumulative prefix hash. Its 2 GiB default
  quota is enforced before native work; graph assets have a separate 128 MiB cap.
  `step=False` never increments graph revision. A fresh child can replay the latest
  accepted run prefix from the journal.
- Child stdout carries protocol messages only; stderr is drained into a 64-line,
  4 KiB-per-line tail. Worker timeout and close timeout kill the process group and
  return incomplete/replay-required status. Counters include candidates, queue,
  replacement, start, accepted, rejected, dropped, fps-limited and failure. Stats
  report request bytes, queue/service percentiles, source-age percentiles when the
  caller supplies a matching clock domain, sampled worker RSS, journal bytes and
  quota.
- The child loads the committed custom labelspace/config, rejects calibration or
  source-clock changes within an episode, steps Hydra in the background, and saves
  a native `.sparkdsg` asset at close. Explicit Hydra config values cap the TSDF and
  mesh integrator at two threads; the child environment caps BLAS/OpenMP at one.

## Verification

- RED/GREEN fake-worker suite covers nonblocking offer, latest-pending replacement,
  accepted/rejected revision accounting, sleep30s/timeout, crash, malformed and
  oversized replies, queue/byte limits, wrong episode, repeated frame, fps limit,
  journal quota, clean/overdue close, and selected-prefix replay.
- Focused CPU command: `.venv/bin/python -m pytest tests/test_hydra_session.py
  tests/test_hydra_labels.py tests/test_hydra_contracts.py tests/test_hydra_input.py
  tests/test_contracts.py -q` — **135 passed**, exit 0. `git diff --check` — exit 0.
- Native child-process smoke used a shell command that sourced only the branch2
  child environment. `offer` queued without waiting; one real `hydra_python` step
  was accepted; close saved and Spark-DSG reloaded the graph; child exited 0. The
  configured TSDF `num_threads` and mesh `integrator_threads` appeared as `2` in
  native logs. The worker metadata reported Hydra source commit
  `2e58a35baea629eee8838409771876acff015daf`, binding SHA256
  `d4fe28b63aa63a5dcc730473ea727c2015c981623f38bf10ae592251c18a8d5d`, and config
  SHA256 `a76b01f3a96057012354fef1e55f9623e0195b435112438e80240567af549011`.
- A fresh native child replayed the journaled accepted source prefix. Source key,
  graph revision (`1`), input-prefix SHA256
  `6169abf7f3fa6f40609b84993d55f4a834ebc1eead7b8d15a82aacfd1b568004`, and saved
  graph SHA256 `c551766bb50ae2421b9825c2cf5c42471938e28fdf3bc7f7abac4784c1029979`
  matched the first process. Spark-DSG reload read 450 mesh vertices. This proves
  exact selected-prefix process replay for the captured one-frame sequence; it does
  not prove live coordinator restart behavior or navigation resilience.

| Artifact | SHA-256 |
| --- | --- |
| Focused CPU test log | `de57e6316383b46bf874ceb16dfe3c8f999d985616fb11c2d71ba5fa1d31b965` |
| First native graph | `c551766bb50ae2421b9825c2cf5c42471938e28fdf3bc7f7abac4784c1029979` |
| Replayed native graph | `c551766bb50ae2421b9825c2cf5c42471938e28fdf3bc7f7abac4784c1029979` |
| First run journal | `923a1bb8bc78a61f0dacfc5177df4612111e85cc69f7c6f3dd9b4b715fe901fd` |
| Replay journal | `9636e3ece93975df3be0b47023f1669e860614d5bb4fd90217ed48beef42549a` |
| Native dataset config | `a76b01f3a96057012354fef1e55f9623e0195b435112438e80240567af549011` |
| Session implementation | `b5efe3eb14e49fc900efec92bfd74aff07c177323fd2b879a666e8ce3fbd2910` |
| Child worker implementation | `5129ed362b607bf53fe7d5bef11c0ad69d4f3d5782ccec2a7df1dca1305e13ea` |

Key ignored artifacts are in `.runtime/hydra_ws/artifacts/h4-worker-smoke/` and
`.runtime/hydra_ws/artifacts/h4-cpu-tests.log`. The native smoke graph has 450 mesh
vertices and zero object/place/room nodes because it is a one-frame transport/lifecycle
probe; H3 native fixtures separately prove those layers. No coordinator or UI was
connected.

**Implemented:** bounded session/worker protocol, journal, native child worker and
restart replay helper.

**Correctness-verified:** 135 focused CPU tests; child-process native step/save/
reload/shutdown and selected-prefix replay passed; configured thread counts were
read from native logs.

**Runtime-validated:** isolated native worker process only. NeuSymNav coordinator
admission, backpressure under live sensing, movement non-regression, UI/export,
live navigation and A/B remain for H5–H7.
