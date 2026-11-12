# Local Rebuild room FPS cap experiment

> **For agentic workers:** Execute inline with `superpowers:executing-plans`. Use TDD for production changes. Do not update or run the Kaggle bundle in this experiment.

**Goal:** Add an opt-in local-only Rebuild admission policy that caps room update rate, keeps at most one latest pending frame, and measures timing/coverage so the sampled map can be compared against replay of the same raw recording.

**Architecture:** The default room lane remains bounded FIFO. An explicit `fps_cap_hz` plus `queue_policy=latest_wins` selects observations by source capture time and replaces only the single pending room frame; every cap/replacement is journaled. Bounded telemetry records frame age, queue wait, and service time. A local replay comparison uses the existing raw RGB-D recording as a full-sequence reference.

**Scope:** NeuSymNav local checkout and local recordings only. Do not upload/edit a Kaggle dataset or notebook, change acceptance, weaken M5 geometry validation, or modify the read-only Rebuild source checkout.

**Implementation steps:**

1. Add failing coordinator tests for FPS selection, single-pending latest-wins replacement, explicit counters/reasons, and bounded timing metrics.
2. Add failing config tests requiring an explicit valid FPS cap for latest-wins; preserve FIFO defaults and include selected admission policy in run provenance/profile.
3. Implement the opt-in policy in coordinator/config/launcher and preserve local experiment options through the local runner config generator.
4. Add a local comparison utility that replays all primary RGB-D frames and a deterministically FPS-selected sequence from the same recording, then reports pose coverage and M3/M5 differences without changing the acceptance checker.
5. Run focused tests, local preflight, then the bounded local recording/replay comparison. Report throughput, queue loss/replacements, source age, pose coverage, map differences, M5/acceptance, resource caps, and artifact paths. Kaggle remains deferred until local gates pass.

**Initial comparison cap:** 0.10 Hz, approximately one selected Rebuild observation every 10 seconds. This is a starting point derived from the observed local room throughput estimate and is not a quality or long-run threshold.
