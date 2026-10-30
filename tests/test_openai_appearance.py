"""OpenAI-compatible local TorchScript backend; all synthetic weights are fixtures."""
from __future__ import annotations

import hashlib
import io
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from neusymnav.perception import appearance_client as client
from neusymnav.perception import appearance_worker as worker

PREPROCESSING = "openai-clip-vit-b-32-eval-224-maskbboxpad20-v1"


def config(tmp_path, **changes):
    checkpoint = tmp_path / "fixture.pt"
    checkpoint.write_bytes(b"not a model; fake torch fixture")
    result = dict(checkpoint_path=str(checkpoint), checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
                  model_name="ViT-B-32", pretrained=None, state_dict_strict=True,
                  preprocessing_id=PREPROCESSING, crop_recipe_id=worker.CROP_RECIPE_ID,
                  feature_dimension=512, checkpoint_format="openai_jit")
    result.update(changes)
    return result


def encoder(tmp_path, **changes):
    cfg = config(tmp_path, **changes)
    return client.AppearanceWorkerEncoder(sys.executable, cfg["checkpoint_path"],
        checkpoint_sha256=cfg["checkpoint_sha256"], model_name=cfg["model_name"],
        preprocessing_id=cfg["preprocessing_id"], checkpoint_format=cfg["checkpoint_format"])


def install_fake_clip(monkeypatch, *, bad_arch=False, bad_transform=False, jit_error=False):
    calls = []
    shape = lambda *dims: SimpleNamespace(shape=dims)
    state = {"visual.conv1.weight": shape(768, 3, 16 if bad_arch else 32, 32),
             "visual.positional_embedding": shape(50, 768), "visual.proj": shape(768, 512)}
    state.update({f"visual.transformer.resblocks.{i}.attn.in_proj_weight": shape(2304, 768) for i in range(12)})
    class Tensor:
        def unsqueeze(self, axis):
            calls.append(("unsqueeze", axis))
            return self
    class Model:
        def load_state_dict(self, state, strict):
            calls.append(("strict", strict))
            return SimpleNamespace(missing_keys=[], unexpected_keys=[])
        def float(self):
            calls.append("float")
            return self
        def eval(self):
            calls.append("eval")
            return self
        def parameters(self):
            return ()
        def encode_image(self, tensor):
            calls.append("encode")
            return SimpleNamespace(detach=lambda: SimpleNamespace(cpu=lambda: SimpleNamespace(numpy=lambda: np.ones((1, 512), dtype=np.float32))))
    def jit_load(path, map_location):
        calls.append(("jit", path, map_location))
        if jit_error:
            raise RuntimeError("not a TorchScript archive")
        return SimpleNamespace(state_dict=lambda: dict(state))
    class Context:
        def __enter__(self): return self
        def __exit__(self, *args): return False
    fake_torch = SimpleNamespace(__version__="fixture", jit=SimpleNamespace(load=jit_load),
        set_num_threads=lambda n: calls.append(("threads", n)),
        set_num_interop_threads=lambda n: calls.append(("interop", n)), inference_mode=Context)
    def stage(name, **attrs):
        return type(name, (), attrs)()
    transforms = [stage("Resize", size=224, interpolation=SimpleNamespace(value="bicubic")),
        stage("CenterCrop", size=(224, 224)), lambda image: image.convert("RGB"),
        stage("ToTensor"), stage("Normalize", mean=(0.48145466, 0.4578275, 0.40821073),
             std=(0.26862954, 0.26130258, 0.27577711))]
    if bad_transform:
        transforms[-1].mean = (0.0, 0.0, 0.0)
    class Transform:
        def __init__(self): self.transforms = transforms
        def __call__(self, image):
            calls.append(("pixels", np.array(image)))
            return Tensor()
        def __str__(self): return "fixture actual transform"
    def build(state):
        calls.append("build")
        return Model()
    fake_clip = SimpleNamespace(_transform=lambda size: Transform())
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "clip", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "clip.clip", fake_clip)
    monkeypatch.setitem(sys.modules, "clip.model", SimpleNamespace(build_model=build))
    monkeypatch.setattr(worker, "_package_version", lambda name: "fixture")
    monkeypatch.setattr(worker, "_implementation_sha256", lambda obj: "c" * 64, raising=False)
    return calls


def test_client_accepts_only_explicit_new_format_and_matching_recipe(tmp_path):
    obj = encoder(tmp_path)
    assert obj.checkpoint_format == "openai_jit"
    with pytest.raises(ValueError, match="checkpoint_format"):
        encoder(tmp_path, checkpoint_format="pickle")
    with pytest.raises(ValueError, match="preprocessing"):
        encoder(tmp_path, preprocessing_id=client.SUPPORTED_PREPROCESSING_ID)
    with pytest.raises(ValueError, match="absolute"):
        encoder(tmp_path, checkpoint_path="fixture.pt")


def test_openai_backend_is_torchscript_only_strict_cpu_and_reports_real_recipe(tmp_path, monkeypatch):
    calls = install_fake_clip(monkeypatch)
    encode, metadata = worker._load_openai_clip(config(tmp_path))
    vector = encode(np.full((7, 8, 3), 123, dtype=np.uint8))
    assert vector.shape == (512,)
    assert ("strict", True) in calls and "float" in calls and "eval" in calls
    assert any(row[0] == "jit" and row[2] == "cpu" for row in calls if isinstance(row, tuple))
    assert any(row[0] == "threads" and row[1] <= 4 for row in calls if isinstance(row, tuple))
    assert metadata["backend"] == "openai_clip" and metadata["checkpoint_format"] == "openai_jit"
    assert metadata["runtime"]["openai_clip"] == "fixture"
    assert "open_clip_torch" not in metadata["runtime"]
    obj = encoder(tmp_path)
    normalized, space_id = obj._validate_metadata(metadata)
    assert normalized["model_fingerprint"].startswith("neusymnav-openai-clip-model-v1:")
    assert space_id.startswith("neusymnav-appearance-space-v1:")
    metadata["runtime"].pop("openai_clip")
    with pytest.raises(ValueError, match="runtime"):
        obj._validate_metadata(metadata)


@pytest.mark.parametrize("failure", ["sha", "architecture", "transform", "jit"])
def test_no_fallback_or_download_on_invalid_local_model(tmp_path, monkeypatch, failure):
    calls = install_fake_clip(monkeypatch, bad_arch=failure == "architecture",
                              bad_transform=failure == "transform", jit_error=failure == "jit")
    cfg = config(tmp_path)
    if failure == "sha": cfg["checkpoint_sha256"] = "0" * 64
    with pytest.raises((ValueError, RuntimeError)):
        worker._load_openai_clip(cfg)
    assert "encode" not in calls
    if failure in ("sha", "architecture", "jit"):
        assert "build" not in calls


def test_worker_dispatch_preserves_safetensors_and_rejects_unknown(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_load_openclip", lambda cfg: calls.append("old") or (None, {}))
    monkeypatch.setattr(worker, "_load_openai_clip", lambda cfg: calls.append("new") or (None, {}), raising=False)
    worker._load_encoder({})
    worker._load_encoder({"checkpoint_format": "openai_jit"})
    with pytest.raises(ValueError, match="checkpoint_format"):
        worker._load_encoder({"checkpoint_format": "pickle"})
    assert calls == ["old", "new"]


def test_new_backend_framed_initialize_protocol(tmp_path, monkeypatch):
    obj = encoder(tmp_path)
    calls = install_fake_clip(monkeypatch)
    _, metadata = worker._load_openai_clip(config(tmp_path))
    # Exercise the real framed initialization protocol in-process, no heavy model process.
    request = {"op": "initialize", "config": config(tmp_path)}
    payload = client.AppearanceWorkerEncoder._frame(request, worker.MAX_REQUEST_BYTES)
    incoming, outgoing = io.BytesIO(payload), io.BytesIO()
    monkeypatch.setattr(worker.sys, "stdin", SimpleNamespace(buffer=incoming))
    monkeypatch.setattr(worker.sys, "stdout", SimpleNamespace(buffer=outgoing))
    assert worker._worker_main() == 0
    outgoing.seek(0)
    response = worker._read_frame(outgoing)
    assert response["op"] == "ready"
    assert obj._validate_metadata(response["metadata"])[1] == obj._validate_metadata(metadata)[1]


def test_backend_spaces_differ_and_legacy_fingerprint_is_preserved(tmp_path, monkeypatch):
    install_fake_clip(monkeypatch)
    cfg = config(tmp_path)
    new = encoder(tmp_path)
    _, new_metadata = worker._load_openai_clip(cfg)
    checkpoint = tmp_path / "fixture.safetensors"
    checkpoint.write_bytes(b"fixture")
    old = client.AppearanceWorkerEncoder(sys.executable, checkpoint,
        checkpoint_sha256=cfg["checkpoint_sha256"], model_name="ViT-B-32",
        preprocessing_id=client.SUPPORTED_PREPROCESSING_ID)
    legacy_metadata = {key: new_metadata[key] for key in (
        "model_name", "checkpoint_sha256", "pretrained", "state_dict_strict", "crop_recipe_id",
        "feature_dimension", "transform_repr_sha256")}
    legacy_metadata.update(preprocessing_id=client.SUPPORTED_PREPROCESSING_ID,
        runtime={key: "fixture" for key in client._RUNTIME_KEYS})
    normalized, old_space = old._validate_metadata(legacy_metadata)
    expected = dict(legacy_metadata)
    expected["model_fingerprint"] = "neusymnav-openclip-model-v1:" + client._canonical_hash({
        key: legacy_metadata[key] for key in ("model_name", "checkpoint_sha256", "pretrained", "state_dict_strict")})
    assert normalized == expected
    assert old_space == "neusymnav-appearance-space-v1:" + client._canonical_hash(expected)
    assert old_space != new._validate_metadata(new_metadata)[1]
    with pytest.raises(ValueError):
        new._validate_metadata(legacy_metadata)
    with pytest.raises(ValueError):
        old._validate_metadata(new_metadata)


@pytest.mark.parametrize("backend", ["safetensors", "openai_jit"])
def test_client_initialize_payload_has_explicit_format_only_for_new_backend(tmp_path, monkeypatch, backend):
    install_fake_clip(monkeypatch)
    cfg = config(tmp_path)
    _, metadata = worker._load_openai_clip(cfg)
    if backend == "safetensors":
        checkpoint = tmp_path / "fixture.safetensors"
        checkpoint.write_bytes(b"fixture")
        obj = client.AppearanceWorkerEncoder(sys.executable, checkpoint,
            checkpoint_sha256=cfg["checkpoint_sha256"], model_name="ViT-B-32",
            preprocessing_id=client.SUPPORTED_PREPROCESSING_ID,
            _worker_command=[sys.executable, "-c", "import time; time.sleep(30)"])
        metadata = {key: metadata[key] for key in ("model_name", "checkpoint_sha256", "pretrained",
            "state_dict_strict", "crop_recipe_id", "feature_dimension", "transform_repr_sha256")}
        metadata.update(preprocessing_id=client.SUPPORTED_PREPROCESSING_ID,
            runtime={key: "fixture" for key in client._RUNTIME_KEYS})
    else:
        obj = encoder(tmp_path)
        obj._command = (sys.executable, "-c", "import time; time.sleep(30)")
    sent = []
    monkeypatch.setattr(obj, "_send", lambda payload, deadline: sent.append(payload))
    monkeypatch.setattr(obj, "_read_response", lambda deadline: {"op": "ready", "metadata": metadata})
    try:
        obj._start(client.FrameKey("fixture-episode", "rgbd", 1))
        assert len(sent) == 1
        if backend == "openai_jit":
            assert sent[0]["config"]["checkpoint_format"] == "openai_jit"
        else:
            assert "checkpoint_format" not in sent[0]["config"]
    finally:
        obj.close()
