# Hydra Python binding audit — pinned branch2 build

Audit date: 2026-11-04. Source commit: [`2e58a35baea629eee8838409771876acff015daf`](https://github.com/MIT-SPARK/Hydra/tree/2e58a35baea629eee8838409771876acff015daf). This audit describes the built commit, not Hydra `main`.

## Build and ABI

- Python 3.12.3, NumPy 1.26.4, pybind11 2.11.1, scikit-build-core 1.1.2; Python packages are in `.runtime/hydra_ws/wheelhouse-python/requirements.lock` with artifact hashes.
- The native graph dependency is Spark-DSG `3c40997e4ae739c56ed3cdd6ef5e882d403d8b64`; the ROS workspace pins are in `.runtime/hydra_ws/dependencies.lock.yaml`. Additional TEASER++/Hydra FetchContent sources are locked in `.runtime/hydra_ws/vendor-lock.json`.
- C++ build used GCC 13.3, CMake 3.28.3, ROS Jazzy, Eigen 3.4, OpenCV 4.6, PCL 1.14, and ROS Jazzy GTSAM 4.2.0. Native package artifacts and versions are listed in `.runtime/hydra_ws/system-dependencies.lock.json`.
- `hydra_python` is built with scikit-build-core from `pyproject.toml`; the Python package build requires the separately built/installed `hydra` CMake package and pybind11. A Python package install alone does not build the native dependency graph.

## API verified at the pinned commit

| API | Observed contract | Source |
| --- | --- | --- |
| `load_configs(dataset, labelspace, config_path, bounding_box_type)` | Recursively merges `config/datasets/<dataset>.yaml` and `config/label_spaces/<labelspace>_label_space.yaml`, then applies frontend/backend/reconstruction defaults. The function returns `None` for missing config files. | [`pipeline.py`](https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/src/hydra_python/pipeline.py) |
| `make_camera(...)` | Creates `CameraConfig` with width/height, pinhole intrinsics, min/max range, and `ExtrinsicsConfig`. Defaults to identity body-to-sensor extrinsics. `body_R_sensor` and `body_p_sensor` are writable. | [`pipeline.py`](https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/src/hydra_python/pipeline.py), [`python_sensors.cpp`](https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/bindings/src/python_sensors.cpp) |
| `HydraPipeline.from_config(yaml, camera, robot_id=0, config_verbosity=0, use_step_mode=True, zmq_url="")` | The YAML string is parsed by the native binding. `use_step_mode=True` is supported and exercised. | [`python_pipeline.cpp`](https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/bindings/src/python_pipeline.cpp) |
| `step(timestamp_ns, world_t_body, world_R_body, depth, labels, rgb, feature=FeatureVector())` | Constructs a native `InputPacket` and `PythonSensorInput`; returns `bool`. Quaternion array order is **w,x,y,z**, passed to Eigen's `(w,x,y,z)` constructor. The build probe returned `True`. | [`python_pipeline.cpp`](https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/bindings/src/python_pipeline.cpp) |
| `save_graph(path, include_mesh=True)`, `.graph`, `.reset()` | Graph property returns a clone; `save_graph` delegates to Spark-DSG. Native loader accepts `.sparkdsg`, `.json`, `.bson`, or no extension. The probe saved and reloaded a `.sparkdsg` file through Spark-DSG. | [`python_pipeline.cpp`](https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/bindings/src/python_pipeline.cpp), [`scene_graph.cpp`](https://github.com/MIT-SPARK/Spark-DSG/blob/3c40997e4ae739c56ed3cdd6ef5e882d403d8b64/python/bindings/src/scene_graph.cpp) |
| Shutdown | `start()`/`stop()` exist in the C++ `PythonPipeline`, and the destructor invokes `stop()`, but neither is exposed as a Python method. The probe released the object and forced Python GC; explicit Python `.stop()` raises `AttributeError`. | [`python_pipeline.cpp`](https://github.com/MIT-SPARK/Hydra/blob/2e58a35baea629eee8838409771876acff015daf/python/bindings/src/python_pipeline.cpp) |

## Buffer format and input constraints

- Depth accepts a single channel. `float32` values are passed through unchanged (use metres); `uint16` is interpreted as millimetres and zero becomes NaN. Other formats are rejected by the parser.
- Labels accept one channel of `uint8`, `int8`, `uint16`, `int16`, `uint32`, or `int32`. RGB/depth/labels must share image height and width. At least color or labels must be present alongside depth.
- RGB parsing copies channel indices 0, 1, and 2 directly into the native 3-channel pixel; it does not swap channel order. NeuSymNav must supply RGB in the expected order. A sentinel-color geometry/native test is still required in H2/H3.
- The binding preserves the caller-provided body pose and sensor extrinsics as separate inputs. Correct camera/body composition, simulator coordinate conversion, NaN behavior downstream, and invalid-depth surface suppression remain H2/H3 native correctness gates.
- Hydra's default Habitat labelspace marks label 0 invalid. It must not be reused for the planned unknown-background label 0 without the H3 labelspace contract; the one-frame H1 smoke used label 1 and is not evidence that unknown label 0 retains geometry.
- The one-frame probe generated an empty graph (0 nodes, 0 edges), but `step=True`, graph serialization, native Spark-DSG reload, and object destruction all completed. Empty graph is an expected H1 smoke result and does not pass geometry, object, or room gates.

## Scope of evidence

H1 correctness-verified: import, camera construction, pipeline construction, one `float32` RGB-D step, graph access, `.sparkdsg` save/reload, and destructor shutdown passed. RGB ordering, nonidentity extrinsics, correct metric plane reconstruction, object generation, room updates, multiple instances, and process restart are not proven by this probe.

## H3 semantic labelspace and native scene gates

The runtime labelspace is generated from `configs/taxonomy-v1.json`, not copied
from ADE20K. NeuSymNav reserves label 0 for `unknown_static`, label 1 for `invalid`,
and assigns taxonomy categories stable IDs 2 through 60. Only category IDs enter
Hydra `object_labels`; `invalid_labels` is `[1]`. The generated YAML uses the
native schema (`total_semantic_labels`, `dynamic_labels`, `invalid_labels`,
`object_labels`, `surface_places_labels`, and a list of `{label, name}` entries in
`label_names`). Its canonical labelspace SHA256 is recorded in each HydraFrame.

`HydraLabelRasterizer` accepts a validated `DetectionBatch` and does not own or
invoke a detector. It sorts detections by descending score and then ascending
`detection_id`, paints only unclaimed pixels, lets unknown detections claim label 0,
and applies invalid-depth label 1 last. Empty batches preserve label-0 background;
the adapter separately passes invalid depth as NaN in metres.

The custom labelspace was loaded through the pinned `hydra_python.pipeline.load_configs`
and native C++ parser. On that config, empty-detection geometry produced a native
mesh and the repeated invalid patch produced no mesh vertices. Native semantic-mask
object clustering made two same-class objects, remaining two nodes over eight
repeated views. With unchanged Habitat thresholds, native room fixtures produced
one room in the open-space control and two rooms in the narrow-connection fixture.
See [H3 result](results/hydra-branch2-h3.md) for commands, graph layer IDs, hashes,
and saved native assets.
