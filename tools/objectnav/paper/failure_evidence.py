#!/usr/bin/env python3
"""Offline failure evidence for a paper-protocol run (Habitat interpreter, EVALUATOR-ONLY).

Same evidence as tools/objectnav/b0/failure_evidence.py (target seen / detected, stop object,
confirmed goal), rendered with the paper camera (0.88 m, HFOV 79 deg, 640x480) instead of the
lockstep camera (1.2 m, 90 deg). It runs that tool's main() with its camera constants replaced
from the protocol config; the tool itself is unchanged. Level camera only (paper B0 never tilts).

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/paper/failure_evidence.py \
        runs/objectnav/<run> --set hm3d_v2 --split val
"""
import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('--protocol', type=Path, default=ROOT / 'configs/objectnav/paper-hm3d-v1.json')
    known, rest = ap.parse_known_args(argv)
    protocol = json.loads(known.protocol.read_text())
    cam = protocol['camera']
    height, width = cam['resolution_hw']
    camera_y, hfov = float(cam['position_xyz'][1]), float(cam['hfov_deg'])
    evidence = _load('b0_failure_evidence', ROOT / 'tools/objectnav/b0/failure_evidence.py')
    views = _load('sample_views', ROOT / 'tools/objectnav/detector_eval/sample_views.py')
    evidence.CAMERA_Y, evidence.WIDTH, evidence.HEIGHT, evidence.HFOV = camera_y, width, height, hfov
    views.CAMERA_Y, views.WIDTH, views.HEIGHT, views.HFOV = camera_y, width, height, hfov

    def open_semantic_sim(scene_path, dataset_config, robot, gpu_device_id=-1):
        return views.open_sim(scene_path, dataset_config, robot, semantic=True, gpu_device_id=gpu_device_id)
    evidence.open_semantic_sim = open_semantic_sim
    with tempfile.TemporaryDirectory() as tmp:
        runner = Path(tmp) / 'runner.json'      # the tool reads robot + renderer device from a runner config
        runner.write_text(json.dumps(dict(robot=dict(radius_m=protocol['agent']['radius_m'],
                                                     height_m=protocol['agent']['height_m']),
                                          sensor=dict(gpu_device_id=protocol.get('gpu_device_id', -1)))))
        return evidence.main(rest + ['--runner-config', str(runner)])


if __name__ == '__main__':
    raise SystemExit(main())
