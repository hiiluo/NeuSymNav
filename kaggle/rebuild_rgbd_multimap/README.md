# Rebuild RGB-D multi-map Kaggle work

This folder contains Kaggle-specific measurement and runner planning artifacts;
it does not change NeuSymNav runtime code.

- [GPU stage matrix for 00805](GPU_STAGE_MATRIX_00805.md) records detector,
  Habitat renderer and Triton raycast measurements with their limits.
- [Multi-map runner design](RUNNER_DESIGN.md) defines profile contents,
  fail-closed preflight checks and strict smoke gates before any campaign.

No multi-map runner is implemented yet. Campaign execution is blocked until
runner preflight and a live M1–M5 smoke pass the existing acceptance checker.
