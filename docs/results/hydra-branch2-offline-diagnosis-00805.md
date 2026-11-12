# Hydra branch2 — offline diagnosis of smoke 00805

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Scope

Analyzed the existing 30 s artifact
`.runtime/hydra_ws/artifacts/hydra-stage-profile-jitwarm-00805-30s-20261104/`
only. No simulator was started and no motion, freshness, sampling, or worker
configuration was changed.

## Findings

### Why there were only two semantic/Hydra inputs

The primary stream registered 95 frames. Capacity-deferred sampling reports 78
frames deferred while the scheduler was at capacity, 17 policy evaluations, 15
policy-unselected frames, and two offers. The offers were primary RGB-D frames 0
and 76; each was durably accepted and processed by Hydra. There were no rejects,
replacements, or stale admissions.

Capture-to-detector-return took **22.74 s** for frame 0 and **1.83 s** for frame
76 (two samples; reported distribution p50 12.28 s, p95 21.69 s). The first
frame's delay is consistent with lazy detector/model startup; a separate offline
profile on this same profile measured 22.93 s worker initialization, including
21.37 s model/encoder load. That timing comparison supports the startup-delay
interpretation but does not prove exactly how much of frame 0's live delay was
initialization. Hydra then spent **5.50 s** and **4.88 s** on the two inputs.
Both were accepted. The graph snapshot reached revision 2, but the measurement
artifact reports zero live detector commits, zero live object-evidence commits,
and no object IDs. Thus “processed” here means the inputs reached Hydra; it does
not establish useful semantic objects or an exportable hierarchy.

The live detector's second capture-to-return latency (1.83 s) is close to the
previous offline warm CPU inference range (p50/p95 1.30/1.87 s). The evidence
points to two separate throughput costs: first-frame initialization and then
roughly multi-second CPU detector/Hydra work. The 30 s run therefore spent most
of its useful window on startup and two serialized inputs.

### What the 33 `expired_or_zero` outcomes mean

The outcomes are consecutive source frames 3–35, with recorded depth ages from
**76.5 to 171.1 ms**. None crossed the 300 ms depth freshness limit. In
`HabitatMotionAdapter.execute`, `expired_or_zero` is returned only when the
command deadline has passed or both `linear_mps` and `yaw_radps` are zero.
There are 62 accepted actuation proofs for the 62 `executed` results and 33
missing proofs for the generic outcomes. The artifact does not preserve the 33
commands' velocities, issue/deadline timestamps, or upstream reasons, so it
cannot distinguish deadline expiry from zero commands per invocation.

The same run reports 32 navigation decisions with reason
`committed_goal_blocked:goal_not_traversable`; this count nearly matches the 33
generic outcomes and is consistent with MotionGuard zeroing a blocked route.
This is the strongest explanation for most outcomes, but the artifact does not
bind those navigation reasons to the individual 33 records. A deadline-expired
case, or another zero-producing reason, remains possible. The age values rule
out the 300 ms stale-depth gate as their cause; they do not rule out the separate
100 ms command horizon.

## Next work

Before another simulator run, make bounded per-invocation actuator diagnostics
retain the command source, issued/deadline/execute timestamps, linear and yaw
values, upstream `MotionCommand.reason`, and actuator result. This will separate
zero commands from command expiry without loosening the 100 ms horizon or the
300 ms source gate. Address detector initialization/readiness before admitting
the first fresh capture, then profile one warm detector-to-Hydra handoff from
the existing recording. A longer simulator run should stay gated until those
two measurements explain the observed throughput and control outcomes.

## Evidence and verification

- `summary.json`: 192 total frames, Hydra offered/processed 2/2, detector calls
  2, durable accepted 2, zero live detector/object evidence commits, zero object
  IDs, `outcome=incomplete`, `native_runtime_validated=false`.
- `measurements.json`: 95 control events; 62 `executed`, 33 `expired_or_zero`;
  95 depth ages; 62 proof records and 33 missing command proofs; semantic sample
  counters `seen=95`, `deferred_capacity=78`, `policy_evaluated=17`,
  `policy_unselected=15`, `offered=2`.
- `hydra/journal.jsonl`: frames 0 and 76 each recorded `queued`, `started`, and
  `accepted`; service times 5,503.4 ms and 4,876.6 ms.
- `control-invocations.json`: 95 results; no missing runtime result. Its
  aggregate result field does not include individual command fields.
- Source check: `src/neusymnav/sensors/habitat_worker.py`,
  `HabitatMotionAdapter.execute`; coordinator result observation in
  `src/neusymnav/runtime/coordinator.py`; collector binding in
  `src/neusymnav/runtime/observability.py`.
- Offline JSON/artifact audit: exit 0. `git diff --check`: exit 0. No tests were
  run because this change adds only a diagnosis report and status entry; no code
  behavior changed.
- Runtime validation for this task: **not run**. The cited 30 s smoke is the
  pre-existing artifact, not a new validation.

Implemented: offline forensic diagnosis and status update. Correctness-verified:
artifact counts and source-level result branches cross-checked. Runtime-validated:
no new validation; overall Hydra live acceptance remains incomplete.
