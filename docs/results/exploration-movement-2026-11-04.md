# Exploration and movement — 2026-11-04

Scope: improve measured exploration on scene00805 without changing the accepted
Rebuild M5 room backend. All runtime variants, including regressions and failed
runs, are retained under `.runtime/movement-improvement-20261103/`. This is a
movement investigation and implementation report; it does not close P10.

## Findings and changes

The frontier selector was only one contributor. Exact navigation-source waits,
serial capture/map work, a slow virtual acceleration ramp and unnecessary yaw
all reduced useful translation. The Habitat actuator divides its100ms budget
between translation and yaw when both are requested. Small mixed legacy
commands therefore made little forward progress. A second, reproduced corner
defect compared a14cm controller preview against an actual pulse of at most2cm:
the controller vetoed a pulse that the unchanged MotionGuard accepted.

Implemented changes:

- Bounded gain/heading-aware frontier ranking, up to8 viewpoints per component,
  and a0.6m preference for a new goal when a farther reachable goal exists.
  Committed goals keep normal hysteresis, replan on each current map, and avoid
  repeating full frontier extraction while tracking.
- Origin-only rolling preserves the acceleration state. Live acceleration is
  configured to0.6m/s² with unchanged0.2m/s hard speed limit. One-axis bounded
  yaw/translation removes residual yaw from aligned forward commands.
- Controller preview follows the actual bounded pulse near a corner. The
  original guard, footprint, unknown/free distinction and collision filter remain.
- Commands are issued after synchronous geometry validation, with deadline still
  bounded by ORIGINAL depth/map capture+300ms and issue+100ms.
- An expired capture is retained in the raw recording and skipped for control;
  the owner captures fresh data. Other pose/provenance failures remain fatal.
  UI observations retain source identity across the pre-admission callback.
- Live runner uses NavMap10cm, primary RGB-D at most1Hz and navigation cadence
  unchanged. Rebuild room input remains5cm and backprojection stride1, with the
  existing pinned M1–M5 source/binaries. No simulator occupancy seeds the map.
- Optional same-sensor fresh-map lag and measured-only local coverage were
  evaluated. The live experiment increased bootstrap cost and expirations;
  map lag remains disabled. This negative result is retained.
- An opt-in hybrid regulated-pursuit mode combines gentle steering and forward
  motion, clears yaw inside6°, and aligns in place above50° until below25°.
  It is mutually exclusive with discrete mode; actuator and guard are unchanged.

No ROS2 dependency, external planner, new model, install or sibling-repository
modification was required. Replacing only the frontier source would not address
the measured source-wait and pulse-execution bottlenecks.

## Retained native observations

These are single runs, not statistically repeated benchmarks. Driver exit0
alone is not success: the diagnostic driver prints the launcher outcome and
may return0 for a failed/incomplete run. Sampled-pose path and native action
translation are reported separately in `movement-results.json`.

| Artifact | Requested duration | Action translation | Interpretation |
| --- | ---: | ---: | --- |
| `baseline-run` |30s|unavailable|EGL startup failed with forced software rendering; retained |
| `baseline-egl-run` |30s|0.179m|legacy baseline, completed |
| `improved-run` |30s|0.507m|early discrete experiment, completed; about2.8× baseline |
| `improved-90-run` |90s|0.661m|before extraction/ramp fixes |
| `diverse-fast-60-run` |60s|0.765m|more reachable viewpoints, before farther-goal preference |
| `fresh-map-60-run` |60s|0.086m|regressed; optional lag disabled |
| `long-goals-120-run` |120s|0.770m|fine NavMap source-wait bottleneck |
| `nav10cm-60-run` |60s|1.068m|coarser navigation only; room input unchanged |
| `final-90-run` |90s|1.556m|faster ramp, before bounded-yaw fix |
| `final-yaw-90-run` |90s|1.538m before failure|stopped early on expired body-pose source; not a90s result |
| `final-recovery-90-run` |90s|1.560m|expired-source recovery tested; corner veto remained |
| `final-corner-90-run` |90s|1.527m|no corner veto;2 reached goals,3 goal IDs; full observation |
| `hybrid-90-run` |90s|1.826m|hybrid, about20% above discrete;3 goal IDs, full observation |
| `hybrid-300-run` |300s|2.663m|4 goal IDs; map latency degrades, sustained goal unmet |
| `hybrid-primary05-90-run` |90s|2.205m|primary0.5Hz; improved short run, still degrades over time |

`final-corner-90-run` intentionally delays one real navigation capture350ms
without changing its timestamp. It records exactly one expired-capture health
event,427/427 raw sensor frames, no worker failure/error and clean shutdown.
M3 accepted/latest revision14; M5 revision11 has2 valid, fresh regions.
RSS sampling has479 samples/support476/truncated1; measurement completeness
therefore remains unresolved. Strict checker exits1, `accepted=false`, reason
`run outcome is 'incomplete', not 'completed'`. The checker was not weakened.

## Verification and remaining work

Pre-hybrid full CPU suite:2362 passed,10 skipped, exit0 in169.33s
(`full-suite-final.log`). A prior full run found7 failures: the real UI ordering
regression was fixed; constructor fakes were replaced with actual Navigator and
MotionGuard; an asynchronous fixture now explicitly waits for its first commit.
Earlier failing logs are retained. Hybrid/config/core/corner/continuity integration:
33 passed, exit0 (`hybrid-integrated.log`); configuration/profile subset71 passed,
exit0 (`hybrid-config-green.log`). Luna's initial hybrid RED/GREEN terminal
outputs were not persisted; main independently saved the integrated GREEN run.

Independent Terra review of frozen hybrid controller SHA256
`fe7727f3095e1d6cdb90e6f352c5d89b513b7b3bb68cf8d3d87f2e1a1d1c6e22`
found no actionable safety regression by static inspection. It did not execute
tests or establish runtime validity. Full source manifest:
`hybrid-source-hashes.json`. The90s hybrid run has no runtime error, a complete
420-frame raw recording and clean shutdown; M3 accepted/latest13, M5r10,
2 fresh regions. RSS470 samples/support463/truncated4 means strict completeness
is still unresolved. A300s hybrid run and final suite/report update are pending;
no performance-completion claim follows from the unit tests.

The completed300s observation (`observed_pose_span_s=300.130`) exposes a remaining
performance failure: map median service rises from92ms early to242–269ms later;
map source age reaches300–338ms. There are400 pending-source results in896
control invocations. Forward commands still request median0.2m/s, but60–180s
commands have median source age241–243ms and only57–59ms evidence lifetime left.
The mixed executor spends roughly half that lifetime translating. No curvature
change is justified by this evidence. M3 accepted/latest39, M5r34,2 fresh regions;
raw1167/1167 frames, clean shutdown, no runtime error, outcome incomplete.

Isolated real early/late-frame replay with four raycast workers takes42–45ms
median; one worker takes81–92ms and is not selected. These samples warm only six
preceding frames, not full run history, and do not establish the absence of a
history-related cost. Both capture and map slow in live runs, indicating possible
shared CPU/scheduling pressure. Profile artifacts: `nav-300-{early,late}-{1,4}.prof`.

The300s UI publication is11,936,850 bytes, including about9MB of detector
observation data. Isolated `encode_publication` costs153–168ms; cProfile records
887k recursive dictionary-encoder calls. On the same already encoded packet,
Python streaming JSON takes114ms versus51ms for the C encoder. A bounded C fast
path with exact streaming fallback is under implementation; byte-budget and
wire-equivalence regressions are required before another native comparison.
No map fidelity or TTL reduction is selected from this diagnosis.

The prior90s result remains too small to establish the user's sustained-coverage
objective. Native runs use offscreen Qt; no visible UI validation is claimed.
Long-run coverage, other scenes and strict resource completeness remain unproven.
