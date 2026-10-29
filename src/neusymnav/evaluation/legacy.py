"""Read-only normalization of the pinned New GraphStore.export_json schema.

No legacy Python imports, checkpoint loading, runtime execution or implicit frame
conversion. Input matching/provenance must be supplied separately by the suite.
This adapter alone provides no identity metric or accuracy comparison.
"""
from __future__ import annotations
import numpy as np
from ..geometry.frames import Y_UP_TO_Z_UP,transform_bounds,transform_vectors
from .protocol import read_json,closed,text


def normalize_legacy_new(path,*,coordinate_convention):
    if coordinate_convention not in {'new_y_up_v1','canonical_z_up_v1'}:raise ValueError('explicit supported coordinate convention required')
    value=read_json(path)
    required={'schema_version','episode_id','version','nodes','edges','evidence'}
    if value.get('schema_version')==3:required.add('alias_journal')
    closed(value,required,'legacy New export')
    if type(value['schema_version']) is not int or value['schema_version'] not in {2,3}:raise ValueError('unsupported legacy New schema')
    if not isinstance(value['nodes'],list) or len(value['nodes'])>4096:raise ValueError('legacy node count exceeds offline bound')
    rotation=Y_UP_TO_Z_UP if coordinate_convention=='new_y_up_v1' else np.eye(3)
    objects=[];ids=set()
    for node in value['nodes']:
        # Other source fields remain unused; no semantic/schema inference.
        text(node['id'],'legacy object id')
        if node['id'] in ids:raise ValueError('duplicate legacy object id')
        ids.add(node['id'])
        bounds=transform_bounds([node['aabb_min_world'],node['aabb_max_world']],rotation)
        centroid=transform_vectors(node['centroid_world'],rotation)
        if np.any(centroid<bounds[0]) or np.any(centroid>bounds[1]):raise ValueError('legacy centroid outside bounds')
        text(node['label'],'legacy raw label')
        objects.append(dict(object_id=node['id'],raw_label=node['label'],centroid=centroid.tolist(),bounds=bounds.tolist(),lifecycle=node['status']))
    aliases={}
    for row in value.get('alias_journal',[]):
        if row['old_id'] in aliases and aliases[row['old_id']]!=row['canonical_id']:raise ValueError('conflicting legacy alias')
        aliases[row['old_id']]=row['canonical_id']
    for old in aliases:
        target=old;seen=set()
        while target in aliases:
            if target in seen:raise ValueError('legacy alias cycle')
            seen.add(target);target=aliases[target]
        if target not in ids:raise ValueError('dangling legacy alias')
    return dict(schema_version=1,source_schema_version=value['schema_version'],episode_id=value['episode_id'],
        coordinate_convention='canonical_z_up_v1',objects=sorted(objects,key=lambda o:o['object_id']),aliases=aliases,
        support='output normalization only; no paired input or GT identity support inferred')
