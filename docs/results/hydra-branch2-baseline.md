# Hydra branch2 baseline — 2026-11-04

## H0 — isolated source and runtime baseline

**State:** implemented and correctness-verified; runtime validation not performed.
No Hydra repository was cloned or built as part of H0. The branch remains
uncommitted.

The source checkout was `Kiet_branch` at
`62f16fcf0b1ae508b49820e0184e99714387c490`, with dirty tracked and untracked
work. H0 created `/home/kiettran05/Desktop/test_Room_segmentation/NeuSymNav/.runtime/worktrees/Kiet_branch2`
on the exact `Kiet_branch2` branch from that HEAD, then applied the aggregate
binary patch and copied the NUL-delimited untracked inventory. The snapshot
contains 22 modified tracked files and 69 untracked files (91 distinct paths).
All 91 file hashes match the source snapshot. The 11 Python files under
`src/neusymnav/navigation/` also match byte-for-byte. See the ignored evidence
bundle at `.runtime/hydra-handoff/` for the staged/unstaged/aggregate patches,
untracked archive and per-file SHA-256 manifest.

The original checkout remains `Kiet_branch` at the same HEAD. It was not
staged, reset, stashed or committed. One `colcon version-check` probe created a
new `log/` under the original checkout; that generated directory was removed
immediately, restoring the original dirty inventory.

### Actual movement profile

H0 captured both ignored local profiles instead of relying on YAML defaults:
`configs/demo.local.json` (`local-intel-00802`) and
`configs/demo-00805.local.json` (`local-intel-00805`). Both use a 5 Hz primary
capture, 10 Hz navigation, 5 cm NavMap with stride 1, a 0.20 m radius robot,
and the existing sensor/detector/UI workers. The 00805 profile's scene,
dataset, YOLOE checkpoint, MobileCLIP encoder, calibration, interpreter and
worker hashes are recorded in `.runtime/hydra-handoff/configs/`. Generated
branch2 copies have worker scripts, taxonomy and UI Python paths remapped to
the child worktree. Scene/model/calibration assets and the existing sensor/
detector interpreters remain read-only external references; no environment
was symlinked into the new worktree.

The source navigation module/config hashes are the baseline for H5/H7. Hydra
must not alter the command TTL, 100 ms horizon, 0.2 m/s cap, or any controller
or frontier implementation. The active 00805 config does not contain an
explicit controller override; its effective behavior comes from the captured
source files. The older Rebuild region worker in this baseline profile is not
evidence of a Hydra integration.

### Python and native package baseline

The old checkout's `.venv/bin/python` is Python 3.12.3. `python -m pip` is not
installed in that venv, so H0 used the system pip's `--python` inspection mode;
it changed nothing in the source environment. `pip freeze --all` and
`pip inspect --local` were captured. The editable NeuSymNav path was kept out
of the dependency list and is pinned separately by the H0 source hashes.

The child `.venv` is a physically separate environment. Its interpreter has a
separate `sys.prefix`; its 14 non-project distributions match the baseline
versions and installed `RECORD` hashes, and imports for NumPy, SciPy, PyYAML,
Pillow, pytest and NeuSymNav succeeded. All 332 native-extension SHA-256 hashes
and normalized `ldd` targets match the source environment. Exact environment
details are in `.runtime/hydra-handoff/environment-lock.json` and
`.runtime/hydra-handoff/branch2-env/`.

The first wheel request failed in the sandbox and the first reviewed transfer
timed out on the SciPy wheel. A bounded retry completed all 14 pinned wheels.
The branch2 `.venv` was then recreated from that local wheelhouse with
`pip install --no-index --require-hashes`; no baseline version was changed.
The wheel SHA-256 list and hashed requirements are in
`.runtime/hydra-handoff/wheelhouse-manifest.json` and
`.runtime/hydra-handoff/requirements.baseline.lock`. The independent install
matches all 14 versions and 6,209 non-generated package content files, plus
332 native extension hashes and normalized dynamic link targets.

### Verification

| Check | Result | Evidence |
| --- | --- | --- |
| Branch, HEAD, copied dirty inventory and protected navigation hashes | pass | `.runtime/hydra-handoff/source-manifest.json` |
| Baseline/child exact wheel install, package contents and native links | pass | `.runtime/hydra-handoff/environment-lock.json`, `requirements.baseline.lock` |
| Navigation, controller, motion guard and corner regression tests | 135 passed, exit 0 | `.runtime/hydra-handoff/navigation-baseline.log` |
| Recorded package replay/evaluator path | 20 passed, exit 0 | `.runtime/hydra-handoff/replay-baseline.log` |
| `Kiet_branch` ref/index and local profiles | unchanged; hashes captured | `.runtime/hydra-handoff/snapshot.json` and `configs/` |

These are CPU/correctness checks. They do not prove Habitat runtime, Hydra
bindings, native graph/object/room production, UI integration, or live
movement non-regression. No Hydra or GPU workload ran.
