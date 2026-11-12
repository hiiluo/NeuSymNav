#!/usr/bin/env python3
"""Build a privileged navmesh coverage tour for any configured Habitat scene.

Run with the Habitat interpreter named in the demo config's sensor worker:

    ~/miniconda3/envs/habitat/bin/python tools/make_navmesh_tour.py \
        --config configs/demo-00807.hydra-room-slm-debug.experimental.local.json \
        --out runs/tours/00807-tour.json

The scene, dataset, start pose and robot radius/height are read from the
config, so the same command works for every scene. The output is simulator
map knowledge for 3DSG evaluation only (``privileged: true``); it is never an
ObjectNav result. Add the printed ``navigation.tour`` block to a demo profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.navigation.tour import plan_coverage_tour, tour_document  # noqa: E402


class HabitatPathfinder:
    def __init__(self, sim, habitat_sim):
        self.pf = sim.pathfinder
        self.habitat_sim = habitat_sim

    def bounds(self):
        low, high = self.pf.get_bounds()
        return tuple(float(v) for v in low), tuple(float(v) for v in high)

    def snap(self, xyz):
        import numpy as np
        point = self.pf.snap_point(np.asarray(xyz, dtype=np.float32))
        values = [float(v) for v in point]
        if not all(math.isfinite(v) for v in values) or not self.pf.is_navigable(point):
            return None
        return tuple(values)

    def island(self, xyz):
        # Older habitat-sim has no island query; reachability is still checked
        # by find_path for every tour leg.
        import numpy as np
        getter = getattr(self.pf, 'get_island', None)
        return 0 if getter is None else int(getter(np.asarray(xyz, dtype=np.float32)))

    def path(self, a, b):
        import numpy as np
        request = self.habitat_sim.ShortestPath()
        request.requested_start = np.asarray(a, dtype=np.float32)
        request.requested_end = np.asarray(b, dtype=np.float32)
        if not self.pf.find_path(request) or not math.isfinite(request.geodesic_distance):
            return math.inf, []
        return float(request.geodesic_distance), [tuple(float(v) for v in p) for p in request.points]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--spacing-m', type=float, default=1.0)
    parser.add_argument('--coverage-radius-m', type=float, default=1.5)
    parser.add_argument('--navmesh-radius-m', type=float,
                        help='navmesh agent radius for the tour route (default: robot radius + margin + '
                             '0.05 m, so the route keeps the observed-map footprint clear of walls)')
    parser.add_argument('--profile-out', help='also write a copy of --config with navigation.tour set')
    parser.add_argument('--realtime', action='store_true',
                        help='in --profile-out also enable the real-time profile: world goal age 1500 ms, '
                             'intent TTL 4000 ms, nice hydra=2 detector=5 ui=8')
    args = parser.parse_args(argv)

    config = json.loads(Path(args.config).read_text())
    sensor = config['sensor_config']
    robot = config.get('navigation', {}).get('robot', {})
    radius = float(robot.get('radius_m', 0.2))
    height = float(robot.get('height_m', 1.5))
    # Shortest navmesh paths hug walls at exactly the navmesh agent radius.
    # The runtime planner needs radius + margin of KNOWN free cells, so a route
    # computed at the bare robot radius is untraversable at every corner.
    if args.navmesh_radius_m is None:
        radius = radius + float(robot.get('margin_m', 0.05)) + 0.05
    elif 0.05 <= args.navmesh_radius_m <= 1.0:
        radius = float(args.navmesh_radius_m)
    else:
        raise SystemExit('--navmesh-radius-m must be in [0.05, 1.0]')
    scene_path = sensor['scene']['path']
    if _sha256(scene_path) != sensor['scene']['sha256']:
        raise SystemExit('scene sha256 does not match the config')

    import habitat_sim
    simulator = habitat_sim.SimulatorConfiguration()
    simulator.scene_id = scene_path
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
        result = plan_coverage_tour(HabitatPathfinder(sim, habitat_sim), sensor['initial_position'],
                                    spacing_m=args.spacing_m, coverage_radius_m=args.coverage_radius_m)
    finally:
        sim.close()
    document = tour_document(result, scene_path=scene_path, scene_sha256=sensor['scene']['sha256'],
                             spacing_m=args.spacing_m, coverage_radius_m=args.coverage_radius_m,
                             agent_radius_m=radius, agent_height_m=height)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(document, indent=1) + '\n').encode()
    out.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f'navmesh_radius={radius:.2f} m goals={len(document["goals_xy"])} polyline_points={len(document["polyline_xy"])} '
          f'length={document["length_m"]:.1f} m candidates={document["candidates"]} '
          f'unreachable={document["unreachable_candidates"]}')
    tour_block = {'path': str(out.resolve()), 'sha256': digest}
    print(json.dumps({'navigation': {'tour': tour_block}}, indent=1))
    if args.profile_out:
        profile = json.loads(Path(args.config).read_text())
        controller = profile.setdefault('navigation', {}).setdefault('controller', {})
        if not controller.get('local_depth_control'):
            raise SystemExit('the tour requires navigation.controller.local_depth_control=true')
        profile['navigation']['tour'] = tour_block
        if args.realtime:
            controller.setdefault('world_goal_max_age_ms', 1500)
            controller.setdefault('world_intent_ttl_ms', 4000)
            profile.setdefault('runtime', {}).setdefault(
                'process_priority', {'hydra': 2, 'detector': 5, 'ui': 8})
        Path(args.profile_out).write_text(json.dumps(profile, indent=2) + '\n')
        print(f'wrote profile {args.profile_out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
