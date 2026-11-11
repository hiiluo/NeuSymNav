# Hydra branch2 — UHD availability and recorded-frame detector A/B

Date: 2026-11-04. Branch/worktree: `Kiet_branch2` /
`.runtime/worktrees/Kiet_branch2`.

## Scope

After the user installed Intel's OpenCL system package, rechecked UHD runtime
visibility and compared the existing YOLOE-26m-seg detector across CPU input
sizes and OpenVINO CPU/UHD on nine frames from the existing 30 s smoke
recording. No simulator was started. No application detector code or runtime
configuration was changed. OpenVINO was installed only in the project-local
`.runtime/detector26` environment, and a static OpenVINO model was exported to
the task artifact directory for this offline experiment.

## UHD runtime availability

- Host PCI identifies Intel Raptor Lake-P UHD Graphics (`8086:a7a8`), using
  kernel driver `i915`. `/dev/dri/card1` and `/dev/dri/renderD128` are
  accessible to the user in the escalated probe (the workspace sandbox hides
  these nodes from ordinary commands).
- Following the user's system installation, `intel-opencl-icd`
  `23.43.27642.40-1ubuntu3` exposes one OpenCL platform,
  `Intel(R) OpenCL Graphics`, and one device, `Intel(R) UHD Graphics`.
- OpenVINO `2026.4.1-22982-e213a147257-releases/2026/4` is installed in the
  local detector venv. `ov.Core().available_devices` returns `CPU` and `GPU`,
  with GPU full name `Intel(R) UHD Graphics (iGPU)`.

## CPU input-size comparison

The same primary RGB-D frames **0, 10, 20, 30, 40, 50, 60, 70, 80** were
profiled with the existing PyTorch CPU detector at each input size. The
checkpoint, MobileCLIP2-B encoder, taxonomy, confidence threshold (0.25), and
maximum detections (30) were held constant. One warm-up call was made per
shape. Matching requires the same raw label and binary-mask IoU >= 0.5 against
the 640 px detector output.

| Input size | p50 inference | p95 inference | Matched to 640 px | Mean mask IoU of matched detections |
| --- | ---: | ---: | ---: | ---: |
| 640 | 1,309 ms | 1,514 ms | 28/28 reference | 1.000 |
| 544 | 1,078 ms | 1,323 ms | 11/28 (39.3%) | 0.902 |
| 512 | 900 ms | 947 ms | 11/28 (39.3%) | 0.938 |
| 480 | 811 ms | 1,081 ms | 8/28 (28.6%) | 0.849 |

Smaller CPU inputs are faster, but substantially change outputs on this small
sample. These are agreement numbers against the 640 px model, not accuracy
against ground truth. Keep 640 px until a larger labeled or visually reviewed
comparison supports a change. The only local checkpoint is YOLOE-26m-seg; no
smaller model was benchmarked.

## OpenVINO CPU/UHD comparison

For a same-runtime comparison, the 640 px checkpoint was exported as a static
59-prompt OpenVINO IR using the existing local taxonomy. Ultralytics 8.4.24's
exporter calls an end2end head's `fuse()` without prompts before applying its
prompt embedding. The one-off exporter script temporarily suppresses that
no-prompt call only on the exporter's disposable deep copy, then restores the
end2end head before prompt fusion. It preserves end2end in the resulting IR;
no application source was patched. The measured calls include Ultralytics
preprocessing, inference, and mask postprocessing. Timings exclude model load
and first compile/warm-up, which are reported separately.

| Backend | p50 inference | p95 inference | First compile/warm-up | Same-label, mask IoU >= 0.5 matches vs Torch CPU | Candidate detections |
| --- | ---: | ---: | ---: | ---: | ---: |
| PyTorch CPU (1 intra-op thread) | 1,295 ms | 1,377 ms | 1,682 ms warm-up | 28/28 reference | 28 |
| OpenVINO CPU | 838 ms | 849 ms | 1,445 ms | 28/28 | 39 |
| OpenVINO Intel UHD GPU | 208 ms | 251 ms | 7,003 ms | 27/28 (96.4%) | 37 |

On these nine frames, OpenVINO UHD was about **6.2x faster at p50** and **5.5x
faster at p95** than the PyTorch CPU baseline. It matched 27 of the baseline's
28 detections by same label and mask IoU >= 0.5, with mean matched-mask IoU
0.975; it also produced 9 additional candidates. OpenVINO CPU matched all 28
baseline detections, with mean matched-mask IoU 0.986, and produced 11
additional candidates. This is output agreement on a tiny recorded sample,
not evidence of semantic accuracy or acceptable false-positive/recall rates.
No ground-truth annotations were used.

OpenVINO's first GPU compile/warm-up took about **7.0 s**, much longer than a
steady frame. A runtime integration should initialize this backend before
semantic work is admitted and preserve the CPU fallback; it should also
validate output contracts and quality on more recorded data before a live run.

## Result and limits

The UHD is visible and can run the exported detector roughly six times faster
than the current PyTorch CPU path on this nine-frame sample. This shows CPU was
not the only practical option on this machine. It does **not** mean the
NeuSymNav runtime now uses UHD: the production worker still instantiates the
existing PyTorch CPU detector. No simulator, live detector worker, movement,
runtime integration, long run, or ground-truth evaluation was performed.

## Verification and artifacts

- User-installed host ICD probe: `clinfo` exit 0; one OpenCL platform and one
  Intel UHD device. OpenVINO device enumeration in `.runtime/detector26` exit
  0; devices `CPU`, `GPU`.
- CPU input-size A/B command:
  `.runtime/detector26/bin/python .runtime/hydra_ws/artifacts/hydra-cpu-resolution-ab-00805-20261104/profile_cpu_resolutions.py`
  — exit **0**.
- OpenVINO CPU/UHD command (run with access to `/dev/dri`):
  `OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 .runtime/detector26/bin/python .runtime/hydra_ws/artifacts/hydra-cpu-resolution-ab-00805-20261104/profile_openvino_devices.py`
  — exit **0**, 9 frames per backend, clean process exit.
- CPU profile JSON: `cpu-resolution-ab.json`; device profile JSON:
  `openvino-device-ab-e2e.json`; hardware/runtime probe: `opencl-probe.json`.
  The static IR, export metadata, and both one-off profile/export scripts are
  in the same artifact directory.
- SHA-256: device result `aff9ff3e67d2416622ce24d6357c24118c4d3ca8bd2455a77ebfb23c37325dc9`;
  CPU result `da425026a0a10522c19428453d9f8d5cd27167033e73eaa1670fdd9debeab2a2`;
  runtime probe `70403b2b15aa67c00bf7081b25fb359477ec89680518e992f990faa2c6bb4632`;
  OpenVINO IR XML `b68fcd9c1537c0461bf8a7a49b47afb513bc2a400a925b43f3d941c45109169b`;
  OpenVINO IR BIN `03a705c35ba6c23515d0cbc7f448da339bd2bb35035b71d62917bc335c1c5a69`.
- `git diff --check` exited **0** for the updated report and checkpoint.
  JSON assertions exited **0** for UHD/OpenVINO enumeration, nine-frame
  profiling, 27/28 detection agreement, and `simulator_started=false`. No
  application tests were run because application code was not changed.

**Status:** implemented — recorded-frame profiling/export artifacts and report;
correctness-verified — device enumeration, frame identities, output matching,
and retained result JSON; runtime-validated — offline on recorded frames only.
Production detector integration, broader quality evaluation, and live
runtime/simulator validation remain open.
