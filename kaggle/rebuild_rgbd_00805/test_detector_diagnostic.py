import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("detector_diagnostic.py")
SPEC = importlib.util.spec_from_file_location("detector_diagnostic", MODULE_PATH)
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


class DetectorDiagnosticTests(unittest.TestCase):
    def test_resolves_exact_frame_and_startup_attempt_and_keeps_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            (run / "keyframes").mkdir()
            (run / "attempts").mkdir()
            (run / "keyframes/frame-000000000000.json").write_text("{}")
            config = {
                "detector": {
                    "checkpoint": {"path": "/models/yolo.pt", "sha256": "a" * 64},
                    "encoder": {"path": "/models/clip.ts", "sha256": "b" * 64},
                    "taxonomy": {"path": "/models/taxonomy.json", "sha256": "c" * 64},
                    "checkpoint_license": "AGPL-3.0",
                    "confidence_threshold": 0.25,
                    "imgsz": 640,
                    "max_detections": 30,
                    "device": "cuda:0",
                }
            }
            (run / "attempts/000-startup.json").write_text(json.dumps({"effective_config": config}))
            frame, startup = diagnostic.resolve_probe_inputs(run)
            recipe = diagnostic.detector_recipe(startup)
            self.assertEqual(frame.name, "frame-000000000000.json")
            self.assertEqual(recipe["device"], "cuda:0")
            self.assertEqual(recipe["checkpoint_path"], "/models/yolo.pt")

    def test_trace_parser_only_accepts_structured_worker_events(self):
        text = "noise\nNEUSYMNAV_DETECTOR_TRACE={\"stage\":\"model_predict\",\"elapsed_ms\":12.5}\n"
        self.assertEqual(diagnostic.parse_trace_events(text), [
            {"stage": "model_predict", "elapsed_ms": 12.5}
        ])

    def test_stage_device_report_does_not_claim_cuda_from_configuration_alone(self):
        report = diagnostic.stage_device_report(
            configured_device="cuda:0",
            probe={"status": "failed", "runtime": {"torch": "2.7.1+cu126"}},
            raycast={"status": "ready", "execution": {"device_name": "Tesla T4"}},
        )
        self.assertEqual(report["detector"]["configured_device"], "cuda:0")
        self.assertIsNone(report["detector"]["observed_device"])
        self.assertEqual(report["raycast"]["observed_device"], "Tesla T4")

    def test_notebook_records_stage_devices_and_isolates_each_run_output(self):
        notebook = json.loads(MODULE_PATH.with_name("m1_m5_smoke_00805.ipynb").read_text())
        source = "\n".join("".join(cell.get("source", [])) for cell in notebook["cells"])
        self.assertIn("stage_devices", source)
        self.assertIn("run_id", source)
        self.assertIn("run_root.rglob", source)
        self.assertNotIn("'cuda_enabled':False", source)

    def test_export_cell_uses_current_run_directory(self):
        notebook = json.loads(MODULE_PATH.with_name("m1_m5_smoke_00805.ipynb").read_text())
        export_source = "".join(notebook["cells"][5].get("source", []))
        self.assertNotIn("run_dir = Path('/kaggle/working/", export_source)
        self.assertIn("run_root/'export.stdout.log'", export_source)
        self.assertIn("run_root / 'review'", export_source)

    def test_notebook_resolves_only_the_diagnostic_pinned_bundle(self):
        notebook = json.loads(MODULE_PATH.with_name("m1_m5_smoke_00805.ipynb").read_text())
        setup_source = "".join(notebook["cells"][1].get("source", []))
        self.assertIn("EXPECTED_DETECTOR_DIAGNOSTIC_SHA256", setup_source)
        self.assertIn("EXPECTED_NETWORK_PREFLIGHT_SHA256", setup_source)
        self.assertIn("EXPECTED_GPU_REQUIREMENTS_SHA256", setup_source)
        self.assertIn("matching_manifest_candidate(candidate_manifest)", setup_source)
        self.assertIn("sha256_path(bundle/relative_path)", setup_source)
        self.assertIn("input_root.glob('**/*.zip')", setup_source)
        self.assertNotIn("rebuild-rgbd-00805-full-gpu-depthfix.zip", setup_source)

    def test_network_gate_runs_before_any_environment_bootstrap(self):
        notebook = json.loads(MODULE_PATH.with_name("m1_m5_smoke_00805.ipynb").read_text())
        setup_source = "".join(notebook["cells"][2].get("source", []))
        self.assertIn("probe/network_preflight.py", setup_source)
        self.assertLess(setup_source.index("network_preflight = subprocess.run"),
                        setup_source.index("manager = shutil.which"))
        self.assertIn("network_preflight.returncode", setup_source)


if __name__ == "__main__":
    unittest.main()
