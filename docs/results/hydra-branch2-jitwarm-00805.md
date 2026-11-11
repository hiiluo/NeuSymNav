# Hydra branch2 — CPU raycast JIT warm-up, map 00805

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Change

The CPU raycast kernel is compiled with Numba `njit(cache=False)`. Previously,
the first call happened inside the navigation update thread, so compilation
blocked the first map and caused captures to expire before an exact map was
ready. Pipeline setup now compiles the kernel's exact runtime signature before
creating pipeline workers or accepting fresh control captures. It uses Numba's
dispatcher `.compile(signature)`; it does not execute a synthetic ray or add
evidence to the map. If Numba is unavailable, the CPU Python fallback remains
available and startup metadata reports `numba_warmed=false`.

The warm-up duration and status are included in
`worker_runtime.navigation_mapper_startup`. The mapping algorithm, source TTL,
raycast worker count, sensor settings, and movement profile were unchanged.

## Offline verification

On the exact recorded `downward-depth/frame-1` source, a fresh Python process
started with no Numba dispatcher signature. The explicit warm-up compiled the
signature in **1,397.2 ms wall**. The first map update after warm-up then took
**101.9 ms wall**, compared with the previous cold first update of 1,793–1,738
ms in offline replays and 2,102.2 ms in the live trace. This puts the one-time
cost in setup and keeps it outside the source's 300 ms freshness interval.

## Bounded live smoke

Ran one 30 s smoke using the same calibrated 00805 profile and unchanged motion
settings. The runtime reported the warm-up completed in **1,269.6 ms**. Across
96 NavMap updates, p50/p95/max was **65.4/121.8/148.9 ms**; first update was
**79.6 ms**. Exact-navigation wait p50/p95/max was **66.1/122.4/150.5 ms**.
No NavMap update exceeded the 300 ms TTL. Control recorded 62 `executed`, 33
`expired_or_zero`, and zero `navigation_unavailable` reasons. The previous
pre-warm profile had a 2.102 s first map and three exact-map waits that expired
while the worker was busy.

The smoke recorded 192 frames, had no runtime worker failures or publication
mismatch, and shut down cleanly. It nevertheless ended **incomplete**, exit 1:
Hydra processed only 2 inputs and coherent hierarchy/map export was unavailable.
`native_runtime_validated=false`. JIT warm-up resolves the cold first-map stall;
it does not resolve semantic/Hydra throughput or the 33 `expired_or_zero`
control outcomes. Those remain separate follow-up issues.

## Verification

- TDD RED: 3 targeted tests failed because the warm-up API and pipeline call
  were absent. GREEN: the same three tests passed, exit 0.
- Focused map/launcher suite: **70 passed, 3 failed**, exit 1. The three failures
  are unrelated existing UI worker SHA assertions in baseline,
  geometry-only, and appearance profiles (`2e6cec…` expected vs
  `310ae171…` actual).
- Full non-native CPU suite before evaluator follow-up exposed eight failures;
  five were attributable to new `stage` telemetry not being accepted by the
  offline evaluator and sensor deadline clock fakes missing `monotonic_ns`.
  Added strict evaluator validation for source-bound stage name and interval,
  and completed the fake clock. Six focused evaluator/deadline regression tests
  then passed, exit 0.
- Final full CPU command:
  `.venv/bin/python -m pytest tests -q -m "not native"` — **2426 passed, 3
  failed, 1 skipped, 9 deselected**, exit 1, 181.87 s. The only remaining
  failures are the same three pre-existing UI worker SHA assertions noted above.
- Preflight: `bash tools/run_hydra_map_demo.sh 00805 --preflight` — ready,
  no issues, exit 0.
- Bounded smoke command:
  `bash tools/run_hydra_map_demo.sh 00805 30 .runtime/hydra_ws/artifacts/hydra-stage-profile-jitwarm-00805-30s-20261104`
  — incomplete, exit 1, clean shutdown.
- `git diff --check` and Python compilation were run after the code changes;
  both exited 0.

## Artifacts

- Smoke directory:
  `.runtime/hydra_ws/artifacts/hydra-stage-profile-jitwarm-00805-30s-20261104/`.
- `summary.json` SHA-256:
  `c70dd737d0702d6daaa76848e0b94d704f2b63896fce2cd7f81edd200eae49b1`.
- `measurements.json` SHA-256:
  `eda8712f4ce53fa0efedde8b9c222f1a26a18b1d0a16fcbecaffd472a5dfdff4`.
- `control-invocations.json` SHA-256:
  `6ff93cd19abff72ab32e02bd2f0b8b62f208eb5a4085dbab7753fcf3e7bec805`.

Implemented and correctness-verified: warm-up call, startup metadata, source-bound
stage evaluator support. Runtime-validated for this 30 s sample: the first map no
longer stalls past TTL. Overall Hydra live acceptance and useful semantic result
throughput remain unverified.
