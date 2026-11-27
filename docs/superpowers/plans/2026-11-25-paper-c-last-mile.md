# Paper C last-mile implementation plan

> Hồ sơ lịch sử. Mã và tùy chọn chạy của C, A, S đã được gỡ khỏi checkout hiện tại.

**Goal**

Acquire candidate evidence on the approach and check the measured pose before leaving it.

**Spec**

[Last-mile research and design](../../objectnav/c-last-mile-research.md).

**Scope**

Implement in the current checkout. Keep the paper B0 configurations, action set, detector, scorer and semantic GT boundary. Use the existing recovery budget and the current 0.50/0.75 m near limits. A single selected viewpoint per attempt uses the calibrated current pitch for prediction and can adjust pitch from live evidence on arrival.

## Tasks

- [x] Extend the Paper C fixture with a delayed Qwen reply at a verified pose, a viewpoint chosen on a reachable path and fresh-depth diagnostics for an occluded surface. Run the new tests against the existing code.
- [x] Reuse VVD reachability and projection for one on-route observation. Bind it to the active canonical candidate, reserve STOP and abandon the observation on alias uncertainty, blocked motion or expiry.
- [x] Give unresolved identity a bounded local re-observation. Retest current RGB-D before movement in recovery, retain the distinct-view and source checks, and verify visually confusable TV candidates with Qwen when it is configured.
- [x] Record reprojection counts and residuals in the VERIFY trace. Expose old, viewpoint-only and combined C behavior in the paper runner for paired comparisons on the same foundation.
- [x] Verify the focused tests, ObjectNav suite, CPU suite and manifest preflights. Record artifact paths and distinguish these checks from benchmark results.
