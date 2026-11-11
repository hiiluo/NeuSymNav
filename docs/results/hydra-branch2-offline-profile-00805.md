# Hydra branch2 — offline latency profile from recorded 00805 frames

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Method

Replayed nine RGB-D observations (frame indices 0, 10, 20, 30, 40, 50, 60, 70,
82) from the complete recording of bounded smoke attempt
`9f4dc3ec-bd13-45e6-a860-ad8316f5972c`. The exact local profile/checkpoints
were used: YOLOE-26m, MobileCLIP2-B, 640 px, CPU. One offline detector worker
was started; its model-load and per-inference elapsed time were sampled, along
with the host round trip through the existing framed IPC client. The run did
not start Habitat, a simulator, or Hydra, and did not access semantic GT.

Profile SHA-256: `962cdf6a3f4a549427c88258a36bda2144969913c4792eae6f3e0d161b4c8310`.
Recording manifest SHA-256:
`a5147e728fcdc92366205b9740532553a28566014d053182489ed05bbca0e965`.

## Findings

- Detector worker initialization took **22.932 s** end-to-end. The instrumented
  model/encoder load accounted for **21.370 s** of that time.
- Across 9 recorded frames, warm `YOLOEDetector.infer` elapsed time was p50
  **1.301 s**, p95 **1.868 s**. Client round trip (encode/send, worker response,
  decode/validation and process scheduling included) was p50 **1.406 s**, p95
  **1.967 s**. The residual after subtracting worker inference was about 121 ms
  p50 and 137 ms p95; this is an estimate of host/IPC/serialization/validation
  overhead, not a pure pipe measurement.
- The two live capture-to-detector-return samples were frame 0: **26.566 s**
  and frame 77: **2.091 s**. The first is consistent with a cold worker/model
  start plus first inference; the offline profile confirms a 22.9 s startup
  cost. The second is close to the measured warm round-trip range. With only
  two live samples, the earlier p50/p95 (14.328/25.342 s) is not a useful
  steady-state detector latency estimate.
- Sensor source intervals in that live recording were also slow: primary RGB-D
  p50 **294.66 ms**, p95 **709.44 ms**, max **1,236.36 ms** (83 captures);
  navigation depth p50 **295.93 ms**, p95 **742.69 ms**, max **1,100.36 ms**
  (84 captures). Control invocation intervals had p50 **293.95 ms**, p95
  **737.18 ms**, max **1,092.87 ms** (82 intervals). Their medians align closely,
  indicating that control cadence follows the sensor/navigation update cadence
  in this run. Navigation depth age exceeded 300 ms in 7/83 control records,
  with a maximum of 406.45 ms.

## Diagnosis and limits

The first detector result was dominated by cold initialization. Warm CPU
inference still takes roughly 1.3 s median for each selected 640 px frame, so
the detector lane cannot keep up with a 5 Hz primary capture cadence if every
frame is submitted. Its latest-wins/admission policy therefore matters. The
detector lane is asynchronous and these timings alone do not prove it caused
the slow control cadence.

The strongest evidence for the control delay is the matching ~295 ms median
navigation capture and control interval. This localizes the bottleneck to the
sensor/simulator-update-to-control path, but this recording has no timestamps
at simulator `step`, render completion, NavMap start/end, or scheduler wakeup.
It cannot distinguish software rendering, simulator stepping, map construction,
or CPU contention as the cause. Those are candidate factors, not measured root
causes. Do not change movement settings or infer a fix from this profile alone;
stage timestamps are needed at those boundaries.

## Verification and artifacts

- Offline replay/profile harness exited **0**. The worker reported clean
  shutdown and was reaped.
- Profile JSON and captured console output:
  `.runtime/hydra_ws/artifacts/hydra-offline-detector-profile-20261104/profile.json`
  and `profile.log`; SHA-256 of each:
  `d1c8b251d0eee520625e27e4fc6fd2294fb8594b73557b377adec864795006b3`.
- Source live measurements remain in
  `.runtime/hydra_ws/artifacts/hydra-smoke-00805-30s-revisionfix-20261104T150133/`.
- No simulator, long smoke, A/B run, config change, or movement change was made.

Next measurement should add monotonic timestamps around simulator request/step,
primary and navigation render/capture, NavMap update, and control-loop start/end
in a short bounded smoke. That is required to separate the remaining sensor,
mapping, and scheduler costs.
