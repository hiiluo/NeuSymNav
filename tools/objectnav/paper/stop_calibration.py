#!/usr/bin/env python3
"""Stop-distance calibration for the paper camera (Habitat interpreter, EVALUATOR-ONLY, DEV only).

Runs tools/objectnav/b0/stop_calibration.py unchanged, with its camera (1.2 m, 90 deg) replaced by
the paper protocol camera (0.88 m, 79 deg, 640x480) and the robot by the challenge agent
(0.18 x 0.88 m). Use its table to set stop_distance_m / far_stop_distance_m in
configs/objectnav/paper-b0-v1.json (docs/objectnav/paper-protocol-plan.md P5).

    PYTHONPATH=src ~/miniconda3/envs/habitat/bin/python tools/objectnav/paper/stop_calibration.py \
        --manifest configs/objectnav/splits/hm3d_v2-val-dev.json --out runs/objectnav/paper-stop-calibration.json
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
    calib = _load('b0_stop_calibration', ROOT / 'tools/objectnav/b0/stop_calibration.py')
    views = _load('sample_views', ROOT / 'tools/objectnav/detector_eval/sample_views.py')
    calib.CAMERA_Y, calib.WIDTH, calib.HEIGHT, calib.HFOV = camera_y, width, height, hfov
    views.CAMERA_Y, views.WIDTH, views.HEIGHT, views.HFOV = camera_y, width, height, hfov
    calib.open_sim = lambda scene, dataset, robot, gpu: views.open_sim(scene, dataset, robot, semantic=True,
                                                                       gpu_device_id=gpu)
    with tempfile.TemporaryDirectory() as tmp:
        runner = Path(tmp) / 'runner.json'
        runner.write_text(json.dumps(dict(robot=dict(radius_m=protocol['agent']['radius_m'],
                                                     height_m=protocol['agent']['height_m']),
                                          sensor=dict(gpu_device_id=protocol.get('gpu_device_id', -1)))))
        return calib.main(rest + ['--runner-config', str(runner)])


if __name__ == '__main__':
    raise SystemExit(main())
