# Detection improvement implementation plan

**Goal:** select CGvisual and execute the approved ordered detector improvement workflow.
**Spec:** docs/superpowers/specs/2026-10-30-detection-improvement-design.md
**Architecture:** GT-free recorded-source replay followed by separate offline audit/calibration. Main owns runtime/contracts, one GPU slot. No new dependency/model download or training without a valid corpus.

- [x] T1 main: select existing CGvisual in tools/run_gpu_demo.sh; bash syntax/preflight0.
- [x] T2 audit worker: tools/audit_detection_errors.py + tests/test_detection_audit.py; deterministic one-to-one class-blind diagnostic join, raw class-aware TP/FP/FN, image overlays; tests include wrong class, duplicate, missing and exact boundary. Run original79 source-bound audit.
- [x] T3 replay worker: tools/replay_detection_quality.py + tests/test_detection_replay.py; verify original ledger/sources via existing readonly replay loader, run real local detector GT-free, explicit prompt→canonical mapping, safe atomic output with masks/source/config hashes, low score floor/maxcap/imgsz configurable for offline experiment only. Test source retention, mapping mismatch/duplicates, mask dimensions, missing assets. CPU tests; GPU execution by main only.
- [x] T4 main: offline evaluator/calibration + tests; evaluate all79/223GT for bounded fixed-input variants, global/per-class PR, AP, raw vs any ontology diagnostic. Freeze results without test/generalization claims. Reuse tested detection scorer and original masks.
- [x] T5 main: promote only measured usable detector improvements with pinned recipe and runtime regression tests; verify actual CPU suite and bounded native path if runtime changes. Leave ineffective variants unselected and report them.
- [x] T6 main: inventory fine-tune prerequisites, publish local data/readiness manifests and next scene-separated collection/annotation instructions; no fake training completion.
- [x] T7 independent SolHigh final review on stable snapshot, logs/hashes/results/status/execution ledger and precise unproven limits.

RED→GREEN applies to new functional code. Config/wrapper changes use actual preflight.
No commits: task artifacts and execution ledger replace automatic commit workflow per repo/user authorization.

T5 runtime ruling: component wiring demonstrated in60s repeat, overall exit1/incomplete dueRSSsample; earliernavdeadline failure retained/rootcauseunproven. No stable/P10claim. T6 preparation complete, actualtraining unstarted dueunvalidatedcorpus. NoSAHI/temporalruntime extension inthisiteration. See measuredreport forcommands/exits.

T7 scoped independent SolHigh ACCEPT source/offline/livecomponentwiring; fulloperationalnative acceptance expresslyunaccepted.36independenttests0 andindependentAP/PR/DBaudit0.
