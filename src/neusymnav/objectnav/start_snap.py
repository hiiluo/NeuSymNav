#!/usr/bin/env python3
"""Snap episode start poses onto the ROBOT's navmesh (Habitat interpreter, setup only).

ObjectNav episodes were generated for the challenge agent (radius 0.18 m,
height 0.88 m). Our robot body differs, and the sensor worker recomputes the
navmesh for it; its planar motion adapter then rejects every step whose height
differs from the launch height by more than 5 cm. A start taken verbatim from
the episode can therefore sit 10-15 cm off the robot's navmesh and the robot
never moves (seen on 00807 and on 00800 episode 7).

This helper recomputes the navmesh exactly like ``HabitatCapture`` does for an
``agent_geometry`` and snaps each start to it. It is simulator setup, like
placing the agent; nothing here reaches the robot's map or policy.

Usage: python start_snap.py <request.json> <result.json>   (files, because
Habitat writes native logs to stdout)

request: {"robot": {"radius_m":..,"height_m":..}, "episodes": [{"uid", "scene_path",
         "dataset_config", "start_position"}]}
result:  {"schema_version": 1, "starts": {uid: {"snapped": [x,y,z], "shift_xz_m",
         "shift_y_m", "navigable"}}}
"""
import json
import math
import sys
from itertools import groupby


def snap_starts(request):
    import habitat_sim
    import numpy as np
    robot = request['robot']
    out = {}
    key = lambda e: (e['scene_path'], e.get('dataset_config') or '')
    for (scene, dataset), group in groupby(sorted(request['episodes'], key=key), key=key):
        cfg = habitat_sim.SimulatorConfiguration()
        cfg.scene_id = scene
        if dataset:
            cfg.scene_dataset_config_file = dataset
        cfg.enable_physics = False
        agent = habitat_sim.agent.AgentConfiguration()
        agent.radius, agent.height = float(robot['radius_m']), float(robot['height_m'])
        agent.sensor_specifications = []
        sim = habitat_sim.Simulator(habitat_sim.Configuration(cfg, [agent]))
        try:
            settings = sim.pathfinder.nav_mesh_settings
            if settings is None:
                settings = habitat_sim.NavMeshSettings()
                settings.set_defaults()
            settings.agent_radius, settings.agent_height = agent.radius, agent.height
            if not sim.recompute_navmesh(sim.pathfinder, settings):
                raise RuntimeError('navmesh recomputation failed for ' + scene)
            for e in group:
                start = np.asarray(e['start_position'], dtype=np.float32)
                snapped = np.asarray(sim.pathfinder.snap_point(start), dtype=np.float64)
                ok = bool(np.isfinite(snapped).all())
                out[e['uid']] = dict(
                    snapped=[float(v) for v in snapped] if ok else None,
                    shift_xz_m=float(math.hypot(snapped[0] - start[0], snapped[2] - start[2])) if ok else None,
                    shift_y_m=float(snapped[1] - start[1]) if ok else None,
                    navigable=ok and bool(sim.pathfinder.is_navigable(snapped.astype(np.float32))))
        finally:
            sim.close()
    return dict(schema_version=1, robot=dict(radius_m=robot['radius_m'], height_m=robot['height_m']), starts=out)


if __name__ == '__main__':
    with open(sys.argv[1]) as stream:
        request = json.load(stream)
    result = snap_starts(request)
    with open(sys.argv[2], 'w') as stream:
        json.dump(result, stream)
