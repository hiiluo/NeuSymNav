# GPU stage microbenchmark — HM3D 00805

Run in the user's Kaggle draft with two Tesla T4 16 GB devices visible. The
measurements are short stage probes, not a full-pipeline performance claim.
Only GPU 0 was selected for model/raycast execution; the two devices were not
benchmarked concurrently.

| Stage | Workload and execution proof | CPU / software path | GPU path | Finding |
| --- | --- | ---: | ---: | --- |
| YOLOE detector | Bundle-pinned YOLOE-26m-seg and MobileCLIP; one 480×640 RGB frame captured from Habitat 00805; project `YOLOEDetector`, `device='cpu'` then `device='cuda:0'`; parameter device and CUDA memory checked | Warm median 0.522 s; first call including load 5.742 s | Warm median 0.0716 s; first call including load 8.371 s; 139,490,816 bytes allocated | 7.28× warm inference speedup on the GPU-enabled Kaggle kernel. Detection count and label matched (1, `door`); mean score delta 6.56e-7. Mask areas differed: 75,935 vs 75,299 pixels. No mask-IoU or exact-pixel equivalence was established. |
| Habitat-Sim renderer | Habitat-Sim 0.3.3 headless, real 00805 scene and calibrated 480×640 RGB-D capture; EGL renderer string from Habitat logs; post-capture `nvidia-smi` | Renderer was Mesa `llvmpipe` (software OpenGL); probe elapsed 16.10 s | No CUDA/OpenGL device use observed; both T4s at 0% and 237 MiB after capture | Did not move rendering to the T4. Kaggle exposed CUDA devices, but this Habitat environment selected software rendering. No GPU speedup is supported. |
| Navigation raycast | Project `GpuRaycastClient` and isolated Triton worker; 4,096 seeded rays, 0.4–4.0 m, 0.05 m grid; same inputs to CPU Python and GPU; worker metadata says Tesla T4, capability 7.5, Triton 3.6.0 | Median 0.2889 s (three calls) | Client end-to-end median 0.01356 s (three calls); worker last total 3.38 ms, kernel 1.57 ms | 21.3× end-to-end speedup. All five returned masks matched CPU exactly; worker shut down cleanly. This optional backend accelerates NeuSymNav's navigation occupancy raycasting, not Rebuild room M1–M5. |

## Measurement limits

- Detector ran in Kaggle's default Python 3.13 / `torch 2.11.0+cu130` kernel.
  It did **not** run with the full bundle's `torch==2.7.1+cpu` environment pin.
  It proves the adapter routes inference to CUDA when given a CUDA-enabled Torch
  runtime; it does not prove the shipped bundle currently configures detector
  inference for GPU. The benchmark-only missing `ftfy` dependency was installed
  into the Kaggle session and not added to project files.
- The detector adapter's contract object used the actual captured RGB frame and
  a placeholder depth/intrinsics/pose because the model stage consumes RGB only.
  Thus this isolates detector compute and does not validate sensor calibration
  or downstream 3D projection.
- Raycast endpoints were deterministic synthetic rays rather than a full
  measured-depth point cloud. Exact mask parity applies to this bounded workload.
- Habitat returned valid RGB-D and used the real scene, but its rendering path
  stayed on llvmpipe. The renderer probe's 16.10 s includes initialization and
  should not be compared directly with the detector/raycast steady-state times.
- The 180 s full M1–M5 run remains a separate result: it was incomplete and had
  zero accepted M5 regions. Its M2 work is native/CPU-side and its queue
  throughput was low; these GPU probes do not make that run accepted or show
  that GPU raycast speeds up the room queue.

## Kaggle artifacts

Raw JSON reports were written in the Kaggle session to:

- `/kaggle/working/gpu-stage-matrix/detector-00805.json`
- `/kaggle/working/gpu-stage-matrix/raycast-00805.json`
- `/kaggle/working/gpu-stage-matrix/habitat-00805/habitat_probe.json`
- Combined JSON: `/kaggle/working/gpu-stage-matrix/gpu-stage-matrix-00805.json`
- Downloadable evidence ZIP: `/kaggle/working/gpu-stage-matrix/gpu-stage-matrix-00805-json-evidence.zip` (4,779 bytes)

The Habitat JSON/stdout recorded the renderer and scene/calibration hashes. The
notebook draft has not been saved as a Kaggle Version, and these Kaggle working
files have not been downloaded into the local repository. The archive link is
shown in the last executed benchmark cell in the Kaggle draft.

## Runtime wiring follow-up

The 00805 Kaggle bundle now has a separate host lock for Torch 2.7.1+cu126 and
TorchVision 0.22.1+cu126. Its notebook selects `YOLOEDetector` on `cuda:0` and
the existing Triton CUDA navigation raycast backend, and requires both CUDA and
Triton to initialize. The CUDA version is deliberately a separate bundle lock;
the CPU host lock remains available for CPU-only setups. Habitat still renders
through the tested software path, and Rebuild native M1–M5 remains CPU-based.
The new bundle/profile have been assembled and their configuration checked
locally, but the CUDA 12.6 wheel install, actual GPU raycast startup and full
acceptance have not yet been runtime-validated in Kaggle.

## State

- **Implemented:** existing detector adapter supports explicit `device`; the
  optional Triton raycast worker/client already exists; this document records
  the short measurements.
- **Correctness-verified:** GPU raycast output exactly matched all five CPU
  masks for the measured deterministic rays; YOLOE device placement, one-label
  output and close confidence score were observed. Detector mask identity was
  not verified.
- **Runtime-validated:** Habitat RGB-D rendered on llvmpipe; YOLOE inference ran
  on a T4; Triton raycast ran on a T4. Full M1–M5 acceptance was rejected, as
  recorded above.
