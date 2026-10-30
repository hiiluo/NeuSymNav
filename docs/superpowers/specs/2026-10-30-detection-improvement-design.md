# Detection improvement and CG visual selection

User explicitly selects CG + Visual and requests execution of the previously
presented priority order. This is authorization to implement that concrete
workflow without another design/permission loop. Existing dirty changes stay.

## Approach

1. Select the existing verified CGvisual profile in the main GPU demo launcher;
   preserve the canonical owner/Hungarian/safety contracts.
2. Audit original79-frame detections vs223GT with source RGB overlays, class-blind
   diagnostic overlaps and raw class-aware results. Do not alter GT/taxonomy to
   make results rise. Manual/visual inspection is diagnostic, not new annotation.
3. Implement GT-free readonly detector replay over the exact committed RGB-D
   sources. Low-score candidate export and source/config/model/prompt hashes are
   durable. Compare fixed79 variants: low-score base, descriptive text prompts,
   larger inference size, compatible local checkpoint. No download/install.
4. Evaluate all frames/GT separately, sweep confidence globally/per-class and
   report AP/PR, class support, cap saturation, timed inference and memory limits.
   Original79 already inspected => development/diagnostic only, never held-out.
5. Wire source-bound prompt mapping/per-class thresholds only where supported by
   evidence and tests. Freeze selected candidate separately from baseline. Higher
   inference cost must not silently enter live runtime without a bounded proof.
6. Fine-tuning needs a scene-separated labeled corpus. Inventory local assets and
   prepare a concrete reproducible dataset/training handoff; do not start training
   on79 correlated diagnostic frames or invent unavailable semantic annotations.

Alternatives: blindly lower confidence (FP already high); switch larger model
without fixed-input comparison (confounded/costly); selected staged replay approach
isolates changes and measures both missed detections and FP. No guaranteed gain.

## Boundaries

GT offline evaluator only. Source siblings read-only. One GPU workload at a time;
main owns GPU/environment/defaults/contracts. Workers have disjoint files.
Default association selection is user preference, not proof CGvisual is best by
all metrics. Cache/output files bind actual source and recipes. No commit/push.

## Review focus

Same79 frames/223GT retained; no per-class GT-informed inference filtering;
source masks/boxes in exact pixel coordinates; prompt classes map deterministically
to existing taxonomy; no silent model download; no tuning/test leakage claim;
partial/capped outputs explicit; old fixture/default behavior compatible.
