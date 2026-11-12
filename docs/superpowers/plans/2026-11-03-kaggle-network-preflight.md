# Kaggle Network Preflight Implementation Plan

> **For agentic workers:** Implement inline; do not use subagents. Steps use checkbox syntax.

**Goal:** Detect Kaggle DNS/TCP egress failures before environment bootstrap and identify the failing hosts.

**Architecture:** Add a standard-library probe script to the pinned 00805 bundle. The notebook runs it before micromamba/conda/pip setup and stops with its JSON report on failure. Bundle validation pins the helper SHA alongside the notebook and existing diagnostic/requirements pins.

**Tech Stack:** Python standard library, Jupyter notebook JSON, unittest.

**Spec:** User-approved continuation of the Kaggle operating procedure in `kaggle/rebuild_rgbd_00805/README.md`.

## Global Constraints

- Do not change GPU profile, source/binary pins, recording limits, timeouts, queue capacity, or acceptance checks.
- Probe DNS and TCP port 443 only; no package installation, model download, or pipeline launch.
- Keep Kaggle files under `kaggle/rebuild_rgbd_00805/` and maintain the bundle manifest/validator pin contract.

## Review Focus

- DNS failure is reported by hostname and prevents TCP attempts.
- TCP failure after successful DNS is distinguished from DNS failure.
- Success requires each configured host to resolve and accept a TCP connection.
- Notebook cannot bootstrap an unpinned probe helper.

### Task 1: Pinned connectivity probe and notebook gate

**Files:** Create `kaggle/rebuild_rgbd_00805/network_preflight.py` and its unittest; modify `m1_m5_smoke_00805.ipynb`, `prepare_full_bundle.py`, `validate_bundle.py`, validator tests, README.

- [ ] Add failing tests for DNS failure, TCP failure, and success.
- [ ] Implement the standard-library DNS/TCP probe and CLI JSON report.
- [ ] Pin the helper in the bundle manifest and validate that pin for directory and ZIP inputs.
- [ ] Run the probe as a notebook gate before bootstrap, require its manifest SHA, and update run instructions.
- [ ] Run focused tests, parse the notebook cells, validate a rebuilt bundle, and record Kaggle runtime status separately.
