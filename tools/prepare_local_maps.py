#!/usr/bin/env python3
"""Prepare machine-local map configs using real Habitat RGB-D; no runtime map seeding.

Run with the sensor interpreter named by configs/demo.local.json. Scene assets
are read-only. Navmesh is used only to pick an explicit setup spawn; its cells
never enter the runtime map. Each live episode uses the saved position/rotation.
"""
import argparse
import base64
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
MAPS = [f'0080{i}' for i in range(10)] + [f'apt_{i}' for i in range(6)]


def asset(path):
    path = path.resolve(strict=True)
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def prepare(name, source_root, template, output):
    import habitat_sim
    import numpy as np
    from PIL import Image
    spec = importlib.util.spec_from_file_location('local_habitat_worker', ROOT / 'src/neusymnav/sensors/habitat_worker.py')
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    if name.startswith('008'):
        parent = source_root / 'hm3d-0.2/hm3d/minival'
        scenes = list(parent.glob(name + '-*/*.basis.glb'))
        if len(scenes) != 1:
            raise ValueError('expected one scene mesh for ' + name)
        scene = scenes[0]
        dataset = parent / 'hm3d_minival_basis.scene_dataset_config.json'
        navmesh = scene.with_suffix('.navmesh')
    else:
        parent = source_root / 'replica_cad_dataset'
        scene = parent / 'configs/scenes' / (name + '.scene_instance.json')
        dataset = parent / 'replicaCAD.scene_dataset_config.json'
        navmesh = parent / 'navmeshes' / (name + '.navmesh')
        if json.loads(scene.read_text()).get('articulated_object_instances'):
            raise ValueError('ReplicaCAD articulated objects require physics; current live sensor disables physics, so the complete scene is unsupported')
    scene_asset, dataset_asset, nav_asset = asset(scene), asset(dataset), asset(navmesh)
    pathfinder = habitat_sim.PathFinder()
    if not pathfinder.load_nav_mesh(str(navmesh)):
        raise ValueError('navmesh failed to load')
    pathfinder.seed(0)
    sensor = copy.deepcopy(template['sensor_config'])
    sensor.pop('scene'); sensor.pop('scene_dataset'); sensor.pop('floor_datum', None)
    sensor.update(scene_id=str(scene), scene_dataset_config_file=str(dataset),
                  episode_id='setup-' + name, gpu_device_id=-1,
                  initial_rotation_xyzw=[0., 0., 0., 1.])
    native = None
    try:
        for attempt in range(30):
            position = np.asarray(pathfinder.get_random_navigable_point(), dtype=float)
            if not np.isfinite(position).all():
                continue
            sensor['initial_position'] = position.tolist()
            if native is None:
                native = worker.HabitatCapture(sensor)
            else:
                native._set_pose(position, sensor['initial_rotation_xyzw'])
            frames = []
            heights = []
            for _ in range(3):
                packet = native.capture('navigation')
                arrays = dict(np.load(io.BytesIO(base64.b64decode(packet['arrays_b64'])), allow_pickle=False))
                depth = arrays['depth_m']; h, w = depth.shape
                yy, xx = np.mgrid[h//2-10:h//2+10, w//2-10:w//2+10]
                z = depth[yy, xx]; k = arrays['K']
                rays = np.stack(((xx-k[0,2])*z/k[0,0], (yy-k[1,2])*z/k[1,1], z, np.ones_like(z)), axis=-1)
                world = rays @ arrays['T_world_camera'].T
                heights.extend(world[...,2][arrays['valid_depth'][yy,xx]].tolist())
                frames.append(packet['metadata'])
            values = np.asarray(heights)
            if len(values) < 1100:
                continue
            floor = float(np.median(values))
            if np.quantile(values, .95) - np.quantile(values, .05) > .03 or abs(floor-position[1]) > .3:
                continue
            if native._planar_math is None or not native._planar_math.valid(native.agent, native.agent.get_state(), float(position[1])):
                raise ValueError('unsupported native planar adapter')
            break
        else:
            raise ValueError('no measured flat-floor spawn found in 30 setup samples')
        lane = native.capture('primary')
        arrays = dict(np.load(io.BytesIO(base64.b64decode(lane['arrays_b64'])), allow_pickle=False))
        Image.fromarray(arrays['rgb']).save(output / (name + '.png'))
        calibration = dict(schema_version=1, map=name, method='measured-downward-depth-center-patch-v1',
            setup_spawn_method='offline_navmesh_sample_seed0_then_measured_floor_check',
            setup_sample_index=attempt, runtime_navmesh_seeds_map=False,
            scene=scene_asset, dataset=dataset_asset, setup_navmesh=nav_asset,
            source_world='new_y_up_v1', canonical_world='canonical_world_z_up_v1',
            sensor_config=sensor, captures=frames, floor_z_m=floor,
            sample_count=len(values), p05_m=float(np.quantile(values,.05)), p95_m=float(np.quantile(values,.95)),
            habitat_version=habitat_sim.__version__)
        calpath = output / (name + '-calibration.json')
        calpath.write_text(json.dumps(calibration, indent=2) + '\n')
        cal = asset(calpath)
        config = copy.deepcopy(template)
        config['episode']['id'] = 'local-intel-' + name
        config['floor'] = dict(z_m=floor, datum_source='measured-downward-depth-v1:' + str(calpath), calibration_sha256=cal['sha256'])
        sensor = config['sensor_config']
        sensor.update(scene=scene_asset, scene_dataset=dataset_asset,
            initial_position=position.tolist(), initial_rotation_xyzw=[0.,0.,0.,1.], gpu_device_id=-1,
            floor_datum=dict(source_convention='new_y_up_v1', source_floor_y_m=floor,
                canonical_floor_z_m=floor, provenance='measured-downward-depth-v1:' + cal['sha256']))
        target = ROOT / 'configs' / ('demo-' + name + '.local.json')
        target.write_text(json.dumps(config, indent=2) + '\n')
        return {'map': name, 'config': str(target), 'floor_z_m': floor, 'initial_position': position.tolist(), 'sample_count': len(values)}
    finally:
        if native is not None:
            native.sim.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('maps', nargs='*', metavar='MAP')
    parser.add_argument('--source-root', type=Path, default=ROOT.parent / 'Rebuild_3DScene_OccuSG/artifacts/habitat_data/versioned_data')
    args = parser.parse_args()
    if any(name not in MAPS for name in args.maps):
        parser.error('unknown map; choose ' + ', '.join(MAPS))
    output = ROOT / '.runtime/map-selection-20261030'
    output.mkdir(parents=True, exist_ok=True)
    template = json.loads((ROOT / 'configs/demo.local.json').read_text())
    results = []
    for name in args.maps or MAPS[:10]:
        try:
            result = prepare(name, args.source_root.resolve(), template, output)
            result['status'] = 'calibrated'
        except Exception as exc:
            result = {'map': name, 'status': 'failed', 'error': str(exc)}
        results.append(result)
        print(json.dumps(result), flush=True)
        (output / 'preparation.json').write_text(json.dumps(results, indent=2) + '\n')
    return int(any(r['status'] == 'failed' for r in results))


if __name__ == '__main__':
    sys.exit(main())
