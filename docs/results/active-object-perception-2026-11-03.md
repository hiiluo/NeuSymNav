# Active object perception: development checkpoint, 2026-11-03

The opt-in prototype is wired into the runtime. The frontier-only default and
object admission default are unchanged. No models, mounts, robot geometry,
safety deadlines, canonical ID authority, or live semantic inputs were changed.

| Work package | Result |
| --- | --- |
| Q0 | Fixed development cohort 00861: 57 paired frames, 230 scoped observations, 25 GT identities. All selected bindings and referenced assets verified; raw certificate 4,669/4,669. No independent exhaustive active-graph GT cohort. |
| Q1 | Replayed B0 through the existing owner and admission policy on the same 57 inputs; all projected boxes/decisions match retained baseline. Ran matched-label replacement through the real offline owner, preserving masks, projections and image embeddings. O-ID is a post-hoc assignment diagnostic. Ran scoped O-mask/proposal replay with real projection, owner and same-recipe CPU appearance encoding. |
| Q2 | Bounded committed view metadata (6 views/object, 256 objects, 64 MiB charged metadata), deterministic alias handling, source watermark, raw scores and angular/position diversity. No added probability or verifier. |
| Q3 | Bounded request queue and fixed optical mount proposals (max 12); observed-free reachable poses, FOV and geometric visibility prediction, world-coordinate revalidation. |
| Q4 | Off/shadow/active modes, one arbiter and existing Navigator/MotionGuard, frontier suspend/resume, async bounded planner, exact fresh capture/commit ACK, UI/export status and trace. |
| Q5 | Same-input passive B/M retention replay completed. B/M/R/C profile candidates and protocol are available, but native pilot is gated on suitable GT. |
| Q6 | Promotion unavailable. No exhaustive held-out scene/start pairs or native matched-budget R/C outcomes. |
| Q7 | Not started. The partial oracle evidence does not isolate proposal recall as the dominant causal bottleneck. |

### What the data says

The denominator of 230 is fixed only within the partial development annotation.
Detector box matching yields 74/230; independently matched projected owner
objects yield 90/230 and 8/25 globally one-to-one identities. Applying current
admission gives 55/230 and 5/25. These are independent stage matches, not a
nested causal funnel. Unmatched predictions have unknown annotation scope.

The O-label owner replay made 74 matched label overrides. With admission off,
the matched projection label count rose from 59 to 86 of 90; under admission,
from 29 to 53 of 55. Matched observations and one-to-one identity counts did
not change. This establishes a label sensitivity result only; it does not
estimate the gain from changing the detector, active capture or proposals.

The O-mask/proposal replay replaced 74 matched masks, added 156 scoped GT
mask proposals, and retained all 70 unmatched original detections. All 239
valid projected crops were encoded again with the pinned ViT-B/32 recipe
and matched the baseline feature-space ID. Projected matches went from
90 to 172/230 and one-to-one identities from 8 to 19/25. Under the current
admission rule the diagnostic is 76/230 and 6/25. Added proposals have
unknown labels and a fixed .25 score, and partial masks disable negative
visibility evidence. This jointly changes mask quality and proposal support;
the admission result is not an isolated mask effect. It motivates a future
proposal-vs-mask split, not a Q7 or default promotion decision.

Passive B/M shares all 109 valid committed views in the 57-frame subset,
using final canonical aliases. B retains 51 views and M retains 41; under
the same 0.3 m / 15-degree criterion, B retains 13 independent pairs out of 26
and M retains 13 out of 13. M's charged metadata is 136,951 bytes. Neither
branch changes admission. This is stricter filtering with fewer retained
views, not evidence of improved recall, precision, or utility.

### Implementation and operational limits

- Experimental profiles use the identical 00861 base detector, CG+Visual, body,
  cameras and capture budgets. M is shadow; R prefers predicted novel views;
  C takes the cheapest feasible viewpoint from the same eligible queue. The C
  prototype does not yet demonstrate matched realized motion or inference use.
- A request receives at most one active slot, 3 attempts per object, a 10-second
  attempt, 30-second request lifetime and 20% elapsed episode wall-time budget.
  Proposals are sampled at one radius and can miss feasible viewpoints.
- Arrival tags a primary frame at the existing cadence; receipt of a frame or
  a guard refusal is not evidence. A matched, fresh, committed independent view
  is required. Missing coverage, an unavailable planner or failed evidence
  preparation cannot be turned into a motion exemption or a negative vote.
- View metadata is derived from the durable owner ledger. Offline replay
  rebuilds the cache and tests replay idempotency. Native restart recovery of
  the entire derived cache and request budget is not validated.
- The preflight and CPU checks are not native latency, resource, or quality
  certification. No active pilot, confirmation campaign, training, download
  or publication was launched. The mask oracle used the existing CPU encoder.

### Reproduction

Artifacts are under `.runtime/active-object-perception/`: Q0 source/GT
inventory and fixed denominators, Q1 retained and owner-oracle reports, Q2
memory tests, Q3 request/viewpoint tests, Q4 config preflight, source hashes,
review and CPU logs, Q5 same-frame retention results and campaign protocol.

```sh
PYTHONPATH=src QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  .venv/bin/python -m pytest tests -q -rs -m 'not native'
PYTHONPATH=src .runtime/host/bin/python -m neusymnav.cli preflight \
  --config configs/p10/active-perception-memory-00861.json
```

Use `tools/evaluate_active_perception.py --help` for Q1; the label-owner
replay takes the checkpointed source ledger. Use `tools/replay_mask_oracle.py --help`
for the offline mask/proposal oracle with the pinned CPU encoder. Use
`tools/replay_active_view_memory.py --help` for the B/M retention replay.
The previous partial-GT data cannot be promoted into a held-out evaluation.


Verification: Q0 inventory exit 0; B0 exact replay, O-label, O-mask and
passive B/M each exit 0. Three native-profile preflights exit 0.
Q4 focused post-review suite: 85 passed, exit 0. Full CPU suite:
2,371 passed, 3 skipped, 9 native deselected, exit 0 (145.38 s).
The later offline-only mask hook was checked with the real 57-frame replay
and a focused 27-test evaluation/runtime regression suite, exit 0.
Independent Terra High source review accepted the Q4 integration after
four findings were fixed. GPU inventory found an idle RTX 3060, but native
quality pilot remained gated on suitable annotation; no GPU workload ran.
