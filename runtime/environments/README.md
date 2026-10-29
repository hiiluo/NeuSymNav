# P10 runtime environments

Created under the user's 2026-10-28 request to implement and complete P10.
All prefixes and download caches are inside NeuSymNav/.runtime. The core .venv
and both source folders remain unchanged. No new model or dataset was needed.

- Sensor: `.runtime/sensor/bin/python`, Habitat-Sim0.3.3/headless, Python3.9,
  NumPy1.26.4/quaternion. Python3.10 dry-run was unsatisfiable for the available
  headless build. Exact channel URLs/checksums are in sensor-linux-64.explicit.txt;
  full available SHA256 and solver actions are retained in sensor-solve-py39.json.
- Detector: `.runtime/detector/bin/python`, Python3.12, torch2.7.1+cu126,
  torchvision0.22.1, ultralytics8.3.221, NumPy1.26.4. Hash lock is retained.
  Local CLIP tokenizer/runtime wheel copies the existing MIT dependency from
  the pinned Ultralytics/CLIP commit7ffa84b3bfa40c42ecc1c77147a855e69cb2dd40,
  preserving LICENSE/metadata. Source hashes and wheel manifest:
  `runs/p10-native-preparation/clip-wheel.json`. It imports from the new prefix,
  never from sibling source. Existing YOLOE/MobileCLIP weights remain external
  checksum-pinned assets. No auto-download is enabled in the detector adapter.
- Host: `.runtime/host/bin/python`, Python3.12 with existing system CPU packages
  plus isolated NumPy1.26.4/Numba0.61.2/llvmlite0.44.0. This selects the mapper's
  existing optional kernel, without changing its algorithm or the core venv.
  First JIT compilation is startup work; report warm/cold timings separately.
- Appearance stays off/optional. No OpenCLIP checkpoint or environment was added.

GPU/net access is unavailable in the default task sandbox. Approved external
execution exposes the existing RTX3060Laptop6GiB and driver580.178.04; no driver
installation, device-node creation, reboot or OS change was needed. Actual
native smoke/campaign must use that execution context; a default-sandbox
NVIDIA-SMI failure is not evidence that the host driver is broken.

Use explicit venv paths in config. Do not resolve the detector Python symlink to
/usr/bin/python3.12: doing so bypasses its venv/site-packages. Config assets keep
the requested absolute path and checksum the executable bytes.

Runtime environment preparation and finite native sensor/model smokes are not
P10 acceptance. See docs/implementation-status.md for the latest gates.

Current native candidate preparation uses separate `native-runtime4-<scene>-seed-<seed>.json` configs (primary120×160, navigation240×320, appearanceoff). These are preparation inputs, not a certified profile. Worker script/config/scene/calibration pins must match the exact reviewed snapshot. Optional `budgets.archive_cap=1073741824` allocates1GiB of the existing raw2GiB budget to full capture archive; RunQuota still charges reservations and actual bytes under raw2GiB/total8GiB. Defaults remain unchanged. Do not reuse diagnostic artifacts as campaign outcomes or infer runtime validation from environment availability.
