# ConceptGraphs-inspired association — implementation and fixed-input result

Date: 2026-10-30. **Implemented and correctness-verified. The spatial-only
pilot shows no quality improvement. Full visual/native runtime remains unvalidated.**

## What changed

Added an opt-in `association.mode: conceptgraphs` recipe inside the existing
canonical owner. New observations are deterministically voxel-sampled; directional
nearest-neighbor overlap queries the complete bounded fused map cloud. Compatible
features contribute raw cosine similarity with a configurable physical bias.
One missing eligible feature triggers row-wide spatial fallback, avoiding mixed
score scales within an observation's candidate ranking. Thresholds and fallback
policy are versioned and persisted; they were not tuned on this pilot.

Hungarian matching, ambiguous/unresolved observations, cannot-link history,
floor/wall/centroid/AABB gates, canonical aliases and existing voxel fusion remain.
Legacy modes remain default. New-mode batches atomically retain diagnostics and
original online IDs even if later canonical merges retarget evidence endpoints.
Opening a populated ledger with a different recipe fails explicitly.

Usage: [configuration and launch instructions](../conceptgraphs-association.md).
Approved [design](../superpowers/specs/2026-10-30-conceptgraphs-association-design.md)
pins reference ConceptGraphs source bytes and documents algorithm differences.

## Fixed-input experiment

Original capture: `runs/demo-yoloe26m-640x480-gpu-20261030-104928-497271978/objects`.
Original prediction selection and semantic GT are the retained
`.runtime/quality-evaluation-20261030/` pilot inputs. No recapture, inference,
training, asset download or semantic-GT input to association occurred.

Read-only replay verifies typed source/batch/observation assets, original selected
order, timestamps, geometry, frame-local detection IDs and masks before output.
Original final ledger IDs do not initialize either replay engine. Both engines
consume the same17 original projected observations, after the same `advance_time`
calls using capture timestamps. All12 selected frames and all44GT observations
remain in evaluation;13distinct GT objects. Four of21detector outputs have no
typed projected observation and are explicitly excluded from this memory scope.
The original21-output detection baseline remains separate and unchanged.

| Metric | Legacy geometry replay | ConceptGraphs spatial replay |
|---|---:|---:|
| Online IDF1 | 32.79% | 32.79% |
| HOTA | 33.81% | 33.81% |
| AssA | 65.95% | 65.95% |
| DetA | 17.81% | 17.81% |
| LocA | 79.43% | 79.43% |
| IDTP / IDFP / IDFN | 10 /7 /34 | 10 /7 /34 |
| Generated identities | 8 | 8 |
| Unresolved / ambiguous observations | 0 /0 | 0 /0 |
| Conditional false-merge / split pairs | 0 /0 | 0 /0 |
| ID switches / fragments | 0 /0 | 0 /0 |
| Revisit recovery | Unavailable | Unavailable |

The identity partitions are exactly equal after ignoring arbitrary ID spelling,
not merely equal aggregate scores. No post-hoc merge is performed in replay;
online and final identities therefore coincide. This does not reconstruct the
original capture's unavailable online history. Pair diagnostics have only10
eligible pairs and switch/fragment metrics only6transitions; revisit support0.

The new scorer evaluated23eligible pairs (all spatial-only), made9matches and
created8IDs;11rows fell back because features were missing. No observation scoring
cap was reached. Maximum fused cloud size was1590points/object and4834total points
for both runs (4096point/object cap). These are cloud-support memory proxies,
not measured process peak RSS.

Single sequential replay `advance_time + ingest` totals: legacy145.29ms,
new150.83ms across all12frames. Asset decoding and output are excluded; method
order/cache state and one sample prevent a reliable latency comparison. This
does not measure native pipeline FPS, realtime throughput, GPU or peak RSS.

## Appearance availability and interpretation

Original typed observations have **zero appearance features**. The supported
OpenCLIP worker cannot run in the checked detector26 environment: `open_clip`
and `safetensors` are absent, as is the declared safetensors checkpoint. An
alternate local OpenAI ViT-B/32 `.pt` exists, but was not substituted for the
declared recipe. No model conversion, installation or download was performed.
Thus full spatial-plus-visual quality and speed comparisons are unavailable.
Compatible-vector synthetic tests prove scoring behavior, not real CLIP quality.

The result supports retaining this recipe as an experimental opt-in. It does
not support promoting it to default, tuning on this sequence and claiming a
held-out gain, or claiming association is solved. The pilot's detector misses
and absence of hard revisit cases constrain what matcher improvements can show.

Next quality experiments: add verified compatible appearance features to the
same fixed inputs; expand to held-out scenes with occlusion/revisits and close
same-class objects; audit missed doors/windows and taxonomy, then run fixed-image
detector PR/AP comparisons. No detector or taxonomy behavior changed here.

## Commands and evidence

```bash
PYTHONPATH=src .venv/bin/python tools/replay_association_quality.py \
  --objects runs/demo-yoloe26m-640x480-gpu-20261030-104928-497271978/objects \
  --predictions .runtime/quality-evaluation-20261030/native-preparation/predictions.json \
  --out .runtime/conceptgraphs-association-20261030/fixed12-replay

PYTHONPATH=src .venv/bin/python -m neusymnav.cli evaluate-quality \
  --gt .runtime/quality-evaluation-20261030/native-gt-overlay/ground-truth.json \
  --predictions .runtime/conceptgraphs-association-20261030/fixed12-replay/conceptgraphs_spatial/predictions.json \
  --out .runtime/conceptgraphs-association-20261030/conceptgraphs_spatial-quality
```

Replay and both evaluator invocations exit0. Outputs already exist; use a new
output directory when reproducing. Legacy evaluation uses the same command with
`legacy_geometry` in the prediction/output paths. The replay tool accepts no GT;
only the separate evaluator reads the offline annotations.

Artifacts: `.runtime/conceptgraphs-association-20261030/` contains replay manifest,
per-frame original online endpoints/diagnostics, reports, `comparison.json`,
commands/exits, source pins, RED/GREEN logs, availability probe and independent
review. Original input masks and source binding remain verifiable by SHA256.

## Verification and limits

- Fresh frozen whole CPU suite: **2024passed,2skipped,3native-deselected**, exit0,
  105.73s; all351source/test/config/tool pins unchanged before/after. Skips are
  optional Numba dispatch in this interpreter and explicit GPU-slot test.
- Main integration/legacy subset91passed, exit0. Engine scoped138passed, exit0;
  separate actual-baseline differential576ingests have identical assignments,
  checkpoints and event digests across all three legacy modes.
- Independent SolHigh reviewer **ACCEPT**,93fresh tests exit0 and independent
  100distance oracles,98unique-optimum exhaustive Hungarian problems and90
  actual-baseline parity frames exit0. No actionable findings. Review scope
  excludes unexecuted visual/native performance or P10 acceptance.
- Opt-in profile preflight exit0/readytrue. Fixture runtime replay exercises
  config-to-owner forwarding and durable metadata; real recorded-cloud replay
  validates the spatial association path offline. No new native live campaign,
  GPU workload, navigation safety or realtime acceptance claim.

No training, installs/downloads, source-sibling writes, commit or push occurred.
