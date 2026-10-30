# Complete real visual association — 2026-10-30

Implemented, CPU correctness-verified and native runtime-validated for the scoped
RGB → CLIP → projected point cloud → existing canonical owner path. This closes
the missing real visual execution from the earlier spatial-only delivery. That
earlier delivery did not satisfy the user's full visual integration request.
No default promotion, detector retraining, download, installation or sibling edit.

## What now runs

The explicit `openai_clip` backend loads the existing local ViT-B-32 TorchScript
checkpoint on CPU, verifies SHA/architecture, constructs strict float32 eval model
and checks the224px CLIP transform. It returns normalized512D vectors for padded
source RGB/mask crops. Metadata binds checkpoint, model/transform source and actual
runtime versions into a separate feature space. The installed `clip` is an
Ultralytics fork; upstream compatibility is not substituted for actual provenance.
No pickle fallback/download. Existing OpenCLIP safetensors recipes remain separate.

Checkpoint: `/home/hiiluo08/Works/NeuSym-Nav/NewOH3DSG/weights/clip/ViT-B-32.pt`
(read only), SHA256 `40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af`.
Feature space: `neusymnav-appearance-space-v1:d1aaf9a81248ca8e7abc93928c2fb120c393e98d4d6dfaab9246fdc6b1760fef`.

The owner combines directional cloud overlap and compatible visual cosine while
retaining Hungarian assignment, canonical IDs, ambiguity and transaction rules.
Safety, unknown/free semantics, TTL and control contracts are unchanged. Native
execution exposed nested immutable metadata that was not JSON serializable;
launcher now copies it recursively, with a reproduced failing regression then fix.

## Same-input comparison

All79 committed detector frames from the original300s run,154 detector outputs,
137 original projected observations and all223 GT observations/19 identities are
retained. Real RGB/mask feature extraction produced154 vectors, complete coverage;
no semantic GT is read by extraction or matching. The separate offline evaluator
reads GT. Exactly17 detections lack original projection in every mode. Unresolved
association exclusions are explicit; no invented IDs or dropped GT/frames.

| Mode | Assigned /137 | Unresolved | IDF1 | HOTA | AssA | DetA |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Legacy geometry |119|18|26.90%|25.81%|34.34%|19.72%|
| ConceptGraphs spatial |108|29|25.98%|22.28%|29.45%|17.16%|
| Legacy + visual |120|17|28.57%|26.32%|36.06%|19.62%|
| ConceptGraphs + visual |101|36|26.54%|25.51%|42.43%|15.51%|

CGvisual scored237 real visual candidate pairs with0 fallback rows. Relative to
CGspatial, AssA increases12.98 percentage points, HOTA3.23 and IDF1 .56, but
unresolved increases29→36. IDTP stays43; IDFP65→58 and IDFN stays180. The small
IDF1 improvement therefore reflects fewer false identity assignments, not more
recovered GT. Legacy+visual has the highest IDF1/HOTA on this sample. CGvisual
switches2/29 supported transitions versus6/33 for spatial; different support
precludes an unconditional robustness claim. Revisit3/8 versus3/10 is also
conditional on different opportunities and is not proof of a general gain.

Detector output is unchanged: original P29.87/R20.63/F124.40%, boxAP50:95=13.71%,
maskAP50:95=14.16%. Association changes do not repair missed detections. Geometry
measurement remains the recorded RGB-D observed-surface proxy, not independent
full-mesh/sensor accuracy. No threshold tuning was done on these results.

## Live runtime proof, separate from quality replay

`runs/demo-conceptgraphs-visual-60s-20261030/`: requested60s, wrapper70.9963s,
exit0 / completed, resource monitoring complete;117 source/config pins unchanged.
Actual RGB-D/simulator + YOLOE + CPU CLIP, single GPU workload.1350/1350 raw frames
recorded, no missing frames.15 committed frames,15 actual durable512D feature
vectors,8/8 snapshot objects with appearance,14 visual candidate pairs,
0 spatial-only pairs and0 fallback rows. Six matches/eight new IDs/one ambiguity.
Worker `feature_frames=15` includes empty batches and is not a count of frames
containing vectors. Durable feature rows and scored pairs are the direct proof.

This60s run proves the live path; the quality table uses the fixed79 inputs from
the earlier300s run. It is not a new300s fullvisual quality campaign or P10/20Hz
acceptance. One scene and correlated observations do not establish held-out gains.

## Verification and retained evidence

Evidence root: `.runtime/conceptgraphs-visual-20261030/`.

- `PYTHONPATH=src QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests -q -rs -m 'not native'`: exit0,2048passed/2skipped/3deselected,105.22s;356 source/config/test/tool pins unchanged. Skips are optional Numba and explicit GPU-slot test.
- Independent SolHigh review ACCEPT:44 focused tests exit0; artifact audit exit0; checkpoint/installed implementation hashes, model/space digest,79 feature payload/source/mask/time bindings and154 finite unit vectors checked. Independent SciPy global ID assignment reproduces all four IDF1 counts.19 HOTA alpha denominators and arithmetic checked; no full independent AssA implementation claimed.
- `backend/{red.log,green.log,report.json}`, `real-worker-smoke.json`, `local-checkpoint-probe.json`: backend regression and actual model/IPC proof.
- `replay/fixed79/replay-manifest.json`, `replay/fixed79/features/manifest.json`, `evaluation/summary.json`: real features, four replay outputs and metrics.
- `native-{exit,result,visual-proof}.json`, `request.json`, `run_native.py`: exact native request, exit, source pins and direct ledger proof.
- `full-cpu.log`, `full-suite-result.json`, `before-full-suite.json`, `after-full-suite.json`, `final-audit/{review.md,result.json,audit.py,audit.log,focused.log}`: final verification.

Cache manifests are trusted local artifacts; arbitrary hand-edited encoder metadata
is not independently authenticated at cache reuse. The retained measured cache was
independently rehashed and its feature-space digest verified by the reviewer.

## Run it

```bash
bash tools/run_conceptgraphs_demo.sh --preflight
bash tools/run_conceptgraphs_demo.sh 300
```

Use a new output directory per episode. The wrapper selects the explicit fullvisual
profile; `tools/run_gpu_demo.sh` retains its existing default. To reproduce feature
extraction/replay, run `tools/replay_visual_association.py --help`; the original
79-frame RGB/masks/clouds and local checkpoint must still be present.

Next accuracy work: audit ontology/false positives/missed doors and windows, then
compare detector PR/AP on frozen images. For association, diagnose the36 unresolved
observations and tune/calibrate on separate validation scenes with deliberate
occlusions/revisits before held-out evaluation. Do not optimize thresholds using
this one reported sample or promote the recipe based on AssA alone.
