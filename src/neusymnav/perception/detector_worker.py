"""Explicit Python >=3.12 worker for the package's actual local P04 YOLOE.

No sibling source paths, auto-downloads, model fallback, pickle, or scene GT.
The only added import root is this self-contained NeuSymNav/src directory.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import time


def _read(stream, count):
    result = bytearray()
    while len(result) < count:
        data = stream.read(count - len(result))
        if not data:
            if not result:
                return None
            raise EOFError('truncated IPC frame')
        result.extend(data)
    return bytes(result)


def main():
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), 'wb', buffering=0)
    os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    def send(value):
        data = json.dumps(value, separators=(',', ':'), allow_nan=False).encode()
        if len(data) > 32 * 1024**2:
            raise ValueError('detector response exceeds bound')
        protocol.write(len(data).to_bytes(4, 'big') + data)
    try:
        if sys.version_info < (3, 12):
            raise RuntimeError('detector worker requires Python >=3.12 package profile')
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from neusymnav.contracts import Observation, Taxonomy, from_dict, to_dict, require_rgbd
        from neusymnav.perception.detector_client import validate_recipe, _json
        from neusymnav.perception.yoloe import YOLOEDetector
        detector, recipe, watermarks, episode = None, None, {}, None
        while True:
            header = _read(sys.stdin.buffer, 4)
            if header is None:
                return 0
            size = int.from_bytes(header, 'big')
            if not 0 < size <= 32 * 1024**2:
                raise ValueError('detector request exceeds bound')
            data = _read(sys.stdin.buffer, size)
            if data is None:
                raise EOFError('missing IPC payload')
            request = _json(data)
            if not isinstance(request, dict) or type(request.get('wire_version')) is not int or request['wire_version'] != 1:
                raise ValueError('invalid detector protocol version')
            if request.get('op') == 'initialize' and detector is None:
                if set(request) != {'op', 'wire_version', 'recipe'}:
                    raise ValueError('invalid initialize fields')
                recipe = validate_recipe(request['recipe'])
                taxonomy = Taxonomy.load(recipe['taxonomy_path'])
                with contextlib.redirect_stdout(sys.stderr):
                    detector = YOLOEDetector(recipe['checkpoint_path'], recipe['encoder_path'], taxonomy,
                        checkpoint_license=recipe['checkpoint_license'], imgsz=recipe['imgsz'],
                        max_detections=recipe['max_detections'], confidence_threshold=recipe['confidence_threshold'],
                        device=recipe['device'])
                    detector._load()
                runtime = dict(python=platform.python_version(), numpy=importlib.metadata.version('numpy'),
                               torch=importlib.metadata.version('torch'),
                               ultralytics=importlib.metadata.version('ultralytics'))
                import clip
                clip_files = [Path(clip.__file__)]
                api = getattr(clip, 'clip', None)
                if getattr(api, '__file__', None):
                    clip_files.append(Path(api.__file__))
                clip_digest = hashlib.sha256(b''.join(p.read_bytes() for p in clip_files)).hexdigest()
                runtime['clip'] = str(getattr(clip, '__version__', 'unversioned-local')) + ':sha256:' + clip_digest
                digest = hashlib.sha256(json.dumps(recipe, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                send(dict(ok=True, wire_version=1, recipe_sha256=digest, runtime=runtime))
            elif request.get('op') == 'infer' and detector is not None:
                if set(request) != {'op', 'wire_version', 'observation'}:
                    raise ValueError('invalid infer fields')
                obs = from_dict(request['observation'])
                require_rgbd(obs)
                if obs.clock_domain.startswith('host_monotonic:'):
                    from neusymnav.sensors.habitat_worker import host_clock_domain
                    if obs.clock_domain != host_clock_domain() or obs.capture_monotonic_ns > time.monotonic_ns():
                        raise ValueError('detector live source clock domain/future capture mismatch')
                sensor = (obs.key.episode_id, obs.key.sensor_id)
                previous = watermarks.get(sensor)
                if ((episode is not None and episode != obs.key.episode_id)
                        or (previous is not None and (obs.key.frame_index <= previous[0]
                                                      or obs.capture_monotonic_ns <= previous[1]))):
                    raise ValueError('detector source replay/episode mismatch')
                episode = obs.key.episode_id
                watermarks[sensor] = (obs.key.frame_index, obs.capture_monotonic_ns)
                with contextlib.redirect_stdout(sys.stderr):
                    batch = detector.infer(obs)
                send(dict(ok=True, wire_version=1, batch=to_dict(batch)))
            else:
                raise ValueError('invalid detector operation/state')
    except Exception as exc:
        send(dict(ok=False, wire_version=1, error=type(exc).__name__ + ': ' + str(exc)))
        return 1
    finally:
        protocol.close()


if __name__ == '__main__':
    raise SystemExit(main())
