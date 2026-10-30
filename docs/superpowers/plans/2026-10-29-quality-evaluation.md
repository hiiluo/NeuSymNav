# Object Quality Evaluation Implementation Plan

Goal: source-bound offline detection, geometry and identity reports.
Spec: ../../quality-evaluation-design.md. Execution authorized by user; additive
files only except main-owned CLI dispatch/status. No commit, installs or GPU.

- [ ] Detection worker: RED known AP/FP/FN/mask cases, implement pure metrics,
  GREEN focused tests and retain logs. Own detection_quality.py + its test only.
- [ ] Association worker: RED split/merge/occlusion/alias cases, implement IDF1
  and conditional diagnostics, GREEN. Own association_quality.py + its test.
- [ ] Geometry worker: RED IoU/center/cloud/support cases, implement pure metrics,
  GREEN. Own geometry_quality.py + its test.
- [ ] Main: tests then versioned loader/source binding, report + offline CLI;
  reject unannotated GT, count missing predictions, retain unsupported metrics.
- [ ] Main: read-only ledger export and unannotated GT template; verify hashes
  and truthfully mark final-canonical-only identity history.
- [ ] Inventory worker: inspect available real GT without inventing annotations.
- [ ] Freeze new source/tests, independent Sol High review, reproduce/fix findings,
  scoped regression tests, CLI reports, status/commands/exits/limitations.

Review focus: future aliases cannot erase online errors; frames missed/failed
remain denominators; no-GT classes/empty support never become perfect scores;
source masks must bind to exact frame/shape; truncated detections are not full AP.
