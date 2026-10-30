# Object quality pilot — 2026-10-30

This is a measured **one-scene, first-12-committed-keyframes pilot**, not a whole
system accuracy estimate or P10 acceptance. It uses retained run
`demo-yoloe26m-640x480-gpu-20261030-104928-497271978`, scene
`00861-GLAQ4DNUx5U`, primary source indices 0–185. The run has 16 committed
batches; the first 12 were selected before GT rendering, not by detection quality.

Effective recorded config SHA256:
`43baef6dfbc069acdd3cedf52f35866b77747a1668d7eacd01024bcf3d0b002e`.
Primary RGB-D 640×480, YOLOE-26m / imgsz640 / confidence .25 / max30.
No detector rerun, model download, training or online GT use was performed.

## Annotation trust and scope

GT is rendered offline from the existing HM3D semantic assets at each exact
SHA-bound source camera pose. Actual rendered K and pose are checked; RGB/depth
alignment is required before any GT is published. The first native attempt
failed because the runtime dataset has no semantic stage registration. Its
failure log is retained. An evaluator-only derived descriptor adds explicit
hashed semantic paths while preserving geometry/render defaults. The second
attempt succeeds for all 12 frames with the original prospective gates.

- 44 eligible instance-frame annotations, **13 distinct GT identities**.
- Six supported categories: chair, door, window, kitchen island, table, lamp.
- Masks >=100 pixels, supported by frozen taxonomy; door/window are included.
- 286 excluded ID-frame records: 12 background, 222 unsupported taxonomy,
  52 small. Full pixel/count/label/reason accounting is retained.
- Maximum RGB MAE: **0.0008366 byte**; maximum RGB p99: **0**.
- Maximum depth MAE: **0.000001167 m**; maximum depth p99: **0.000036015 m**.
- Every frame has 100% supported depth pixels inside the declared tolerance.

This trusts the scoped HM3D annotations, not manual whole-scene adjudication.
Repeated nearby frames are correlated; 44 observations are not 44 independent
objects. No confidence interval is claimed from this pilot.

## Detection — all 21 supplied detections

Class-aware bbox matching, IoU >=.5, score >=.25:

| Metric | Measured value | Support |
|---|---:|---|
| TP / FP / FN | 7 / 14 / 37 | 21 predictions, 44 visible GT observations |
| Precision | 33.33% | 7/21 |
| Recall | 15.91% | 7/44 |
| F1 | 21.54% | 14/65 |
| Box AP50 / AP75 | 21.12% / 2.08% | Six classes with GT |
| Box AP50:95 | 10.53% | 101-point, ten IoU thresholds |
| Mask AP50 / AP75 | 24.09% / 18.15% | Same supplied outputs and GT |
| Mask AP50:95 | 12.69% | Same six-class scope |

AP is the non-crowd/non-ignore subset over **already filtered recorded outputs**,
not full official COCO AP or a low-score detector replay. AP excludes classes
with no GT from its macro mean; their false-positive counts remain in precision.

| Category with GT | TP / FP / FN | Recall |
|---|---:|---:|
| chair | 6 / 2 / 12 | 33.33% |
| door | 0 / 0 / 10 | 0% |
| window | 0 / 0 / 7 | 0% |
| kitchen island | 0 / 0 / 4 | 0% |
| table | 0 / 0 / 4 | 0% |
| lamp | 1 / 0 / 0 | 100% (only one observation) |

Some predicted categories have no eligible same-label GT in these frames.
Ontology granularity (for example table versus dining table) must be visually
audited before attributing every such FP to model hallucination. Do not silently
rewrite taxonomy aliases to improve this existing score.

## Association — 17 projected-memory observations

Four detections lack an object-memory identity because they did not produce an
assigned projected observation. The unfiltered report correctly leaves identity
metrics unavailable. A **separate, explicitly labeled memory-output report** uses
the 17 identity-bearing observations, retains all 12 frames and all 44 visible GT
observations, and records exactly which four detections were excluded. Detector
metrics above always use all 21. Geometry matching here ignores semantic labels.

Ledger merge rewrites historical endpoints; these are **final canonical** scores.
Online historical scores are unavailable, not reconstructed from future aliases.

| Metric | Measured value | Support / limitation |
|---|---:|---|
| IDF1 | 32.79% | IDTP10 / IDFP7 / IDFN34; 20/61 |
| HOTA | 33.81% | Mean of 19 alpha thresholds |
| AssA | 65.95% | Same HOTA protocol |
| DetA | 17.81% | Same HOTA protocol |
| Conditional pair precision / recall | 100% / 100% | Only 10 eligible same-ID pairs each |
| False-merge / split pairs | 0 / 0 | Matched observations only |
| ID switches / visible fragments | 0 / 0 | Only six scored matched transitions |
| Duplicate observation rate | 0% | 0/17 |
| Revisit identity recovery | Unavailable | Zero eligible revisits |

HOTA follows a reference-pinned TrackEval sequence algorithm with class-agnostic
bbox IoU. It uses its own global alignment and alpha matching; it is not simply
the square root of the average DetA and AssA above. No official dataset benchmark
or broad robustness claim follows. The small conditional pair support and lack
of revisits do not establish good long-term association.

## Geometry — observed RGB-D surface proxy

An auxiliary CPU preparation reconstructs verified GT-mask pixels using recorded
valid axial depth/K/pose and unions only the selected predicted ObjectObservation
clouds by final ID. It does not use full-episode final geometry or unobserved
mesh surfaces. Bounds use all input points; point metrics use declared 2cm voxel
sampling and at most20,000 points/object. Depth and pose are shared inputs, so
this is a **mask/projection/fusion consistency proxy**, not independent sensor
depth accuracy or full-object 3D reconstruction accuracy.

| Metric | Measured value | Support |
|---|---:|---|
| Predicted / GT observed objects | 8 / 13 | Selected source frames only |
| TP / FP / FN at volume IoU >=.25 | 4 / 4 / 9 | Label-independent one-to-one matching |
| Instance precision / observed recall | 50% / 30.77% | 4/8 and 4/13 |
| Mean matched 3D AABB IoU | .6042 | Four matches |
| Mean matched XY AABB IoU | .6729 | Four footprint matches |
| AABB-center error median / p95 | .0945 m / .5360 m | Four matches; unstable small-sample p95 |
| Point precision / recall at5cm | 77.88% / 77.14% | 2,599 predicted /4,672 GT sampled matched points |
| Point F1 at5cm | 77.51% | Matched sampled surfaces only |

## How these measurements guide the next experiment

1. Audit missed doors/windows and the table/dining-table vocabulary distinction
   against source images and masks. Keep any taxonomy change versioned.
2. Replay competing detectors on exactly these source images with a predeclared
   low score floor and detection cap. Measure full PR tradeoff and mask/box AP;
   confidence values alone cannot establish an improvement.
3. Expand the fixed annotated sequence to multiple scenes and deliberate revisits,
   close same-class objects and occlusion. This pilot cannot diagnose rare merges.
4. Compare association on identical detection inputs; separately use GT observations
   offline to isolate matcher limitations from detector misses.

## Artifacts and reproduction

Local retained evidence: `.runtime/quality-evaluation-20261030/`:
`native-preparation/`, `semantic-prepared/`, `native-gt-overlay/`,
`detection-baseline/`, `memory-baseline/`, `geometry-baseline/`, reviewer directories,
and `build_geometry_inputs.py` with per-object sampling/source support.
These include raw JSON values, source/asset hashes and explicit denominators.
The old `runs/quality-evaluation-20261029/` was intentionally removed by the
user-authorized cleanup; its historical logs are not claimed to be present.

```bash
PYTHONPATH=src .venv/bin/python -m neusymnav.cli evaluate-quality \
  --gt .runtime/quality-evaluation-20261030/native-gt-overlay/ground-truth.json \
  --predictions .runtime/quality-evaluation-20261030/native-preparation/predictions.json \
  --out .runtime/quality-recheck-new
```

See [evaluation usage](../object-quality-evaluation.md) and
[semantic GT trust boundary](../quality-semantic-gt.md). Synthetic fixtures test
the evaluator; they are not included in these measured quality numbers.

## Verification of this implementation

Fresh whole CPU suite: **1,960 passed, 2 skipped, 3 native deselected**, exit0,
105.83s pytest time. All314 source/test/config pins were stable before/after.
The skips are optional Numba dispatch under this interpreter and an explicit
single-GPU-slot test; neither is silently counted as passed. The native semantic
render was executed separately and completed exit0. Independent Sol High final
audit ACCEPT:108focused tests, exact-arithmetic HOTA/IDF1 derivations,47native
manifest files,44GT mask instances, and observed-surface preparation checked.
Exact logs, commands/exits, hashes and review limits are retained locally.

The full semantic raster/rendered RGB-D and measured GL matrices were not retained;
alignment statistics are saved with the hashed execution path and source data.
Recomputing these raster measurements requires a renderer rerun. Review certifies
the declared source/artifact scope, not full annotation completeness or P10.
