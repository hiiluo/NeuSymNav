# Kaggle RGB-D M1–M5 bundle for map 00805

This folder keeps Kaggle packaging and notebook code out of NeuSymNav's runtime
package. It has two inputs: the earlier small Habitat probe and a full, private
M1–M5 smoke bundle. The full run uses live Habitat RGB-D and the pinned
NeuSymNav/Rebuild path; it does not use semantic ground truth or fabricate map
outputs.

## Build the private full bundle

Run from the NeuSymNav root:

```bash
./.venv/bin/python kaggle/rebuild_rgbd_00805/prepare_full_bundle.py \
  --output .runtime/kaggle/rebuild-rgbd-00805-full-gpu
```

The script writes an ignored staging directory and ZIP under
`.runtime/kaggle/rebuild-rgbd-00805-full*`. It includes the NeuSymNav Python
package and runner tools, map profile/calibration, 00805 scene and navmesh,
the two detector weights, Habitat worker, region worker, pinned Rebuild M1–M5
source and binaries, native shared-library dependencies, separate CPU and Kaggle CUDA host requirement locks, and checksums. It refuses to package changed Rebuild pins. It does
not copy a virtual environment, recordings, `runs/`, credentials, or unrelated
maps. Keep the dataset private unless the scene and model licenses allow wider
redistribution.

Before uploading, validate that the ZIP, its manifest, and the notebook in this
folder match:

```bash
./.venv/bin/python kaggle/rebuild_rgbd_00805/validate_bundle.py \
  .runtime/kaggle/rebuild-rgbd-00805-full-gpu-stable-v3.zip
```

The verifier checks ZIP integrity and safe member paths, expected bundle/map/GPU
identity, notebook SHA, and the detector diagnostic, network preflight, and GPU
lock SHAs. It accepts either the ZIP or its expanded bundle directory. Do not
upload if it reports `FAIL`; rebuild the bundle after changing the notebook or
a pinned helper/lock.

## Run the Kaggle notebook

Import `m1_m5_smoke_00805.ipynb` as a Kaggle Notebook and attach the ZIP as a
private Kaggle Dataset. Select a Kaggle GPU accelerator and enable Internet for first setup. The notebook builds
a Python 3.12 host/detector environment with pinned CUDA 12.6 PyTorch/Triton and a separate Python 3.9
Habitat-Sim 0.3.3 headless environment. Before any environment installation, it
checks DNS and outbound TCP port 443 for the micromamba, Conda, PyPI, and PyTorch
hosts. It prints one JSON status per host and stops immediately if DNS or TCP
fails; the probe does not install packages or download assets. It then requires
CUDA to be visible, uses YOLOE on `cuda:0`, and runs navigation raycasting with
the Triton CUDA backend. The Habitat renderer remains on the previously
validated llvmpipe software path; Rebuild native M1–M5 mapping remains
CPU-bound. It then runs the NeuSymNav preflight and
one bounded **180-second** live RGB-D diagnostic smoke with the UI disabled.

The notebook exports the real M3 occupancy map, M5 region outlines, hierarchy
graph, logs, runtime summary, and acceptance report to `/kaggle/working`. Set
`NEUSYMNAV_RUN_SECONDS` in a notebook cell before Run All to select a
duration from 1 second through the pinned profile's current 600-second cap; 180
seconds is the default smoke. Every execution gets a unique run directory, and
its archive includes only that run so repeated executions cannot mix artifacts.
M5 is
accepted only if the project's acceptance checker confirms a completed run,
clean recording/shutdown, current M3/M5 pairing, and valid polygon geometry. A
failed or incomplete run remains visible as rejected. No retry is selected to
make a result look better. After the live run, a diagnostic-only one-frame probe
uses the exact saved RGB-D keyframe and startup detector recipe to measure the
detector request path and YOLOE prediction on the allocated GPU. Its longer
diagnostic timeout is kept separate from the production timeout and cannot
publish to maps or hierarchy. The report records the detector's observed device
only when prediction completes; a configured CUDA device alone is not treated
as GPU evidence.

The output archive is `rebuild-rgbd-00805-m1-m5-results-<duration>s.zip` inside
the unique run directory. Notebook export is
a post-run review artifact, not a streaming live UI. GPU acceleration applies to
YOLOE detector inference and NeuSymNav navigation/control-map raycasting; it does
not accelerate Habitat's current llvmpipe renderer or Rebuild native M1–M5 room
mapping. The result records actual device status per stage instead of a single
GPU boolean. Strict acceptance conditions remain unchanged.

## Depth preview

The Habitat depth PNG uses a per-frame 2nd–98th percentile stretch over valid
depth pixels; invalid pixels stay black. The chosen display range is recorded in
the JSON report. This only changes visualization, not the saved depth values.

## Current validation state

- The Kaggle GPU notebook now requires the CUDA runtime lock and explicit CUDA
  device selection. Rebuild the full bundle after source changes and reattach
  the generated `*-gpu.zip`; the previously uploaded CPU-only bundle does not
  include the updated GPU runtime configurator/lock.
- Habitat RGB-D alone has already passed on Kaggle for map 00805.
- The full bundle's local preflight passes with the pinned source/binary hashes.
- A local 30-second staged-bundle integration run completed capture and shutdown,
but ended without an accepted M5 region. Its acceptance checker correctly
rejects it; this does **not** validate full M1–M5 acceptance.
- The latest completed Kaggle GPU run used Dataset Version 3 (Private), passed preflight,
  and produced 144 sensor frames plus one valid, non-stale M5 polygon paired to
  the latest accepted M3. The run still failed strict acceptance: detector graph
  work exceeded its whole-operation deadline, room admission was 5/70 frames,
  runtime shutdown/measurement were incomplete, and hierarchy export was absent.
  No acceptance limit changed. See `docs/implementation-status.md` for counters
  and the known missing worker stderr detail.
- The diagnostic harness is implemented locally and is added to newly built
  full bundles. Its Kaggle runtime result has not yet been validated. Do not use
  this harness or the failed 00805 smoke to start a long map campaign.
- The notebook now supports run-scoped outputs and durations up to the existing
  600-second profile cap. This is a bounded smoke/repro workflow, not yet a
  multi-hour campaign runner; storage caps and clean strict acceptance must be
  established before extending it.
- Dataset Version 4 (Private) contains the matching `*-gpu-stable-v3.zip`
  bundle. The notebook was imported into the Kaggle draft, that exact private
  dataset was attached, GPU T4 x2 was selected, and Internet showed enabled.
  Two Run All attempts both failed at the first `micro.mamba.pm` download with
  `socket.gaierror: [Errno -3] Temporary failure in name resolution`. No
  environment setup, NeuSymNav preflight, or M1–M5 runtime smoke was reached.
  This is a Kaggle-kernel DNS/egress failure observed while the Internet setting
  was on; it does not validate or reject the pipeline. The failed draft session
  was stopped to release its GPU. See `docs/implementation-status.md` for the
  exact runtime checkpoint.

## Repeatable Kaggle operating procedure

1. Build a fresh bundle into a new ignored `.runtime/kaggle/` directory. Never
   reuse an old ZIP after changing the notebook or a helper; the bundle manifest
   pins both the helper and notebook SHA-256.
2. Upload that ZIP as a **new private Dataset version**. Attach exactly that
   version to the draft notebook. The notebook rejects older bundles without
   the pinned detector diagnostic helper and requires one unambiguous bundle.
3. Select a GPU accelerator and enable Internet for environment setup; keep
   the bundle and dataset private. Before installing the environments, confirm
   the Kaggle kernel can resolve and reach `micro.mamba.pm`, `conda.anaconda.org`,
   and the PyTorch/PyPI hosts. An enabled Internet toggle does not prove kernel
   DNS/egress is working. If the bootstrap reports a name-resolution error,
   stop the draft session and retry only after connectivity is restored; do not
   interpret that as a pipeline result. Once setup succeeds, run all cells for
   a bounded 180-second smoke.
4. Download the archive produced under the unique `runs/<run-id>/` directory.
   Review `kaggle_result.json`, `review/review.json`, run summary, detector
   diagnostic, logs, M3/M5 preview and hierarchy preview together. The only
   accepted result is the project's unchanged acceptance checker returning
   `accepted=true`, with a completed run, clean shutdown, current M3/M5 pair and
   valid non-stale M5 region(s).
5. A rejected smoke blocks long runs. First diagnose the recorded stage timing,
   detector stage trace, room queue counts, recording certificate, measurement
   completion and disk/resource caps; fix the evidenced cause and repeat the
   bounded smoke. Do not raise worker timeouts, queue capacity or acceptance
   thresholds to force a pass.
6. Only after an accepted smoke, explicitly review the profile's duration and
   storage caps for the intended session. The current map profile allows at
   most 600 seconds, so it is not yet configured for an entire scene traversal.
   Keep a single run within Kaggle's session/storage limits and archive each run
   separately. A multi-hour or multi-map campaign remains out of scope until a
   longer profile has its own storage budget, interruption/recovery behavior and
   strict-acceptance validation.

Each notebook rerun creates a new run directory and the exporter consumes that
same directory. It does not reuse a fixed path from a previous run. Keep the
latest notebook and matching bundle together. Dataset Version 3 remains the
last bundle whose Kaggle run reached the NeuSymNav pipeline. Version 4 contains
the new detector diagnostic and notebook pins; its draft stopped at dependency
bootstrap because of Kaggle-kernel DNS failure, so Version 4 still needs a
successful setup, preflight, and bounded M1–M5 smoke before it can serve as a
long-run baseline.
