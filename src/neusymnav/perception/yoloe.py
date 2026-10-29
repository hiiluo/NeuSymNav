"""Lazy YOLOE11s adapter; local model and MobileCLIP only, never downloads.

Prompt provider algorithm ported from NewOH3DSG/perception/local_text.py;
source hashes live in runs/p04/source-hashes.json. Native inference is optional.
"""
from __future__ import annotations
import hashlib
import numpy as np
from ..contracts.observations import (Detection, DetectionBatch, Taxonomy,
                                     require_rgbd, validate_detection_batch)

"""Offline MobileCLIP text embeddings for YOLOE prompt vocabularies.

The upstream Ultralytics text-model factory may install ``clip`` or download
weights as a side effect. This provider deliberately owns loading instead: it
requires an existing TorchScript encoder, loads it on CPU, and only imports the
tokenizer/runtime after confirming that ``clip`` is already available.
"""


import importlib
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Iterable


EncoderFactory = Callable[[Path], Any]
Tokenizer = Callable[..., Any]


class LocalMobileCLIPPromptProvider:
    """Create YOLOE-compatible text embeddings using a local MobileCLIP encoder.

    Pass this instance as ``prompt_embedding_provider`` to
    :class:`YOLOEDetector`. The encoder and tokenizer are loaded
    lazily once and retained for this provider's lifetime. Encoder inference
    stays on CPU; only the final text features are moved to the YOLOE model's
    device and dtype before the model's ``get_tpe`` head is applied.

    ``encoder_path`` must point to an existing official ``mobileclip_blt.ts``
    (YOLOE-11) or ``mobileclip2_b.ts`` (YOLOE-26) file.
    Tests and specialized integrations may inject all three runtime components;
    partial injection is rejected so production loading cannot be ambiguous.
    """

    def __init__(
        self,
        encoder_path: str | Path,
        *,
        encoder_factory: EncoderFactory | None = None,
        tokenizer: Tokenizer | None = None,
        tensor_runtime: Any | None = None,
        batch_size: int = 80,
    ) -> None:
        path = Path(encoder_path).expanduser()
        if path.name not in {"mobileclip_blt.ts", "mobileclip2_b.ts"}:
            raise ValueError("encoder_path must name an explicit local MobileCLIP TorchScript file")
        if not path.is_file():
            raise FileNotFoundError(f"local MobileCLIP encoder does not exist: {path}")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size <= 0:
            raise ValueError("batch_size must be a positive integer")

        injected = (encoder_factory, tokenizer, tensor_runtime)
        if any(value is not None for value in injected) and not all(value is not None for value in injected):
            raise ValueError("encoder_factory, tokenizer, and tensor_runtime must be injected together")
        if all(value is not None for value in injected) and (
            not callable(encoder_factory) or not callable(tokenizer)
        ):
            raise TypeError("injected encoder_factory and tokenizer must be callable")

        self._encoder_path = path.resolve(strict=True)
        self._encoder_factory = encoder_factory
        self._tokenizer = tokenizer
        self._tensor_runtime = tensor_runtime
        self._batch_size = batch_size
        self._encoder: Any | None = None
        self._lock = RLock()

    @property
    def encoder_path(self) -> Path:
        return self._encoder_path

    @property
    def batch_size(self) -> int:
        return self._batch_size

    def _load(self) -> None:
        if self._encoder is not None:
            return

        if self._encoder_factory is None:
            # Do this before importing Ultralytics helpers: their text_model
            # module attempts a package install when clip is absent.
            try:
                clip_spec = importlib.util.find_spec("clip")
            except (ImportError, ValueError):
                clip_spec = None
            if clip_spec is None:
                raise RuntimeError(
                    "the clip tokenizer is unavailable; install its dependency explicitly "
                    "before using local MobileCLIP prompts"
                )

            torch = importlib.import_module("torch")
            clip_module = importlib.import_module("clip")
            clip_api = getattr(clip_module, "clip", None)
            tokenizer = getattr(clip_api, "tokenize", None)
            if not callable(tokenizer):
                raise RuntimeError("the installed clip package does not expose clip.clip.tokenize")

            def load_torchscript(path: Path) -> Any:
                encoder = torch.jit.load(str(path), map_location="cpu")
                if callable(getattr(encoder, "eval", None)):
                    encoder.eval()
                return encoder

            encoder_factory: EncoderFactory = load_torchscript
            tensor_runtime = torch
        else:
            encoder_factory = self._encoder_factory
            tokenizer = self._tokenizer
            tensor_runtime = self._tensor_runtime

        encoder = encoder_factory(self._encoder_path)
        if not callable(encoder):
            raise TypeError("local MobileCLIP encoder must be callable")
        if not callable(getattr(tensor_runtime, "inference_mode", None)):
            raise TypeError("tensor_runtime must provide inference_mode()")
        if not callable(getattr(tensor_runtime, "cat", None)):
            raise TypeError("tensor_runtime must provide cat()")
        if not callable(getattr(tensor_runtime, "isfinite", None)):
            raise TypeError("tensor_runtime must provide isfinite()")

        self._encoder = encoder
        self._encoder_factory = encoder_factory
        self._tokenizer = tokenizer
        self._tensor_runtime = tensor_runtime

    @staticmethod
    def _is_finite(tensor_runtime: Any, value: Any) -> bool:
        finite = tensor_runtime.isfinite(value).all()
        if callable(getattr(finite, "item", None)):
            finite = finite.item()
        try:
            return bool(finite)
        except (TypeError, ValueError, RuntimeError):
            return False

    @staticmethod
    def _model_parts(model: Any) -> tuple[Any, Any]:
        core = getattr(model, "model", model)
        parameters = getattr(core, "parameters", None)
        if not callable(parameters):
            raise TypeError("YOLOE model must expose model.parameters()")
        try:
            parameter = next(iter(parameters()))
        except (StopIteration, TypeError) as error:
            raise ValueError("YOLOE model has no parameters to determine device and dtype") from error

        layers = getattr(core, "model", None)
        try:
            head = layers[-1]
        except (TypeError, IndexError, KeyError) as error:
            raise TypeError("YOLOE model must expose its detection head as model.model[-1]") from error
        if not callable(getattr(head, "get_tpe", None)):
            raise TypeError("YOLOE detection head must provide get_tpe(text_features)")
        if not hasattr(parameter, "device") or not hasattr(parameter, "dtype"):
            raise TypeError("YOLOE model parameter must expose device and dtype")
        return parameter, head

    def __call__(self, model: Any, prompts: Iterable[str]) -> Any:
        if isinstance(prompts, str):
            raise TypeError("prompts must be an iterable of strings, not a string")
        prompt_list = tuple(prompts)
        if not prompt_list:
            raise ValueError("at least one prompt is required")
        if any(not isinstance(prompt, str) or not prompt.strip() for prompt in prompt_list):
            raise ValueError("prompts must contain non-empty strings")

        with self._lock:
            self._load()
            parameter, head = self._model_parts(model)
            tokenizer = self._tokenizer
            tensor_runtime = self._tensor_runtime
            encoder = self._encoder

            feature_batches = []
            with tensor_runtime.inference_mode():
                for offset in range(0, len(prompt_list), self._batch_size):
                    prompt_batch = prompt_list[offset : offset + self._batch_size]
                    tokens = tokenizer(list(prompt_batch), truncate=True)
                    token_shape = getattr(tokens, "shape", ())
                    if len(token_shape) < 1 or token_shape[0] != len(prompt_batch):
                        raise ValueError("MobileCLIP tokenizer output does not align with prompts")
                    features = encoder(tokens)
                    if callable(getattr(features, "detach", None)):
                        features = features.detach()
                    shape = getattr(features, "shape", ())
                    if len(shape) != 2 or shape[0] != len(prompt_batch) or shape[1] <= 0:
                        raise ValueError("MobileCLIP encoder must return [prompt_count, feature_dim]")
                    if not self._is_finite(tensor_runtime, features):
                        raise ValueError("MobileCLIP encoder returned non-finite text features")
                    feature_batches.append(features)

            features = (
                feature_batches[0]
                if len(feature_batches) == 1
                else tensor_runtime.cat(feature_batches, dim=0)
            )
            feature_shape = features.shape
            if feature_shape[0] != len(prompt_list):
                raise ValueError("MobileCLIP encoder output count does not align with prompts")
            features = features.reshape(1, len(prompt_list), feature_shape[-1])
            move = getattr(features, "to", None)
            if not callable(move):
                raise TypeError("MobileCLIP text features must provide to(device, dtype)")
            features = move(device=parameter.device, dtype=parameter.dtype)

            # The encoder features were produced under inference_mode. Keep
            # YOLOE's learned projection there too: autograd cannot save an
            # inference tensor for backward through its Linear layers.
            with tensor_runtime.inference_mode():
                embeddings = head.get_tpe(features)
            shape = getattr(embeddings, "shape", ())
            if len(shape) != 3 or shape[0] != 1 or shape[1] != len(prompt_list) or shape[2] <= 0:
                raise ValueError("YOLOE get_tpe must return embeddings shaped [1, prompt_count, dim]")
            if not self._is_finite(tensor_runtime, embeddings):
                raise ValueError("YOLOE get_tpe returned non-finite text embeddings")
            return embeddings


def _numpy(value, name):
    if value is None: raise ValueError(f'YOLOE result missing {name}')
    if hasattr(value,'detach'): value=value.detach()
    if hasattr(value,'cpu'): value=value.cpu()
    if hasattr(value,'numpy'): value=value.numpy()
    result=np.asarray(value)
    if result.dtype.kind not in 'buif' or not np.isfinite(result).all():
        raise ValueError(f'YOLOE {name} must contain finite numeric values')
    return result


class YOLOEDetector:
    """Text-prompted YOLOE with explicit taxonomy and exact original-size masks.

    Loading occurs at first infer inside the detector worker. There is no
    implicit fallback to fixture inference, package installation or download.
    Injected factories/providers exist for CPU contract tests and deployments
    that already own the same local model assets.
    """
    def __init__(self, checkpoint_path, encoder_path, taxonomy: Taxonomy, *,
                 checkpoint_license, model_factory=None, prompt_embedding_provider=None,
                 imgsz=480, max_detections=30, confidence_threshold=.25, device='cpu'):
        self.checkpoint_path=Path(checkpoint_path).expanduser().resolve(strict=True)
        self.encoder_path=Path(encoder_path).expanduser().resolve(strict=True)
        if not self.checkpoint_path.is_file() or not self.encoder_path.is_file():
            raise FileNotFoundError('YOLOE and MobileCLIP must be existing local files')
        if not isinstance(taxonomy,Taxonomy): raise ValueError('explicit Taxonomy required')
        if not isinstance(checkpoint_license,str) or not checkpoint_license.strip():
            raise ValueError('checkpoint license provenance is required')
        if imgsz not in (480,512,544,640) or type(max_detections) is not int or not 1<=max_detections<=30:
            raise ValueError('unsupported YOLOE runtime profile')
        if not np.isfinite(confidence_threshold) or not 0<=confidence_threshold<=1:
            raise ValueError('confidence threshold must be in [0,1]')
        if not isinstance(device,str) or not device.strip(): raise ValueError('device is required')
        self.taxonomy=taxonomy
        self.checkpoint_license=checkpoint_license
        self.checkpoint_sha256=hashlib.sha256(self.checkpoint_path.read_bytes()).hexdigest()
        self.encoder_sha256=hashlib.sha256(self.encoder_path.read_bytes()).hexdigest()
        self.imgsz,self.max_detections=imgsz,max_detections
        self.confidence_threshold,self.device=confidence_threshold,device
        self._factory=model_factory
        self._provider=prompt_embedding_provider or LocalMobileCLIPPromptProvider(self.encoder_path)
        self._model=None
        self._lock=RLock()

    def _load(self):
        if self._model is not None: return
        # Recheck assets at actual load, so replacement after recipe creation
        # cannot silently change the pinned detector profile.
        if (hashlib.sha256(self.checkpoint_path.read_bytes()).hexdigest()!=self.checkpoint_sha256
            or hashlib.sha256(self.encoder_path.read_bytes()).hexdigest()!=self.encoder_sha256):
            raise ValueError('detector local asset checksum changed')
        if self._factory is None:
            # Ultralytics' text-model module may auto-install clip. Confirm it
            # exists before importing Ultralytics to keep the adapter offline.
            if importlib.util.find_spec('clip') is None:
                raise RuntimeError('local clip tokenizer unavailable; native detector blocked')
            from ultralytics import YOLOE
            factory=YOLOE
        else:
            factory=self._factory
        model=factory(str(self.checkpoint_path))
        prompts=self.taxonomy.categories
        embeddings=self._provider(model,prompts)
        if embeddings is None: raise ValueError('offline prompt provider returned no embeddings')
        model.set_classes(list(prompts),embeddings)
        self._model=model

    def infer(self, observation):
        require_rgbd(observation)
        with self._lock:
            self._load()
            bgr=np.ascontiguousarray(observation.rgb[...,::-1])
            results=list(self._model.predict(source=bgr,imgsz=self.imgsz,
                max_det=self.max_detections,conf=self.confidence_threshold,
                retina_masks=True,verbose=False,device=self.device))
            if len(results)!=1: raise ValueError('YOLOE requires one result for the exact source frame')
            result=results[0]
            if (tuple(getattr(result,'orig_shape',()))!=observation.rgb.shape[:2]
                or not np.array_equal(getattr(result,'orig_img',None),bgr)):
                raise ValueError('YOLOE result source image mismatch')
            boxes=getattr(result,'boxes',None)
            if boxes is None:
                raise ValueError('YOLOE result missing boxes/completion evidence')
            classes=_numpy(getattr(boxes,'cls',None),'classes')
            scores=_numpy(getattr(boxes,'conf',None),'scores')
            if classes.ndim!=1 or classes.shape!=scores.shape or np.any(classes!=np.floor(classes)):
                raise ValueError('YOLOE classes and scores must be aligned vectors')
            if np.any(classes<0) or np.any(classes>=len(self.taxonomy.categories)) or np.any((scores<0)|(scores>1)):
                raise ValueError('YOLOE class/score outside vocabulary/range')
            container=getattr(result,'masks',None)
            if len(classes):
                masks=_numpy(getattr(container,'data',None),'masks')
                if masks.shape!=(len(classes),*observation.depth_m.shape) or np.any((masks<0)|(masks>1)):
                    raise ValueError('YOLOE retina masks must match the original source image')
            elif container is not None and _numpy(getattr(container,'data',None),'masks').size:
                raise ValueError('YOLOE masks without boxes')
            detections=[]
            for index,class_id in enumerate(classes):
                label=self.taxonomy.categories[int(class_id)]
                detections.append(Detection(str(index),label,self.taxonomy.canonicalize(label),
                    float(scores[index]),masks[index]>=.5))
            batch=DetectionBatch.from_observation(observation,tuple(detections),
                vocabulary_id=self.taxonomy.vocabulary_id,completion='complete',
                cap_reached=len(detections)>=self.max_detections)
            validate_detection_batch(observation,batch)
            return batch
