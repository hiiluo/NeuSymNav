# YOLOE-26m / 640×480 observation — 2026-10-29

User explicitly requested higher-resolution observation and YOLOE-26m-seg.
Prepared profile: `configs/p10/demo-yoloe26m-640x480-00861.json`.

- Actual primary RGB AND matching primary depth:480×640 H×W. Detector imgsz640.
- Existing pinned local `yoloe-26m-seg.pt` (70,443,185bytes) and `mobileclip2_b.ts`
  (~243MiB), both already present in the read-only reference asset directory.
- Same taxonomy, confidence threshold0.25, max30detections and CUDA0.
- Navigation depth stays180×240. HFOV/extrinsics/floor/footprint/TTL/proof and
  recording/runtime memory caps unchanged. Actual K/calibration ID are calculated
  from the native sensor projection by the existing worker, not scaled old K.
- New episode/output isolates model/resolution provenance from earlier runs.

## Verified dependency blocker

Current `.runtime/detector/bin/python`: Python3.12, Ultralytics8.3.221,
Torch2.7.1+cu126. Fresh CPU checkpoint load fails: missing YOLOESegment26 and
Proto26 classes. Read-only Conda/venv/cache inventory found no compatible
existing Ultralytics. See `runs/yoloe26-640x480-20261029/compat/report.md`.
Preflight checking paths alone cannot certify model loading.

## Minimal environment proposal, awaiting user approval

Earlier user instructions asked to review environment dependencies and disk
estimates before installation. Therefore no environment installation yet.

Create isolated `.runtime/detector26` with existing Python3.12, install only
`ultralytics==8.4.0` without dependency upgrades, then add a read-only .pth import
path to the existing detector environment to reuse Torch/CUDA, torchvision,
NumPy, OpenCV, Polars, local CLIP tokenizer and other already installed packages.
Install the wheel BEFORE adding that path so the package manager cannot try to
uninstall the old detector package. The new environment's own package directory
precedes the reused dependency directory. Keep the old environment intact.

Official v8.4.0 source contains both required classes:
https://raw.githubusercontent.com/ultralytics/ultralytics/v8.4.0/ultralytics/nn/modules/head.py
and Proto26 in block.py. Its documented dependency floors are already met by
the inspected existing packages. This is a compatibility candidate until actual
checkpoint/prompt loading and inference pass; no silent model/runtime fallback.

Estimated incremental download2–5MB and disk20–50MB including the small venv,
package and cache; reuse existing multi-GB Torch/CUDA dependencies. No model or
dataset download, training, system installation or sibling-source modification.
Exact resolved wheel SHA/bytes and actual disk usage will be recorded.

Proposed execution after approval:

```sh
UV_CACHE_DIR="$PWD/.runtime/cache/uv" uv venv --python /usr/bin/python3.12 .runtime/detector26
UV_CACHE_DIR="$PWD/.runtime/cache/uv" uv pip install --python .runtime/detector26/bin/python --no-deps 'ultralytics==8.4.0'
# Add the existing detector site-packages path via .pth AFTER wheel installation.
# Audit import locations/versions, checkpoint/MobileCLIP2 loading, then finite inference.
```

## Validation and limits

Verify actual source640×480 RGB/depth/K/calibration and exact-size masks. Perform
bounded native inference and demo with existing assets; retain failures and
report latency/resource/recording support. The input has16× as many primary
pixels as120×160, so storage/IPC/semantic costs increase. Prior10Hz evidence
cannot certify this profile. Higher score is not guaranteed and confidence is
not an accuracy metric. The old demo default remains until the requested model
actually loads; staged profile is explicitly not runnable before runtime setup.


## Executed after user approval

User approved the isolated runtime and small dependency installation. Installed
8.4.0 first (1.1MiB wheel), preserved that attempt, then discovered checkpoint
metadata saved version8.4.24 and matched that version in the SAME isolated runtime
(1.2MiB wheel). No dependency/model/dataset downloads or upgrades. Runtime directory
reported4.6MiB; reused Torch/CUDA remain in the original environment.

New runtime satisfies all12 declared Ultralytics dependency specifiers via the
approved .pth reuse path and all imports succeed. The package manager's static
`uv pip check` ignores .pth and reports12missing packages; that output is retained
with its scope, rather than claimed pass. Actual `importlib.metadata` plus import
checks and native worker provenance establish dependency availability. The old
interpreter still reportsUltralytics8.3.221. Exact59prompt parity also passes on8.4.24.

Native captures prove primaryRGB/depth640×480, expected pixel-centre K and changed
primarycalibration; navigation calibration/resolution stays identical. Actual
nonempty committed masks640×480 pass SHA/source/geometry audits. Native30seconds:
incomplete due rawquota, retained; native20seconds:completed/raw292of292/resources
complete/cleanupclean, actual detector/object commits. New default wrapper uses
this profile with20seconds, no silent model fallback. Measured control7.388Hz,
p95165.476/p99173.716ms,142/142deadline misses; confidence gain unproven.
[Full checkpoint](../runs/yoloe26-640x480-20261029/report.md).
