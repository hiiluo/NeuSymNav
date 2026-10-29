# CPU-only calibrated capture fixture

`capture-v1.json` is an analytic synthetic capture, not native Habitat output.
It has 2×3 RGB/depth samples, independently declared K, source Y-up sensor
translation (1,4,3), and source Habitat camera axes. Normalization produces
canonical camera translation (1,-3,4) and optical forward +Y. Depth contains
zero, NaN and the calibrated 10 m clip plane; these stay invalid and receive no
free-space certificate. Source host/boot clock and pose are fixture values.

The file uses P02 JSON/NPZ wire v1 and has an embedded SHA-256 over metadata
and raw archive. It is suitable for host codec and replay smoke, never proof
of native sensor runtime or map/navigation coverage.
