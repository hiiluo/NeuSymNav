"""Standalone OpenCLIP image-feature worker for schema-v1 RGB-D detections.

The host invokes this file with the explicitly configured worker interpreter.
Only the child process imports Pillow, OpenCLIP, Torch, and safetensors. The
crop and normalization behavior is adapted from Fusion's U2 extraction helper:
ConceptGraphs-style padded RGB crops, no mask painting, strict local weights,
and unit-normalized 512-D image features. See runs/p05-adapter-report.md for
source hashes and attribution.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import struct
import sys
from typing import Any, Callable, Mapping

import numpy as np


SUPPORTED_MODEL_NAME = "ViT-B-32"
SUPPORTED_PREPROCESSING_ID = "openclip-vit-b-32-openai-eval-224-maskbboxpad20-v1"
CROP_RECIPE_ID = "mask-tight-xyxy+20px-clipped+PIL-float-edge-rounding-v1"
FEATURE_DIMENSION = 512
MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PROTOCOL_VERSION = 1


def crop_bbox_rgb(rgb: np.ndarray, bbox_xyxy: Any, *, padding_px: int = 20):
    """Return the reference RGB crop and its float box after clipped padding.

    Pillow owns float edge rounding, matching the pinned U2 helper. The source
    RGB pixels remain unchanged; masks identify/crop detections but do not
    black out context or foreground pixels.
    """
    from PIL import Image

    if not isinstance(rgb, np.ndarray) or rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("rgb must be an HxWx3 uint8 source image")
    if rgb.shape[0] == 0 or rgb.shape[1] == 0:
        raise ValueError("RGB dimensions must be nonempty")
    if type(padding_px) is not int or padding_px < 0:
        raise ValueError("padding_px must be a nonnegative integer")
    try:
        values = tuple(float(value) for value in bbox_xyxy)
    except (TypeError, ValueError) as error:
        raise ValueError("bbox_xyxy must contain four finite coordinates") from error
    if len(values) != 4 or not all(math.isfinite(value) for value in values):
        raise ValueError("bbox_xyxy must contain four finite coordinates")
    x_min, y_min, x_max, y_max = values
    height, width = rgb.shape[:2]
    if not (0 <= x_min < x_max <= width and 0 <= y_min < y_max <= height):
        raise ValueError("bbox_xyxy lies outside the original source image")
    left = min(float(padding_px), x_min)
    top = min(float(padding_px), y_min)
    right = min(float(padding_px), width - x_max)
    bottom = min(float(padding_px), height - y_max)
    crop_box = (x_min - left, y_min - top, x_max + right, y_max + bottom)
    crop = np.asarray(Image.fromarray(rgb, mode="RGB").crop(crop_box), dtype=np.uint8)
    if crop.ndim != 3 or crop.shape[2] != 3 or not crop.size:
        raise ValueError("Pillow returned an empty or invalid RGB crop")
    return crop, crop_box


def mask_bbox_xyxy(mask: np.ndarray) -> tuple[float, float, float, float]:
    """Derive a tight pixel-edge box from a full-resolution detection mask."""
    if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.ndim != 2:
        raise ValueError("mask must be a two-dimensional bool array")
    rows, cols = np.nonzero(mask)
    if not len(rows):
        raise ValueError("mask must contain at least one source pixel")
    # Pixel-edge coordinates include the final occupied column and row.
    return float(cols.min()), float(rows.min()), float(cols.max() + 1), float(rows.max() + 1)


def crop_mask_rgb(rgb: np.ndarray, mask: np.ndarray, *, padding_px: int = 20):
    """Apply the mask-bounds adapter then the reference padded RGB crop."""
    if not isinstance(mask, np.ndarray) or mask.dtype != np.bool_ or mask.shape != rgb.shape[:2]:
        raise ValueError("mask must be bool and match the original RGB image shape")
    return crop_bbox_rgb(rgb, mask_bbox_xyxy(mask), padding_px=padding_px)


def normalize_feature(vector: Any, *, dimension: int = FEATURE_DIMENSION) -> np.ndarray:
    """Validate and L2-normalize one finite floating-point image embedding."""
    values = np.asarray(vector)
    if values.dtype.kind != "f" or values.ndim != 1 or values.shape != (dimension,):
        raise ValueError(f"feature must be a floating-point vector of shape ({dimension},)")
    values = values.astype(np.float32, copy=False)
    if not np.isfinite(values).all():
        raise ValueError("feature contains non-finite values")
    norm = float(np.linalg.norm(values))
    if not math.isfinite(norm) or norm <= 0:
        raise ValueError("feature has zero or non-finite norm")
    normalized = (values / np.float32(norm)).astype(np.float32, copy=False)
    if not np.isclose(float(np.linalg.norm(normalized)), 1.0, atol=1e-5, rtol=1e-5):
        raise ValueError("normalized feature norm is outside tolerance")
    return np.ascontiguousarray(normalized)


def encode_rgb_features(
    rgb: np.ndarray,
    detections: tuple[Mapping[str, Any], ...],
    *,
    image_encoder: Callable[[np.ndarray], Any],
    padding_px: int = 20,
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, str]]]:
    """Encode detections independently and report failures without fake vectors.

    ``detections`` carry the original detection ID and full-resolution mask.
    A per-detection preprocessing or inference error is represented by a
    ``missing`` status and omitted from the feature mapping.
    """
    if not callable(image_encoder):
        raise TypeError("image_encoder must be callable")
    feature_by_id: dict[str, np.ndarray] = {}
    status_by_id: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for detection in detections:
        detection_id = detection.get("detection_id")
        if not isinstance(detection_id, str) or not detection_id.strip() or detection_id in seen:
            raise ValueError("detections must have unique nonempty detection IDs")
        seen.add(detection_id)
        try:
            crop, _crop_box = crop_mask_rgb(rgb, detection["mask"], padding_px=padding_px)
            feature_by_id[detection_id] = normalize_feature(image_encoder(crop))
            status_by_id[detection_id] = {"status": "available"}
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"[:240]
            status_by_id[detection_id] = {"status": "missing", "reason": reason}
    return feature_by_id, status_by_id


def _sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def _normalized_transform_repr(preprocess: Any) -> str:
    # Torchvision's transform repr embeds process-specific object addresses.
    return re.sub(r" at 0x[0-9a-fA-F]+", " at <address>", str(preprocess))


def _package_version(distribution: str) -> str:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError as error:
        raise RuntimeError(f"required worker package is unavailable: {distribution}") from error


def _load_openclip(config: Mapping[str, Any]):
    """Strictly load the declared local safetensors checkpoint on CPU."""
    checkpoint = Path(str(config["checkpoint_path"]))
    if not checkpoint.is_absolute() or checkpoint.suffix.lower() != ".safetensors" or not checkpoint.is_file():
        raise ValueError("checkpoint_path must be an existing absolute .safetensors file")
    expected_sha = str(config["checkpoint_sha256"])
    actual_sha = _sha256_file(checkpoint)
    if actual_sha != expected_sha:
        raise ValueError("local checkpoint SHA-256 differs from the configured value")
    if config["model_name"] != SUPPORTED_MODEL_NAME:
        raise ValueError(f"unsupported OpenCLIP model; expected {SUPPORTED_MODEL_NAME}")
    if config.get("pretrained") is not None or config.get("state_dict_strict") is not True:
        raise ValueError("worker requires pretrained=None and strict local state-dict loading")
    if config["preprocessing_id"] != SUPPORTED_PREPROCESSING_ID:
        raise ValueError("preprocessing_id does not name the supported pinned crop/eval recipe")
    if config["crop_recipe_id"] != CROP_RECIPE_ID:
        raise ValueError("crop_recipe_id does not name the supported mask-bounds adapter")
    if config.get("feature_dimension") != FEATURE_DIMENSION:
        raise ValueError("feature_dimension differs from the supported OpenCLIP ViT-B-32 output")

    # Import only in the standalone process. pretrained=None avoids model-zoo
    # lookup; only the existing local safetensors file supplies weights.
    import open_clip
    import torch
    from safetensors.torch import load_file

    torch.set_num_threads(min(4, os.cpu_count() or 1))
    torch.set_num_interop_threads(1)
    model, _train_preprocess, preprocess = open_clip.create_model_and_transforms(
        SUPPORTED_MODEL_NAME, pretrained=None, device="cpu"
    )
    state_dict = load_file(str(checkpoint), device="cpu")
    incompat = model.load_state_dict(state_dict, strict=True)
    if incompat.missing_keys or incompat.unexpected_keys:
        raise RuntimeError("local checkpoint is incompatible with the configured OpenCLIP model")
    del state_dict
    model.eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)

    runtime = {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "open_clip_torch": _package_version("open_clip_torch"),
        "torch": str(torch.__version__),
        "torchvision": _package_version("torchvision"),
        "Pillow": _package_version("Pillow"),
        "numpy": str(np.__version__),
    }
    transform_sha = hashlib.sha256(_normalized_transform_repr(preprocess).encode("utf-8")).hexdigest()
    metadata = {
        "model_name": SUPPORTED_MODEL_NAME,
        "checkpoint_sha256": actual_sha,
        "pretrained": None,
        "state_dict_strict": True,
        "preprocessing_id": str(config["preprocessing_id"]),
        "crop_recipe_id": CROP_RECIPE_ID,
        "transform_repr_sha256": transform_sha,
        "runtime": runtime,
        "feature_dimension": FEATURE_DIMENSION,
    }

    def image_encoder(crop_rgb: np.ndarray) -> np.ndarray:
        from PIL import Image

        tensor = preprocess(Image.fromarray(crop_rgb, mode="RGB")).unsqueeze(0)
        with torch.inference_mode():
            output = model.encode_image(tensor)
        return output.detach().cpu().numpy().astype(np.float32, copy=False).reshape(-1)

    return image_encoder, metadata


def _read_exact(stream, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("worker input closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_frame(stream) -> dict[str, Any]:
    size = struct.unpack("!I", _read_exact(stream, 4))[0]
    if size > MAX_REQUEST_BYTES:
        raise ValueError("IPC request exceeds the worker byte limit")
    payload = json.loads(_read_exact(stream, size).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("IPC request must be a JSON object")
    return payload


def _write_frame(stream, payload: Mapping[str, Any]) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_RESPONSE_BYTES:
        payload = {"op": "error", "reason": "IPC response exceeds the worker byte limit"}
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    stream.write(struct.pack("!I", len(encoded)))
    stream.write(encoded)
    stream.flush()


def _decode_encode_request(request: Mapping[str, Any]):
    rgb_shape = request.get("rgb_shape")
    if (not isinstance(rgb_shape, list) or len(rgb_shape) != 3 or rgb_shape[2] != 3
            or any(type(value) is not int or value <= 0 for value in rgb_shape)):
        raise ValueError("RGB shape is invalid")
    height, width, _channels = rgb_shape
    rgb_bytes = base64.b64decode(request["rgb_b64"], validate=True)
    if len(rgb_bytes) != height * width * 3:
        raise ValueError("RGB payload length does not match its shape")
    rgb = np.frombuffer(rgb_bytes, dtype=np.uint8).reshape((height, width, 3))
    rows = []
    for item in request.get("detections", ()):
        detection_id = item.get("detection_id")
        shape = item.get("mask_shape")
        if (not isinstance(detection_id, str) or not detection_id.strip()
                or not isinstance(shape, list) or shape != [height, width]):
            raise ValueError("detection ID or source mask shape is invalid")
        packed = base64.b64decode(item["mask_bits_b64"], validate=True)
        expected_bytes = (height * width + 7) // 8
        if len(packed) != expected_bytes:
            raise ValueError("packed mask length does not match its source shape")
        mask = np.unpackbits(np.frombuffer(packed, dtype=np.uint8), count=height * width,
                             bitorder="little").reshape((height, width)).astype(np.bool_, copy=False)
        rows.append({"detection_id": detection_id, "mask": mask})
    ids = [row["detection_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate detection ID in worker request")
    return rgb, tuple(rows)


def _encode_worker_request(request: Mapping[str, Any], image_encoder: Callable[[np.ndarray], Any]):
    rgb, detections = _decode_encode_request(request)
    features, status = encode_rgb_features(rgb, detections, image_encoder=image_encoder,
                                           padding_px=20)
    encoded = {
        detection_id: base64.b64encode(np.asarray(vector, dtype="<f4").tobytes()).decode("ascii")
        for detection_id, vector in features.items()
    }
    return {"op": "features", "source": request["source"],
            "geometry_hash": request["geometry_hash"], "features": encoded,
            "status": status}


def _worker_main() -> int:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    image_encoder = None
    try:
        while True:
            try:
                request = _read_frame(stdin)
            except EOFError:
                return 0
            operation = request.get("op")
            if operation == "close":
                return 0
            if operation == "initialize":
                if image_encoder is not None:
                    _write_frame(stdout, {"op": "error", "reason": "worker already initialized"})
                    continue
                try:
                    config = request["config"]
                    image_encoder, metadata = _load_openclip(config)
                    _write_frame(stdout, {"op": "ready", "metadata": metadata})
                except Exception as error:
                    _write_frame(stdout, {"op": "error", "reason": f"{type(error).__name__}: {error}"[:500]})
                    return 2
                continue
            if operation != "encode" or image_encoder is None:
                _write_frame(stdout, {"op": "error", "reason": "worker is not initialized"})
                continue
            try:
                _write_frame(stdout, _encode_worker_request(request, image_encoder))
            except Exception as error:
                _write_frame(stdout, {"op": "error", "reason": f"{type(error).__name__}: {error}"[:500]})
    except Exception as error:
        try:
            _write_frame(stdout, {"op": "error", "reason": f"protocol failure: {type(error).__name__}: {error}"[:500]})
        except Exception:
            pass
        return 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help="serve the private framed-JSON worker protocol")
    args = parser.parse_args(argv)
    if not args.worker:
        parser.error("--worker is required; this process is normally launched by AppearanceWorkerEncoder")
    return _worker_main()


if __name__ == "__main__":
    raise SystemExit(main())
