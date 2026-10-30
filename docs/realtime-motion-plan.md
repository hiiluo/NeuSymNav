# Realtime and motion repair — 2026-10-29

Scope authorized by the user: diagnose the latest stationary demo and improve
useful live control toward NewOH3DSG cadence without relaxing correctness.
Keep both upstream folders read-only; no model/data download, install or publish.

1. Freeze/inspect latest run and reproduce pause/source mismatch through real
   production methods. Distinguish wall-time loop calls from source-matched
   executed control and measured body translation; retain uncertain UI cause.
2. Regression first: paused control must return runtime_paused before requesting
   a superseded sensor pose; no actuator/guard/policy call, no invented proof,
   no automatic resume. Owner main: coordinator + guard feedback test.
3. Persist a bounded command/ACK audit outside control. Owner pause_audit:
   ui_transport and transport tests only. Last64 records and explicit overflow,
   finalization within reserved transport quota. No command schema changes.
4. Measure existing native stages before optimization. Preserve primary640x480,
   YOLOE26m imgsz640, source-one-use, TTL300ms, footprint/clearance and proof.
   Identify measured bottleneck; optimize equivalent computation only, backed
   by regression/parity tests. Additional changes depend on the profile result.
5. Freeze final source/config pins before bounded native validation, one GPU
   job at a time. Report actual p95/p99, misses50/100ms, source-ready and executed
   counts, movement, raw replay completeness, graph progress and resources.
6. Independent Sol High review for safety/scheduling changes, full CPU suite,
   updated status/execution ledger and a truthful final demo command. No20Hz
   certification from paused/rejected iterations or historical benchmark alone.

Evidence: runs/realtime-motion-20261029/. Initial attempts/config checksum
blocks and unsuccessful native resource samples remain recorded, not promoted.
