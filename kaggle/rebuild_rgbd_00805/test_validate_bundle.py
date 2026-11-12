import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from kaggle.rebuild_rgbd_00805.validate_bundle import validate_bundle


class ValidateBundleTests(unittest.TestCase):
    def _make_bundle(self, root: Path, notebook: Path) -> Path:
        bundle = root / "bundle"
        (bundle / "probe").mkdir(parents=True)
        (bundle / "probe/detector_diagnostic.py").write_text("diagnostic-v1")
        (bundle / "probe/network_preflight.py").write_text("network-preflight-v1")
        (bundle / "requirements-host-kaggle-gpu.txt").write_text("gpu-lock-v1")
        notebook.write_text("notebook-v1")
        manifest = {
            "bundle": "neusymnav-rebuild-rgbd-m1-m5-v1",
            "map": "00805",
            "kaggle_gpu_enabled": True,
            "workflow_notebook_sha256": "",
            "detector_diagnostic_sha256": "",
            "network_preflight_sha256": "",
            "kaggle_gpu_host_requirements_sha256": "",
        }
        import hashlib

        manifest["workflow_notebook_sha256"] = hashlib.sha256(notebook.read_bytes()).hexdigest()
        manifest["detector_diagnostic_sha256"] = hashlib.sha256(
            (bundle / "probe/detector_diagnostic.py").read_bytes()
        ).hexdigest()
        manifest["network_preflight_sha256"] = hashlib.sha256(
            (bundle / "probe/network_preflight.py").read_bytes()
        ).hexdigest()
        manifest["kaggle_gpu_host_requirements_sha256"] = hashlib.sha256(
            (bundle / "requirements-host-kaggle-gpu.txt").read_bytes()
        ).hexdigest()
        (bundle / "manifest.json").write_text(json.dumps(manifest))
        return bundle

    def test_accepts_directory_and_zip_when_pins_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notebook = root / "workflow.ipynb"
            bundle = self._make_bundle(root, notebook)
            self.assertEqual(validate_bundle(bundle, notebook), [])

            archive = root / "bundle.zip"
            with zipfile.ZipFile(archive, "w") as output:
                for path in bundle.rglob("*"):
                    if path.is_file():
                        output.write(path, path.relative_to(bundle).as_posix())
            self.assertEqual(validate_bundle(archive, notebook), [])

    def test_rejects_notebook_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notebook = root / "workflow.ipynb"
            bundle = self._make_bundle(root, notebook)
            notebook.write_text("different-workflow")
            issues = validate_bundle(bundle, notebook)
            self.assertTrue(any("workflow notebook SHA-256 mismatch" in issue for issue in issues))

    def test_rejects_network_preflight_helper_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notebook = root / "workflow.ipynb"
            bundle = self._make_bundle(root, notebook)
            (bundle / "probe/network_preflight.py").write_text("changed-network-preflight")

            issues = validate_bundle(bundle, notebook)

            self.assertTrue(any("network preflight SHA-256 mismatch" in issue for issue in issues))

    def test_rejects_unsafe_archive_member(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notebook = root / "workflow.ipynb"
            bundle = self._make_bundle(root, notebook)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as output:
                for path in bundle.rglob("*"):
                    if path.is_file():
                        output.write(path, path.relative_to(bundle).as_posix())
                output.writestr("../escape", "unsafe")
            issues = validate_bundle(archive, notebook)
            self.assertTrue(any("unsafe archive member" in issue for issue in issues))

    def test_rejects_non_object_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notebook = root / "workflow.ipynb"
            bundle = self._make_bundle(root, notebook)
            (bundle / "manifest.json").write_text("[]")
            issues = validate_bundle(bundle, notebook)
            self.assertTrue(any("manifest must be a JSON object" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
