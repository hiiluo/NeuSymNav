# Completion and fine-tuning — 2026-11-01

User explicitly authorizes finishing the previous campaign and running fine-tuning.
Keep CG+Visual, 59-class taxonomy, 1m body and current camera rig. Preserve existing
dirty changes; no sibling writes, commit or push. One GPU operation at a time.

## Design

Fix evidenced navigation failures with a red regression before behavior changes.
Keep the strict RSS measurement contract: unknown samples remain unknown, and
failed attempts remain in the report. A non-atomic proc census is a measurement
limitation, not permission to fabricate a resource certificate.

Build a versioned bitmap dataset from the 1,400 existing Hypersim triplets.
Exclude inconsistent instances, preserve void/unsupported pixels as ignore, and
use source wall/floor/ceiling only as certified background for mapped object
classes. Freeze scene-disjoint train/validation/test before tuning. Start from
the original YOLOE11s checkpoint, not legacy adapted checkpoints. Record previous
scene exposure and do not claim universal pretraining disjointness.

Train the YOLOE head with its original local MobileCLIP vocabulary embeddings.
Keep all 59 outputs; suppress loss on unsupported class channels and ignored
spatial regions. Preserve instance bitmaps without polygon approximation. Use
validation for checkpoint selection; test is opened only after selection. Compare
base and selected checkpoint using identical partial-annotation metrics, then
check runtime compatibility before offering an opt-in tuned profile. Promote no
default unless quality and runtime evidence support it.

## Tasks / ownership

- [x] Dataset: `tools/prepare_hypersim_training.py`,
  `src/neusymnav/training/dataset.py`, dataset tests — dataset worker.
  Validate actual crosstabs, lossless masks, hashes, fixed scene splits.
- [x] Navigation: frontier policy/controller and tests — navigation worker.
  Main integrates bounded provenance diagnostics into runtime telemetry.
- [x] RSS: actual lifecycle repro and safe repair if proved — RSS worker.
  Otherwise document exact architectural blocker; do not weaken the gate.
- [x] Training: ignore-aware criterion, loader, trainer and tests — main.
  Prove ignored pixels/classes have zero gradient and mapped foreground trains.
- [x] Independent source/data/loss review, then bounded GPU forward/backward,
  baseline validation, training, validation selection, held-out comparison.
- [x] Serialized native navigation and tuned runtime validation; retain failures.
- [x] Final source checks, commands/exits, model/data artifacts and status report.

Artifacts: `.runtime/finetune-20261101/`; durable results under `docs/results/`.
Report implemented, correctness-verified and runtime-validated separately.
No numeric gain is promised before measurement. Training approval is current;
routine conservative label and implementation decisions need no repeated approval.

Executed checkpoint: two training recipes (6+2epochs), selectedBepoch1,
held-out regression and developmentdomain gain both reported. Baseline detector
retained; tuned profiles opt-in. Qualified00802navigation copied to ordinary
profile after nativeproof. Four completed native runs and one startup failure
retained. FullfinalCPU2290pass/3skip/9deselected0, independentreview and gradient
checks complete. RSS atomicity remains an explicit measurement limitation; no
unsafe/fabricatedrepair. See docs/results/completion-finetune-2026-11-01.md.
