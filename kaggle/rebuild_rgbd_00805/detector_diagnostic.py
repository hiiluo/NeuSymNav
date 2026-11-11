#!/usr/bin/env python3
"""Run one source-bound detector probe and report stage/device evidence.

The probe uses an observation and exact detector recipe from a completed
NeuSymNav run. It is diagnostic-only: it never publishes objects, room maps,
or hierarchy, and its longer timeout does not change the production profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

TRACE_PREFIX = "NEUSYMNAV_DETECTOR_TRACE="


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_probe_inputs(run_dir: Path) -> tuple[Path, Path]:
    run_dir = Path(run_dir).expanduser().resolve(strict=True)
    frames = sorted((run_dir / "keyframes").glob("frame-*.json"))
    attempts = sorted((run_dir / "attempts").glob("*-startup.json"))
    if not frames:
        raise FileNotFoundError(f"run has no durable detector input under {run_dir / 'keyframes'}")
    if not attempts:
        raise FileNotFoundError(f"run has no startup recipe under {run_dir / 'attempts'}")
    return frames[0], attempts[-1]


def detector_recipe(startup_path: Path) -> dict:
    startup = json.loads(Path(startup_path).read_text(encoding="utf-8"))
    detector = startup.get("effective_config", {}).get("detector")
    if not isinstance(detector, dict):
        raise ValueError("startup attempt is missing effective_config.detector")
    required = ("checkpoint", "encoder", "taxonomy")
    recipe = {}
    for name in required:
        asset = detector.get(name)
        if not isinstance(asset, dict) or set(asset) != {"path", "sha256"}:
            raise ValueError(f"startup detector {name} pin is invalid")
        recipe[f"{name}_path"] = asset["path"]
        recipe[f"{name}_sha256"] = asset["sha256"]
    for key in ("checkpoint_license", "confidence_threshold", "imgsz", "max_detections", "device"):
        if key not in detector:
            raise ValueError(f"startup detector recipe is missing {key}")
        recipe[key] = detector[key]
    return recipe


def parse_trace_events(stderr_text: str) -> list[dict]:
    events = []
    for line in str(stderr_text).splitlines():
        marker = line.find(TRACE_PREFIX)
        if marker < 0:
            continue
        try:
            event = json.loads(line[marker + len(TRACE_PREFIX):])
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and isinstance(event.get("stage"), str):
            events.append(event)
    return events


def stage_device_report(*, configured_device: str | None, probe: dict,
                        raycast: dict | None) -> dict:
    events = probe.get("worker_events", []) if isinstance(probe, dict) else []
    model_events = [event for event in events if event.get("stage") == "model_predict"]
    detector_device = None
    if probe.get("status") == "completed" and model_events:
        detector_device = model_events[-1].get("observed_device")
    raycast = raycast if isinstance(raycast, dict) else {}
    execution = raycast.get("execution") if isinstance(raycast.get("execution"), dict) else {}
    return {
        "detector": {
            "configured_device": configured_device,
            "probe_status": probe.get("status"),
            "observed_device": detector_device,
        },
        "raycast": {
            "backend": raycast.get("backend"),
            "status": raycast.get("status"),
            "observed_device": execution.get("device_name"),
            "requests_completed": raycast.get("requests_completed"),
        },
        "habitat_renderer": "Mesa llvmpipe (CPU)",
        "rebuild_m1_m5": "native CPU",
    }


def worker_shim_source() -> str:
    return r'''import json, os, runpy, sys, time
from neusymnav.perception.yoloe import YOLOEDetector

PREFIX = "NEUSYMNAV_DETECTOR_TRACE="
def emit(stage, started, **fields):
    event = {"stage": stage, "elapsed_ms": round((time.perf_counter()-started)*1000, 3), **fields}
    print(PREFIX + json.dumps(event, sort_keys=True, separators=(",", ":")), file=sys.stderr, flush=True)

def sync_cuda(requested):
    try:
        import torch
        if str(requested).startswith("cuda") and torch.cuda.is_available():
            torch.cuda.synchronize(requested)
            return torch.cuda.get_device_name(torch.device(requested))
    except Exception:
        pass
    return None

original_load = YOLOEDetector._load
def traced_load(self):
    started = time.perf_counter()
    result = original_load(self)
    observed = sync_cuda(self.device)
    model = self._model
    if not getattr(model, "_neusymnav_predict_traced", False):
        original_predict = model.predict
        def traced_predict(*args, **kwargs):
            sync_cuda(self.device)
            started_predict = time.perf_counter()
            emit("model_predict_start", started_predict, requested_device=self.device)
            succeeded = False
            try:
                result_predict = original_predict(*args, **kwargs)
                succeeded = True
                return result_predict
            finally:
                observed_device = sync_cuda(self.device)
                emit("model_predict", started_predict, requested_device=self.device,
                     observed_device=observed_device, cuda_synchronized=bool(observed_device),
                     succeeded=succeeded)
        model.predict = traced_predict
        model._neusymnav_predict_traced = True
    emit("model_load", started, requested_device=self.device, observed_device=observed)
    return result
YOLOEDetector._load = traced_load

original_infer = YOLOEDetector.infer
def traced_infer(self, observation):
    started = time.perf_counter()
    result = original_infer(self, observation)
    emit("yoloe_infer_total", started, requested_device=self.device,
         detection_count=len(result.detections))
    return result
YOLOEDetector.infer = traced_infer

target = os.environ["NEUSYMNAV_DIAGNOSTIC_WORKER_SCRIPT"]
runpy.run_path(target, run_name="__main__")
'''


def _timed_method(obj, name: str, target: dict, key: str) -> None:
    original = getattr(obj, name)
    def measured(*args, **kwargs):
        started = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            target.setdefault(key, []).append(round(time.perf_counter() - started, 6))
    setattr(obj, name, measured)


def run_probe(*, run_dir: Path, worker_script: Path, output: Path,
              timeout_s: float = 120.0, startup_timeout_s: float = 180.0) -> dict:
    run_dir = Path(run_dir).expanduser().resolve(strict=True)
    worker_script = Path(worker_script).expanduser().resolve(strict=True)
    output = Path(output).expanduser().resolve()
    timings: dict = {}
    report = {
        "schema_version": 1,
        "status": "failed",
        "diagnostic_only": True,
        "production_deadline_changed": False,
        "diagnostic_timeout_s": timeout_s,
        "production_timeout_s": None,
        "worker_events": [],
        "timings_s": timings,
        "error": None,
    }
    client = None
    prior_worker_script = os.environ.get("NEUSYMNAV_DIAGNOSTIC_WORKER_SCRIPT")
    try:
        frame_path, startup_path = resolve_probe_inputs(run_dir)
        recipe = detector_recipe(startup_path)
        startup = json.loads(startup_path.read_text(encoding="utf-8"))
        detector_settings = startup.get("effective_config", {}).get("workers", {}).get("detector", {})
        report["production_timeout_s"] = detector_settings.get("timeout_s")
        report["source"] = {
            "frame_path": str(frame_path),
            "frame_sha256": _sha256(frame_path),
            "frame_bytes": frame_path.stat().st_size,
            "startup_path": str(startup_path),
            "recipe_device": recipe["device"],
        }
        from dataclasses import replace
        from neusymnav.contracts import from_dict
        from neusymnav.perception import detector_client as detector_client_module
        from neusymnav.perception.detector_client import DetectorClient
        from neusymnav.sensors.habitat_worker import host_clock_domain

        observation = from_dict(json.loads(frame_path.read_text(encoding="utf-8")))
        observation = replace(observation, clock_domain=host_clock_domain(),
                              capture_monotonic_ns=max(0, time.monotonic_ns() - 1_000_000))
        report["source"]["frame_key"] = {
            "episode_id": observation.key.episode_id,
            "sensor_id": observation.key.sensor_id,
            "frame_index": observation.key.frame_index,
        }
        report["source"]["clock_rebased_for_inference_only"] = True

        output.parent.mkdir(parents=True, exist_ok=True)
        shim_path = output.with_name(output.stem + "-worker-shim.py")
        shim_path.write_text(worker_shim_source(), encoding="utf-8")
        os.environ["NEUSYMNAV_DIAGNOSTIC_WORKER_SCRIPT"] = str(worker_script)

        client = DetectorClient(python=sys.executable, worker_script=shim_path, recipe=recipe,
                                timeout_s=timeout_s, startup_timeout_s=startup_timeout_s)
        _timed_method(client._wire, "send", timings, "send_encode_and_pipe_write_s")
        _timed_method(client._wire, "receive", timings, "receive_wait_read_and_json_decode_s")
        _timed_method(detector_client_module, "to_dict", timings, "client_serialize_contract_s")
        _timed_method(detector_client_module, "from_dict", timings, "client_parse_contract_s")
        _timed_method(detector_client_module, "validate_detection_batch", timings,
                      "client_validate_contract_s")
        started = time.perf_counter()
        try:
            batch = client.infer(observation)
            report["detection_count"] = len(batch.detections)
            report["status"] = "completed"
        finally:
            timings["infer_whole_operation_s"] = round(time.perf_counter() - started, 6)
        report["worker_runtime"] = client.runtime_metadata
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        if client is not None:
            report["worker_runtime"] = client.runtime_metadata
            report["worker_events"] = parse_trace_events("".join(client.diagnostics))
    finally:
        if client is not None:
            report["shutdown"] = client.close(timeout_s=5.0)
            report["worker_events"] = parse_trace_events("".join(client.diagnostics))
        if prior_worker_script is None:
            os.environ.pop("NEUSYMNAV_DIAGNOSTIC_WORKER_SCRIPT", None)
        else:
            os.environ["NEUSYMNAV_DIAGNOSTIC_WORKER_SCRIPT"] = prior_worker_script
        try:
            Path(output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                    encoding="utf-8")
        except OSError as exc:
            report["error"] = (report.get("error") or "") + f"; report_write: {exc}"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--worker-script", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=120.0,
                        help="diagnostic-only request deadline; production timeout is unchanged")
    parser.add_argument("--startup-timeout-s", type=float, default=180.0)
    args = parser.parse_args()
    result = run_probe(run_dir=args.run_dir, worker_script=args.worker_script,
                       output=args.output, timeout_s=args.timeout_s,
                       startup_timeout_s=args.startup_timeout_s)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("status") == "completed" and result.get("shutdown", {}).get("clean_shutdown") else 1


if __name__ == "__main__":
    raise SystemExit(main())
