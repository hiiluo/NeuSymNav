# YOLOE11s Hypersim head adaptation — 2026-11-01

Status: trained, validation-selected, offline-evaluated and runtime-load-tested.
Experimental opt-in; original YOLOE11s remains the default detector.

## Artifact and use

Checkpoint: `.runtime/finetune-20261101/training-detection/epoch-01.pt`

SHA256: `13edea274868fc7fdb4c5284578ba8ee9dc671dcdd5aac96749745f929972221`

```bash
bash tools/run_finetuned_demo.sh 00861 300
bash tools/run_finetuned_demo.sh 00802 300
# Optional third argument: a new output directory.
```

The wrapper selects GPU, CG+Visual and the versioned tuned profile.00802 uses
qualified navmesh/launch height.00770 has a checked profile but no new native
qualification in this campaign. Checkpoint is a local generated artifact, not
bundled into source control. Baseline command stays `bash tools/run_gpu_demo.sh`.

## Training/data

Original local YOLOE11s SHA8e439445…3e3 and local MobileCLIP; all59 ordered prompt
classes retained.900train/300validation/200test frames,14scenes split9/3/2.
25NYU40→runtime class mappings;20classes have positive train support. Bed,
bookcase,curtain,dresser,nightstand have no positive train support. Invalid,
unsupported and inconsistent instances remain ignore; structural wall/floor/
ceiling pixels provide background only for observed training classes.

Bitmap source/ignore resampling aligned; ignored pixels and unsupported channels
have zero loss gradient. No polygon approximation, pseudo labels or unknown→
background conversion. Backbone and maskproto/cv5 (including BatchNorm state)
remain unchanged in the selected detection-only recipe. Their predictions can
still change through detection proposals/confidence. Original prompt architecture
is retained; no fused vocabulary head or canonical object-ID owner change.

ExperimentA6epochs allhead did not improve primaryvalidationmaskAP, so selected
base. ExperimentB2epochs detectionheadcv2/cv3/cv4 from originalbase,AdamW1e-4,
batch2,seed0; checkpoint selection among base/epoch1/epoch2 by validation mask
subsetAP50:95 selected epoch1.900training examples/450optimizer steps at selection.
Both runs completed exit0 with frozen training dependency hashes unchanged.

Source conversion QC included held-out labels. ExperimentA script computed base
performance after its selection; main reports not consulting those metrics when
choosing B from validation evidence. Do not call test never-computed/unopened
across the campaign. No tuning followed B's held-out results. Possible exposure
of scenes during original pretraining is unknown. Neighboring frames are
correlated, and scene count is small.

## Measurements (subset AP50:95)

| Evaluation | Base bbox | Tuned bbox | Base mask | Tuned mask |
| --- | --- | --- | --- | --- |
|Validation300frames/14GTclasses|20.91%|23.74%|25.87%|26.03%|
|Test200frames/7GTclasses|15.01%|11.82%|10.33%|7.54%|
|HM3D00861development57frames/10GTclasses|12.20%|20.59%|12.56%|14.68%|

Hypersim uses original-resolution masks,25mapped-class spatial ignore and
independent bbox/mask eligibility, confidencefloor.05/maxDet100. It is a custom
partial-annotation metric, not officialCOCOignorematching. IoU.5possiblematch
eligibility is fixed across.5:.95 scoring. No confidence interval or universal
improvement follows. Validation mask improvement is only0.153percentagepoints.

HM3D uses the same57 source hashes/order, same230GT observations, evaluator and
encoder for both models, confidencefloor.05/maxDet100. Atconf.3, baseTP54/FP90/FN176
versus tunedTP92/FP159/FN138: precision37.50→36.65%, recall23.48→40.00%,
F128.88→38.25%. All59classes are scored where supported; the semantic renderer's
annotation scope has limitations. HM3D is one development scene, not a new
held-out benchmark. Hypersim and HM3D use different evaluation/box protocols;
compare models within a row, not numerical scores between domains.

## Native scope and decision

Live CG+Visual, original1m body/radius.125m and unchanged relative camera mounts:
00861tuned60s exit0,2.439m observed translation lowerbound,17feature commits,
RSS524/524;00802tuned60s exit0,2.239m,9feature commits,RSS515/515. RealCLIPfeatures,
zero geometry-fallback frames. Motion/map proofs are partial sampled bounds,
not complete trajectories. No native GT accuracy claim is made.

Measured cross-scene test regression prevents general default promotion. The
opt-in profile is useful for inspecting the demonstrated development-domain
tradeoff. Future adaptation needs more balanced class/scene support and a new
untouched test before additional tuning; do not repeatedly optimize this test.

Artifacts/commands/exits: `.runtime/finetune-20261101/` recipe/history/selection,
training-exit, detection-training-exit, experiment-protocol, hm3d-exits,
review/final-artifact-audit and completion-manifest. Base-model and dataset files
were read-only. No commit, push, publication or new data/model download.
