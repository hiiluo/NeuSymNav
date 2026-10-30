# Detection improvement — 2026-10-30

User explicitly selects CG + Visual and authorizes the previously proposed
ordered detection workflow. Both demo wrappers now select the new
`configs/p10/demo-yoloe11s-conceptgraphs-visual-gpu-00861.json`: YOLOE-11s640,
confidence .30, cap30, paired local MobileCLIP encoder, CGvisual/openai_clip.
The earlier26m profile remains an explicit baseline.

## Measured detection result

Same79 retained source RGB-D frames, unchanged223GT observations/19identities.
The selected detector is actually rerun with runtime confidence/cap, not obtained
only by filtering a low-score report. No source/GT labels are changed. Detection
matches use class-aware bboxIoU≥.5 with allGT/frames retained.

| Operating configuration | TP | FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|
| Original26m640/.25/cap30 |46|108|177|29.87%|20.63%|24.40%|
| Fresh26s640/.25/cap30 |72|125|151|36.55%|32.29%|34.29%|
| Selected11s640/.30/cap30 |80|134|143|37.38%|35.87%|36.61%|

Selected vs original: +34TP, -34FN, +26FP; precision+7.51pp, recall+15.25pp,
F1+12.21pp. There are more FP in absolute count despite better precision. This is
an in-sample diagnostic improvement on one scene, not held-out generalization.
We selected the strongest measured globalF1 while requiring precision at least
original. A class-specific fitted result is not installed as the runtime default.

| GT class | Original TP/FP/FN | Selected TP/FP/FN |
|---|---:|---:|
| chair |21/20/47|19/1/49|
| door |9/0/51|42/45/18|
| window |2/0/31|5/1/28|
| table |0/0/21|0/0/21|
| lamp |0/5/8|0/2/8|
| kitchen island |0/0/12|0/13/12|
| oven |0/0/6|0/0/6|
| toilet |14/1/1|14/6/1|

Door recall gains dominate; chair loses2TP. Table, lamp, island and oven still
have no TP. These failure classes remain targets for annotation/domain adaptation.

## Executed priority order

1. **Error/ontology audit:** source-bound original RGB/GT/prediction overlays,
   original rawTP46/FP108/FN177 reproduced. Separate class-blind diagnostics:
   29labelconfusions,24localization,2duplicates,53predictions unmatched within the
   suppliedGTscope and124unpairedGT. Largest confusion is table→dining table14,
   then chair→desk5 and door→fridge4. No alias/GT edit to inflate rawmetrics;
   unmatched predictions outside scoped annotations are not all hallucinations.
2. **PR collection/calibration:** real low-score .01/cap100 inference; global
   PR15thresholds +perclasssupport/fallback and fittedF1. Fitted perclass11s F1
   40.32% is diagnostic only, not promoted. Prediction-only classes retain the
   global threshold rather than being suppressed based on absentGT.
3. **Prompts:** exact59canonical category→text mapping with rawcategory baseline,
   `a photo of a ...`, and general indoor descriptions. Output classes always
   remain original canonical names. Neither promptvariant beats the selected
   checkpoint by globalF1, so no prompt rewrite is installed.
4. **Resolution/checkpoints:** same source images at imgsz640/960, local26m/26s/11s
   with compatible encoders. No new weights/packages.960 resizes existing640×480
   pixels; it does not add captured image detail. The actualruntimecap30 checks
   reproduce selected scores, capnotreached. Native validation is recorded below.
5. **Fine-tuning preparation:** localassetinventory and79sourceRGB/223candidateCOCO
   annotations with223maskSHA/RLE/bbox roundtrip checks. Taxonomy has59classes.
   The corpus is not train-ready: annotations scoped/nonexhaustive, one inspected
   scene, missing independent splits. Local1,400Hypersimtriplets/14scenes are
   inventoried but HDF5/mapping/completeness/split history remain unvalidated.
   No training executed. See [readiness](../detection-finetuning-readiness.md).

## Controlled low-score ablations

All use confidence.01/cap100 and all79/223GT. AP is the existing COCO-style
101point subset protocol (not official fullCOCO); all supplied low-scoreoutputs
are included. Numbers below are fractions shown as percentages.

| Model/prompt | BoxAP50:95 | MaskAP50:95 | F1 at.25 | Best globalF1 (threshold) |
|---|---:|---:|---:|---:|
|26m640 rawnames|19.88%|19.70%|24.47%|27.78% (.15)|
|26m640 photo prompt|19.35%|19.47%|24.89%|24.89% (.25)|
|26m640 indoor descriptions|20.59%|19.91%|20.23%|25.05% (.10)|
|26m960 rawnames|22.71%|20.88%|29.18%|31.13% (.15)|
|26s640 rawnames|19.45%|17.04%|34.29%|34.29% (.25)|
|11s640 rawnames|21.52%|19.28%|34.51%|36.61% (.30)|

11s is strongest by selected operatingF1, while26m960 has highestAP. The11s
maskAP slightly decreases vs26m640 at the same lowfloor; no allmetricgain claim.
11s lowfloor has one cap100saturated frame (partial); allothers have0. Cap30
selectedruntime at.30 has0saturated frames. Original13.71/14.16%AP used .25floor
and cannot be compared as equal-scope AP with these .01runs.
Fresh26m lowfloor rerun filtered at.25 has153pred vs original154 (46TP/107FP,
not46/108); retained images identical does not imply bitwise prediction parity
across changed upstreamscore/cap settings. Runtimechecks for26s/11s were separate.

Early exploratory inference timings overlapped CPUaudit/tests; those timings are
not an isolated throughput comparison. The native check is a separate proof of
bounded live wiring, not a claim of20Hz/P10 or speedup. Association quality must
be remeasured for new detector inputs; old CGvisual scores are not relabeled as
scores of this detector. CGvisual is retained by explicit user preference.

## Reproduce and evidence

```bash
bash tools/run_gpu_demo.sh --preflight
bash tools/run_gpu_demo.sh 300
# tools/run_conceptgraphs_demo.sh selects the same profile.
```

Tools: `tools/audit_detection_errors.py`, `tools/replay_detection_quality.py`,
`tools/evaluate_detection_campaign.py` (each has --help). Replay has no GT inlet;
evaluation validates sourcebindings and maskhashes separately. Backend mutation
regression was reproducedRED then fixed by independent BGRcopy/originalRGBcheck.
Sixinitialvariants retain their original frozen toolhash; finalcap30reruns use the
fixedsource. Historical artifacts are not silently attributed to the newer code.

Evidence root `.runtime/detection-improvement-20261030/`: exactcommands/exitcodes
in run_campaign.py/campaign-exits.json and run_selected_checks.py/selected-check-exits.json;
replays/*/{predictions.json,replay-manifest.json}; evaluation/*/report.json andpr.csv;
audit/{report.md,verification.json,original79-final/index.html}; replay-tool/
RED/GREEN/hashhistory; training-readiness/; comparison.json; final-review/.

## Final verification and runtime limits

Fresh frozen CPU suite:
`PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -rs -m 'not native'`
→2084passed/2skipped/3native-deselected, exit0/113.86s;367source/config/test/tool
pins unchanged. OptionalNumba and GPU-slot test skipped. `full-cpu.log`,
`full-suite-result.json`, before/after-full-suite.json record this exact snapshot.
Wrapper syntax and selected-profile preflight exit0/readytrue.

IndependentSolHigh scoped audit independently recomputed bbox/maskAP10IoUs,
PR15thresholds and fittedcounts for original+8replays, agreeing within1e-12;
all79source fields/223GT/19IDs, tightmaskboxes/hashes, originalledgerlogicaldigest,
449sourceassets and exact59classpromptmapping verified. Fresh36scopedtests exit0.
Review scope is source/offlinequality and livecomponentwiring; full operational
native acceptance is not established.

Two native attempts retained, same selectedprofile/safety/timeouts and117unchanged
source/configpins, oneGPU workload at a time:

- Attempt1: `runs/demo-detection-improved-cgvisual-60s-20261030/`, requested60s but
  failed early, wrapper30.829s/exit1. Navigation worker IPC whole-operation deadline
  exceeded; finalbundle mismatch is secondary. Onebatch committed/five realfeatures;
  no visual candidate pairs yet. Resource sampling also had1RSSreaderror and1
  truncatedsample. Firstobjectcommit is correlated with a1.02565s hostcontrolgap;
  retained binaryresponse mtime is8ms after request. This suggests a host scheduling/
  semantic-lane pause, but rootcause is unproven; no claimed fix or deadlineextension.
- Attempt2: `runs/demo-detection-improved-cgvisual-60s-repeat-20261030/`, actual60s
  session/wrapper71.772s. Runtimehealthfailed={}, noadmissionstop/exporterror, clean
  workers;8committedbatches,25actualdurable512DCLIPvectors,36visualcandidatepairs,
  0spatial-onlypairs/0fallback.1256/1256rawframes recorded, missing0. Actualdetector
  recipe/checkpoint/encoder and CGvisual provenance checked directly. **Overall
  exit1/outcomeincomplete**, due1RSSsample readerror; no capbreach. This run proves
  selected-detector→realCLIP→cloud association wiring, not complete resourcebounded
  acceptance or runtime stability. Failure from attempt1 remains unresolved.

Evidence: native-attempt-1/, native-attempt-2/, native-reproduction-policy.json,
run_native_selected.py/run_native_repeat.py, native-proof.json and check_native.py.
The proof-checker exits0 when these exact limited assertions hold; it does not
rewrite native exit1 into pass. No further retry to hide the measurement failure.

Fine-tuning, independent held-out quality, complete annotation audit, new-association
quality and P10/performance acceptance remain unproved. SAHI/higher-resolution
capture and temporal/depth detection confirmation were not implemented in this
iteration; the completed earlier priorities already yield a measured operating
improvement, while the next step is valid independent data and runtime-stall diagnosis.


Final independent review: **scoped ACCEPT** source correctness, offline metrics,
live CGvisual wiring and reporting; **operational native acceptance unaccepted**.
See final-review/review.md and result.json for exact scope.
