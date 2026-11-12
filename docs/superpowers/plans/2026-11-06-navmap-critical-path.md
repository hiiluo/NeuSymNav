# NavMap critical-path reduction

User authorizes implementation and measured freshness target below5%, as low as feasible.
Scope Kiet_branch2 only; no promises for arbitrary run length. Preserve300ms source
TTL,100ms horizon, unknown/free and original full measured evidence/Hydra/frontier policy.

## Design and alternatives

1. Exact ROI traversal (first): rolling currently computes all full-frame ray votes
then crops. Compute only the samples able to contribute to retained planar/height
cells, keeping original sampling lattice and endpoint/lastvoxel exclusion. This
changes neither planner nor guard contracts. Main implementation choice.
2. Separate local-depth clearance/control lane from asynchronous planning: larger
contract change (distinct planning/safety sources, path following and proofs).
Retain as next option if exact reduction is insufficient; do not silently bypass
map floor/height or full intent-path validation.
3. Relax TTL or stride: excluded; prior stride2 removed bootstrap evidence.

## Execution

- [ ] Capture RED tests: independently crop original full ray masks; compare exact
  bounded masks for adversarial boundaries, negative axes, no-return, endpoint
  veto/lastvoxel, varied dimensions, parallel workers, Python/Numba.
- [ ] Implement optional bounded CPU traversal, prewarm signatures; legacy/custom
  collectors unchanged. Compare actual recorded snapshot fields/source exactly.
- [ ] Serial paired replay timing and independent review. Run focused/full tests.
- [ ] Native UI-on30/120/300 then600 if safe/beneficial; no concurrent workload.
  Complete recording/trace/proofs/cleanup mandatory. Preserve denominator incl
  stale stops. Report whole-run and last-window freshness, progress not coverage.
- [ ] If insufficient, record evidence and implement subsequent justified reduction
  rather than force5% via TTL or scoring. Update status/report limitations.

Artifacts `.runtime/navmap-critical-path-20261106/`. Main owns production/contracts.
Luna xhigh read-only audit/review. No commits or dependency changes.

## Evidence-based extension: capture GC window

ROI alone: native30 .917%,120 .743%,3007.075% (targetFAIL); temporal300
windows2.09/8.28/12.56%. Exact ray correctness holds but not sufficient longlive.
GCtimestamp-only diagnostic3002.169%/7.102m (runvariance); activegen2 max130.555ms,
3of47 refusals overlapgen2>=20ms. This is a contributor, not solecause.

Main ruling: opt-in Hydra-only `runtime.defer_capture_gc` schedules full cyclic
collection before a fresh sensor request, once/second, and disables automatic
cycliccollection solely during capture→mapwait→synchronouscontrol/measurement.
Restore previous GC state on all exits. Reference counting and original capture/
TTL/horizon remain. Fullcollection pauses allhostPythonthreads and consumes run
budget, so require progress/interval measurements alongside freshness. No global
indefiniteGCdisable; no legacyassociationdecorator interaction (trueflag rejected
for legacybackend). Diagnostics bounded1024collectionevents plus total/dropstats.

Correctness: RED missing module;56focusedGREEN; finalfull2655pass/10skip exit0,
187.54s. Newsourceclosure gc-source-hashes.json; earlierROIclosure retained.
IndependentLuna xhigh review no blockingfinding. Native30/120/300 ongoing;
30 completed0,0/211refusals,1.606m,allproofs/timingcomplete. Do not promote before300.

600 instrumentation limitation: current512MiB/65536 trace-record ceiling may
truncate a600s run at observed eventrate. Do not claim whole-run600refusals from
truncated trace or silently change sampling/denominator/caps. Assess actual300
capacity;600 may remain unverified requiring a separate complete-trace design.

### Local lane continuation (authorized same scope)

ROI/GC repeat300s failed103/1303=7.90%; do not promote GC profile.
Implement opt-in measured-depth local lane with independent local map revisions,
immutable world intent(originalcapture expiry2s), no wait for exactworldmap.
Current depth guard300ms/horizon100ms unchanged. Diagnosticv2 binds both sources;
null intent requires STOP. Add local map/follower/guard/worldintent timing stages.
Independent review and regression fixes completed (transient blockage recovery;
old-intent expiry cannot clear newer intent). Next: fullsuite; isolated native
30/60/120/300s; score actualallinvocations, executedproofs, movement, intent starvation,
complete traces. Repeatlongrun before claiming stability; no universal guarantee.
AuxiliaryGCprobe capped10,000events; observed3overlaps lowerbound only.

### Availability recovery + cadence continuation

First local30s had0/275 freshness but0m: world no-path outcomes were not observed
by watchdog once local intent disappeared. Fixed, real-Navigator regression passed;
repaired native30/60/120s:0%,2.74%,3.17%, movement1.48/2.55/4.78m.
Optional runtime.world_navigation_hz waits outside locks before newest-source dequeue;
localmodeonly<=10Hz. Cadence/local/telemetry/launcher112focusedpassed/exit0.
2.5Hz worldmap /10Hzcapture ceiling:30s.40%/.647m;120s3.79%/4.974m.
Full final suite and300s next; no guarantee on every run/length/map.

### Measured local raycast parallelism

World2.5Hz300s7.34%;fullrate local1worker300s6.96%;combinedGC120s5.32%;
control5Hz120s0% but.649m -> availabilityFAIL. Do not promote failed profiles.
CPUprofile50frames isolates raycast20/36ms; paired51sources1/2/4workers exact,
p95local39.97/33.08/28.15ms. Optional local_raycast_workers1..4/default1,
126focusedpassed/exit0. Native4worker30/120s.85/3.30%,1.80/5.69m;
300s running, finalfullsuite/strictallruns/sourceclosure still required.

### Final checkpoint

Parallel4 native300s13.32%/5.977m failed, option/wiring removed; archived source
under local-lane/parallel-source. Final2706pass10skip/255.46s/exit0; all15native
runs/9364controls strict inspected, collectorcomplete/no drops/prooffaults, hashes
match, diffcheck0. No long-ready promotion; under5% long objective FAIL. Detailed
nextprocess-isolation direction and limitations in results report. Existingdefault
unchanged, experimental local-depth config only. No600s, no commit/push.
