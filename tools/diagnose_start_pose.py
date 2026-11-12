#!/usr/bin/env python3
"""Check whether the configured start pose can translate in Habitat at all.

Run with the Habitat interpreter:

    ~/miniconda3/envs/habitat/bin/python tools/diagnose_start_pose.py \
        --config configs/demo-00806.hydra-realtime-slm.experimental.local.json

For 16 headings it asks the simulator collision filter (``step_filter``, the
same call the planar actuation adapter uses) for a 5 cm forward step from the
configured start and reports the planar displacement and the height change.
The planar adapter rejects a step whose filtered height differs from the start
height by more than 5 cm, so a large ``dy`` explains zero motion. Read-only:
it never edits the config.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np

PLANAR_HEIGHT_TOLERANCE_M = 0.05


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', required=True)
    parser.add_argument('--step-m', type=float, default=0.05)
    args = parser.parse_args(argv)
    config = json.loads(Path(args.config).read_text())
    sensor = config['sensor_config']
    robot = config.get('navigation', {}).get('robot', {})
    radius, height = float(robot.get('radius_m', 0.2)), float(robot.get('height_m', 1.5))

    import habitat_sim
    simulator = habitat_sim.SimulatorConfiguration()
    simulator.scene_id = sensor['scene']['path']
    simulator.enable_physics = False
    simulator.gpu_device_id = int(sensor.get('gpu_device_id', 0))
    if sensor.get('scene_dataset', {}).get('path'):
        simulator.scene_dataset_config_file = sensor['scene_dataset']['path']
    agent = habitat_sim.agent.AgentConfiguration()
    agent.radius, agent.height = radius, height
    agent.sensor_specifications = []
    sim = habitat_sim.Simulator(habitat_sim.Configuration(simulator, [agent]))
    try:
        settings = sim.pathfinder.nav_mesh_settings or habitat_sim.NavMeshSettings()
        if sim.pathfinder.nav_mesh_settings is None:
            settings.set_defaults()
        settings.agent_radius, settings.agent_height = radius, height
        if not sim.recompute_navmesh(sim.pathfinder, settings):
            raise SystemExit('navmesh recomputation failed')
        start = np.asarray(sensor['initial_position'], dtype=np.float32)
        snapped = np.asarray(sim.pathfinder.snap_point(start), dtype=np.float64)
        report = dict(config=str(args.config), initial_position=[float(v) for v in start],
                      snapped_position=[float(v) for v in snapped],
                      snap_offset_xz_m=float(math.dist(start[[0, 2]], snapped[[0, 2]])),
                      snap_dy_m=float(snapped[1] - start[1]),
                      start_is_navigable=bool(sim.pathfinder.is_navigable(start)),
                      headings=[])
        island_radius = getattr(sim.pathfinder, 'island_radius', None)
        if callable(island_radius):
            report['island_radius_m'] = float(island_radius(start))
        moving = 0
        for k in range(16):
            angle = 2 * math.pi * k / 16
            end = start + np.asarray([math.cos(angle), 0., math.sin(angle)], np.float32) * args.step_m
            filtered = np.asarray(sim.step_filter(start, end), dtype=np.float64)
            moved = float(math.dist(filtered[[0, 2]], start[[0, 2]]))
            dy = float(filtered[1] - start[1])
            accepted = moved > 1e-6 and abs(dy) <= PLANAR_HEIGHT_TOLERANCE_M
            moving += accepted
            report['headings'].append(dict(deg=round(math.degrees(angle), 1), moved_m=round(moved, 4),
                                           dy_m=round(dy, 4), planar_accepts=accepted))
        report['headings_that_can_move'] = moving
        if moving == 0:
            report['verdict'] = ('start cannot translate: '
                + ('filtered height differs >5 cm from start height; set sensor_config.initial_position '
                   'to snapped_position' if any(abs(h['dy_m']) > PLANAR_HEIGHT_TOLERANCE_M and h['moved_m'] > 0
                                                for h in report['headings'])
                   else 'collision filter blocks every heading; choose another start'))
        else:
            report['verdict'] = 'start can translate'
    finally:
        sim.close()
    print(json.dumps(report, indent=1))
    return 0 if report['headings_that_can_move'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
