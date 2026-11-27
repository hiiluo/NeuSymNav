#!/usr/bin/env python3
"""Build model-blind review panels for a frozen link-scoring report."""
import argparse
import hashlib
from itertools import product
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from neusymnav.contracts.observations import FrameKey
from neusymnav.recording.replay import ReplayReader


CORNERS = tuple(product((0, 1), repeat=3))
EDGES = tuple((i, j) for i, a in enumerate(CORNERS) for j, b in enumerate(CORNERS)
              if i < j and sum(x != y for x, y in zip(a, b)) == 1)


def draw_endpoints(image, observation, endpoints):
    draw = ImageDraw.Draw(image)
    world_to_camera = np.linalg.inv(observation.T_world_camera)
    for node in endpoints:
        bounds = np.asarray(node['bounds'])
        world = np.array([[bounds[index, axis] for axis, index in enumerate(corner)]
                          for corner in CORNERS])
        camera = world @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
        if (camera[:, 2] <= .05).any():
            continue
        uv = camera @ observation.K.T
        xy = np.clip(uv[:, :2] / uv[:, 2, None], -4096, 4096)
        for a, b in EDGES:
            draw.line((tuple(xy[a]), tuple(xy[b])), fill='#57e7ff', width=2)
        center = xy.mean(axis=0).clip((0, 0), (image.width-1, image.height-1))
        draw.text(tuple(center), node['native_id'] + ' ' + node['category'],
                  fill='white', stroke_width=2, stroke_fill='black')


def prepare(report_path, recording, output):
    raw = report_path.read_bytes()
    report = json.loads(raw)
    output.mkdir(parents=True, exist_ok=False)
    frames = ReplayReader(recording).source_frames()
    labels = []
    for row in report['records']:
        source = FrameKey(**row['token']['source'])
        observation = next((frame for frame in frames if frame.key == source), None)
        if observation is None:
            raise ValueError(f'frozen recording does not contain {source}')
        if observation.geometry_hash != row['token']['source_geometry_hash']:
            raise ValueError('native review frame does not match projection source')
        if not row['evidence']:
            continue
        sensor = Image.fromarray(observation.rgb)
        endpoints = sensor.copy()
        draw_endpoints(endpoints, observation, row['native_geometry'])
        for index, item in enumerate(row['evidence'], 1):
            evidence = item['evidence']
            array_path = report_path.parent / evidence['asset_key']
            with np.load(array_path, allow_pickle=False) as payload:
                mask = payload['mask']
            if hashlib.sha256(mask.tobytes()).hexdigest() != evidence['mask_sha256']:
                raise ValueError('detection mask failed checksum')
            x0, y0, x1, y1 = evidence['bbox_xyxy']
            marked = np.asarray(sensor).copy()
            region = marked[y0:y1, x0:x1]
            region[mask] = ((region[mask].astype(np.uint16) + (255, 153, 35)) // 2).astype(np.uint8)
            panel = Image.new('RGB', (sensor.width*2, sensor.height+26), '#172328')
            panel.paste(Image.fromarray(marked), (0, 26))
            panel.paste(endpoints, (sensor.width, 26))
            draw = ImageDraw.Draw(panel)
            draw.text((8, 7), f"Detection: {item['category']}", fill='white')
            draw.text((sensor.width+8, 7), f"Native boxes — revision {row['revision']}", fill='white')
            filename = f"r{row['revision']:02d}-d{index:02d}.png"
            panel.save(output / filename)
            labels.append(dict(revision=row['revision'], detection_id=evidence['detection_id'],
                               status='unresolved', native_id=None, image=filename))
    (output/'annotations.json').write_text(json.dumps(dict(schema_version=1,
        report_sha256=hashlib.sha256(raw).hexdigest(), labels=labels), indent=2)+'\n')
    print(f'Prepared {len(labels)} blind review panels')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--recording', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.report, args.recording, args.output)
