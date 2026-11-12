import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).with_name("configure_runtime.py")
spec = importlib.util.spec_from_file_location("configure_runtime", MODULE_PATH)
configure_runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure_runtime)


class ConfigureRuntimeTest(unittest.TestCase):
    def test_build_runtime_config_rebinds_every_asset_to_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"
            project = bundle / "project"
            scene = bundle / "scene" / "scene.basis.glb"
            dataset = bundle / "scene" / "hm3d_minival_basis.scene_dataset_config.json"
            taxonomy = project / "configs" / "taxonomy-v1.json"
            checkpoint = project / "local-assets/models/yoloe-26m-seg.pt"
            encoder = project / "local-assets/models/mobileclip2_b.ts"
            region = project / "local-assets/native/bin/occusg_dude_worker"
            m23 = bundle / "Rebuild/build/native-m3/occupancy/standalone_sg_octomap_fixture_runner"
            m4 = bundle / "Rebuild/build/native-m4-dude/occusg_dude_worker"
            source = bundle / "Rebuild/src/standalone_sg"
            sensor_script = project / "src/neusymnav/sensors/habitat_worker.py"
            detector_script = project / "src/neusymnav/perception/detector_worker.py"
            raycast_script = project / "src/neusymnav/mapping/gpu_raycast_worker.py"
            host_target = root / "host-python-executable"
            host_python = root / "env/bin/python"
            habitat_python = root / "habitat-python"
            for path in (scene, dataset, taxonomy, checkpoint, encoder, region, m23, m4,
                         source / "__init__.py", sensor_script, detector_script, raycast_script,
                         host_target, habitat_python):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            host_python.parent.mkdir(parents=True)
            host_python.symlink_to(host_target)
            region.chmod(0o755)
            m23.chmod(0o755)
            m4.chmod(0o755)
            profile = {
                "schema_version": 1,
                "mode": "live",
                "profile": "baseline",
                "episode": {"id": "map-00805", "floor_id": "floor-0", "primary_sensor_id": "primary-rgbd"},
                "floor": {"z_m": 0.0, "datum_source": "test", "calibration_sha256": "a" * 64},
                "sensor_config": {
                    "scene": {"path": "scene/scene.glb"},
                    "scene_dataset": {"path": "scene/dataset.json"},
                },
                "detector": {
                    "checkpoint": {"path": "model"}, "encoder": {"path": "encoder"},
                    "taxonomy": {"path": "taxonomy"},
                },
            }
            template = bundle / "profile_template.json"
            template.write_text(json.dumps(profile))
            manifest = {
                "map": "00805",
                "pins": {"m23_sha256": hashlib.sha256(b"fixture").hexdigest(),
                         "m4_sha256": hashlib.sha256(b"fixture").hexdigest(),
                         "source_tree_sha256": "b" * 64},
            }
            (bundle / "manifest.json").write_text(json.dumps(manifest))
            output = root / "runtime.json"
            configure_runtime.build_runtime_config(
                bundle=bundle, template=template, host_python=host_python,
                habitat_python=habitat_python, output=output,
                detector_device="cuda:0", raycast_backend="triton_cuda",
            )
            result = json.loads(output.read_text())
            self.assertEqual(result["sensor_config"]["scene"]["path"], str(scene))
            self.assertEqual(result["sensor_config"]["scene_dataset"]["path"], str(dataset))
            self.assertEqual(result["workers"]["room_pipeline"]["source_root"], str(source.parent.parent))
            self.assertEqual(result["workers"]["sensor"]["python"]["path"], str(habitat_python))
            self.assertEqual(result["workers"]["detector"]["python"]["path"], str(host_python.absolute()))
            self.assertFalse(result["ui"]["enabled"])
            self.assertEqual(result["profile"], "rebuild-rgbd-m1-m5-v1")
            self.assertEqual(result["detector"]["device"], "cuda:0")
            self.assertEqual(result["navigation"]["mapper"]["raycast_backend"], "triton_cuda")
            self.assertEqual(result["workers"]["raycast"]["python"]["path"], str(host_python.absolute()))
            self.assertEqual(result["workers"]["raycast"]["script"]["path"],
                             str(project / "src/neusymnav/mapping/gpu_raycast_worker.py"))


if __name__ == "__main__":
    unittest.main()
