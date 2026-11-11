# Hydra branch2 H1 — native bindings build and probe

Date: 2026-11-04. Worktree: `.runtime/worktrees/Kiet_branch2`, branch `Kiet_branch2`.

## Gate result

**H1 passed; binding-built and correctness-verified.** The pinned Hydra workspace and its Python bindings compiled with exit code 0. A dedicated Python 3.12.3 environment imported Hydra and Spark-DSG, constructed a camera and pipeline, accepted one RGB-D frame (`step=True`), read the graph, saved `.sparkdsg`, reloaded it through Spark-DSG, and shut down through object destruction/GC. The serialized graph has 0 nodes and 0 edges; this smoke frame is not evidence for geometry, object creation, or rooms. Full runtime validation of NeuSymNav integration remains pending H2–H7.

## Pinned sources and ABI

- Hydra: `2e58a35baea629eee8838409771876acff015daf`.
- Hydra-ROS manifest: `8f3b7e369e2bda49d24eba889a5bd0dfc5903a62`.
- ROS workspace dependency closure: `.runtime/hydra_ws/dependencies.lock.yaml` (SHA-256 `6898148caf697b0e76b96fb946bf0e8277e620f8cf55b4d87ef294382fa2098d`). It includes Spark-DSG `3c40997e4ae739c56ed3cdd6ef5e882d403d8b64` and the local Python dependency `spark_dataset_interfaces` at `d770fec99ae025fbef10cf978c382aff72e1a2cf`.
- Hydra/TEASER++ FetchContent source pins: `.runtime/hydra_ws/vendor-lock.json`.
- Python wheel closure: `.runtime/hydra_ws/wheelhouse-python/requirements.lock`, 27 wheel artifacts, installed using `pip --require-hashes`. Lock SHA-256: `abac05cbc501d47ddd94b26a48ffb07aebdecb051ae60bdf7aa89399befc9861`. Python pins include NumPy 1.26.4, SciPy 1.17.1, pybind11 2.11.1, and scikit-build-core 1.1.2.
- Native system dependencies downloaded/extracted only into `.runtime/hydra_ws/sysroot`; exact package versions and SHA-256 hashes are in `.runtime/hydra_ws/system-dependencies.lock.json` (lock SHA-256 `41263a802dcf6989f104802f2c65f7df69b10ea9ee74409b21d6bc7357ee46fd`). ROS Jazzy GTSAM 4.2.0 supplies `gtsam_unstable`; the Ubuntu GTSAM dev package lacked those headers. The sysroot-local GTSAM CMake overlay excludes a missing `CppUnitLite` test-only target that the Ubuntu export incorrectly references. No host/system packages were installed.
- Build versions: Ubuntu 24.04, ROS Jazzy, GCC 13.3, CMake 3.28.3, Eigen 3.4, OpenCV 4.6, PCL 1.14, GTSAM 4.2.0.

## Verification commands and results

| Command/action | Result | Artifact |
| --- | --- | --- |
| `colcon build --base-paths src --build-base build --install-base install --packages-up-to hydra --parallel-workers 2 ...` with pinned local prefixes, `HYDRA_ENABLE_PYTHON=ON`, `HYDRA_ENABLE_EVAL=OFF`, `BUILD_TESTING=OFF` | Exit 0; 8 packages finished: config_utilities, kimera_rpgo, pose_graph_tools, spatial_hash, spark_dsg, teaserpp, kimera_pgmo, hydra | `.runtime/hydra_ws/log/latest_build/` |
| Rebuild `spark_dsg` with `SPARK_DSG_BUILD_PYTHON=ON`, `SPARK_DSG_BUILD_EXAMPLES=OFF`, `BUILD_TESTING=OFF` | Exit 0; `_dsg_bindings.cpython-312-x86_64-linux-gnu.so` installed | `.runtime/hydra_ws/install/spark_dsg/` |
| Build/install `hydra_python` using its audited scikit-build-core backend, no build isolation, no dependency resolution | Exit 0; wheel `hydra_python-0.0.1-cp312-cp312-linux_x86_64.whl`, SHA-256 `a29867a3f3f7ac1ea6df83755944f8974a36e48de833338fb917e1415268d785` | `.runtime/hydra_ws/.venv/` |
| `.runtime/hydra_ws/.venv/bin/python .runtime/hydra_ws/probe/h1_pipeline_probe.py` with ROS/workspace setup and native library paths | Exit 0; `step_result=true`, save/reload succeeds, object destruction succeeds; graph 0 nodes/0 edges | `h1-probe.json`, `h1-probe.sparkdsg`, `h1-probe.log` |
| `ldd` on Hydra and Spark-DSG Python extensions with native runtime paths | Exit 0; no `not found` entries | `h1-hydra-bindings-ldd.txt`, `h1-dsg-bindings-ldd.txt` |

To activate the branch2 native runtime, source `.runtime/hydra_ws/env.sh`; its SHA-256 is `a3db15c5defd22c99adf639c48e64dea67b2aca6982196f028e489488ed0bb72`. This script only scopes ROS, Python and library paths to the Hydra child workspace.

The first build attempts exposed missing `nlohmann_json`, Ubuntu GTSAM's omitted unstable headers, TEASER++'s implicit PMC clone, and Hydra's implicit nanoflann clone. These were resolved in the isolated sysroot/vendor directory with exact package/commit pins. An earlier probe attempt also exposed that `graph.nodes` is an iterator and that Spark-DSG requires the `.sparkdsg` extension; the final probe uses the native API correctly. A direct Python `.stop()` call is not available; C++ destructor shutdown is the verified path.

## Binary/artifact hashes

- `libhydra.so`: `5cce5ce5c6d7bb374226969a69144a55a7d5d70862f8976fdfcae16f719a62dc`
- installed `_hydra_bindings.cpython-312-x86_64-linux-gnu.so`: `d4fe28b63aa63a5dcc730473ea727c2015c981623f38bf10ae592251c18a8d5d`
- `libspark_dsg.so`: `83a89506cd4e140bf566f0b65930fb1b05b3f8e6ca6b8a15a95d292e3d07fc14`
- `_dsg_bindings.cpython-312-x86_64-linux-gnu.so`: `73b70d94dad4d50b050a7ec26861f75c66ef67df423c90cf0ea3f056a8eedd6c`
- saved graph: `ad0fa538f1934fa068aff4a8bc4caca0660428a50caa89815582278a4a2de954`
- probe result JSON: `d681d0c5f585c1c43390093d1dc4996ef9d30a6bd6006ecb01b71b9fc29b6681`
- probe log: `e128412ef14cf28b64cf6f24a831b3bd2a4cf6736b9fe7253c99be39bc50b42e`
- Python wheel lock: `abac05cbc501d47ddd94b26a48ffb07aebdecb051ae60bdf7aa89399befc9861`
- vendored-source lock: `7de66b8b972b9c98ed75231a38a0b062949ce558b838a7f181be5ff0132bfff6`
- final Python freeze: `dca79fcf0ebd7e6441b6eb56a52193a7ab1bbd2dff6873fcf8fc0efe93ac2f89`
- Hydra/Spark-DSG `ldd` outputs: `9075c858666e7b57cf31242f85fa861b8c9f4767a2621d945712c9270333a423` and `68aa1af2267bda915fcb35fe35e334ca203247cbcf42acf00511c695d5ab14ab`

## Remaining work

H2 must prove transforms, calibration, RGB ordering, depth units, and invalid-depth behavior. H3 must prove measured geometry, object nodes from predicted masks, and room updates. H4–H7 remain unimplemented. The tiny H1 frame created no graph nodes, so it does not satisfy any native geometry/object/room gate.
