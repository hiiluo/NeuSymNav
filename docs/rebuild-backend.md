# Rebuild room backend

The opt-in Rebuild profile runs its pinned native M4 DuDe segmentation worker
and the matching source M5 guard/tracker. NeuSymNav remains the sole public
region snapshot owner. The profile consumes the same accumulated measured
`NavSnapshot` occupancy used by the default region backend; it does not run
Rebuild's RGB-D mapper or replace navigation occupancy.

The adapter accepts only the exact Rebuild worker and Python source pins below.
It imports `standalone_sg` under a private package name so it cannot collide
with the 3DSG `standalone_sg` source package. Geometry, resolution, origin and
the `-1=unknown, 0=free, 100=occupied` raster pass through unchanged. M4 uses
the source `preprocessing_policy=source`; this is not preprocessing parity with
NeuSymNav's `extended_unknown_boundary` DuDe backend. Measured floor support and
clearance are copied to the source `FreeSpaceGrid2D` z arrays where present;
unsupported values remain NaN. Those z arrays are not used to manufacture or
modify occupancy.

Source M5 region IDs are the canonical IDs in this backend. A candidate is
published only after its M5 guard accepts it and NeuSymNav validates source
revision, polygon simplicity, geometry and immutable snapshot construction. M5
tracker state is copied transactionally and committed with the snapshot. If
validation fails, the accepted snapshot and its `accepted_nav` pairing remain
unchanged and consumers see stale geometry. A native M4 request can still
advance native internal state before a downstream rejection, as with the
existing DuDe integration; reset on origin/resolution/shape change is explicit
and does not clear M5 region identity.

Pinned runtime inputs:

- Worker: `Rebuild_3DScene_OccuSG/build/native-m4-dude/occusg_dude_worker`
- Worker SHA-256: `6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693`
- `src/standalone_sg/**/*.py` aggregate SHA-256: `60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0` (50 files)
- DuDe configuration: 1.5 m decomposition threshold, 0.5 m safety distance,
  30 s request timeout, source preprocessing policy

Run a calibrated machine-local profile with:

```bash
bash tools/run_rebuild_map_demo.sh 00805 600
```

Use `bash tools/run_rebuild_map_demo.sh 00805 --preflight` to check assets and
runtime readiness. The wrapper creates an ignored config at
`.runtime/rebuild-backend-20261102/configs/` from `configs/demo-00805.local.json`
and writes the worker/source pin record to
`.runtime/rebuild-backend-20261102/worker/source-pins.json`. It does not alter
the selected default `run_map_demo.sh` backend.

This backend is a segmentation comparison on a common occupancy input. It
does not establish RGB-D/M4 mapping parity, whole-scene Rebuild equivalence,
room semantic accuracy, or improved navigation. Runtime reports must include
the backend diagnostics and the exact source map revision paired with the
accepted region snapshot.
