#!/usr/bin/env python3
"""Inspect the Room policy on source-pinned archived UI publications.

This consumes saved measured maps and published DuDe polygons; it does not run a
simulator, infer missing history, or measure room accuracy without annotations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from neusymnav.contracts import Region, RegionSnapshot
from neusymnav.hierarchy import HierarchyComposer
from neusymnav.runtime.ui_transport import decode_publication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('publications', nargs='+', type=Path,
                        help='Chronologically ordered ui/publication.json files from one episode')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    composer = HierarchyComposer()
    records = []
    for path in args.publications:
        raw = path.read_bytes()
        envelope = decode_publication(raw)
        hierarchy = envelope.hierarchy
        nav, objects = envelope.sources.nav, envelope.sources.objects
        if nav is None or objects is None:
            raise ValueError('archive must retain source-pinned nav and object snapshots')
        if nav.revision != hierarchy.map_revision:
            raise ValueError('archive source map must match hierarchy revision')
        floors = [n for n in hierarchy.nodes.values() if n.kind == 'floor']
        if len(floors) != 1:
            raise ValueError('single-floor archive required')
        floor_id = floors[0].attributes['floor_id']
        # Rebuild only the actually published polygons, retaining the exact map
        # revision. Historical raw native responses are not present in this DTO.
        regions = {key: Region(key, node.attributes['polygon'])
                   for key, node in hierarchy.nodes.items() if node.kind == 'region'}
        snapshot = RegionSnapshot(nav.episode_id, hierarchy.region_revision,
                                  nav.revision, floor_id, regions,
                                  hierarchy.statuses.get('regions') == 'unavailable')
        def compose_debug():
            result = composer.compose(objects, nav, snapshot,
                                      latest_nav_revision=hierarchy.latest_nav_revision,
                                      now_ns=envelope.published_monotonic_ns,
                                      clock_domain=nav.clock_domain)
            return next(n.attributes['room_debug'] for n in result.nodes.values()
                        if n.kind == 'floor')
        first = compose_debug()
        # Serialize nested immutable contract mappings through the standard wire
        # conversion path rather than assuming MappingProxyType is JSON-native.
        def plain(value):
            from collections.abc import Mapping
            if isinstance(value, Mapping):
                return {str(k): plain(v) for k, v in value.items()}
            if isinstance(value, (tuple, list)):
                return [plain(v) for v in value]
            return value
        first = plain(first)
        for _ in range(5):
            if plain(compose_debug()) != first:
                raise AssertionError('repeated identical source publication changed Room evidence')
        records.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(),
                        'map_revision': nav.revision, 'shape': list(nav.states.shape),
                        'published_region_count': len(regions), 'room_debug': first,
                        'five_identical_repeats_unchanged': True})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'schema': 'room_policy_archive_probe_v1',
        'scope': 'archived measured input; reconstructed published region polygons',
        'room_accuracy_measured': False, 'records': records}, indent=2, allow_nan=False)+'\n')
    print(f'{len(records)} source-pinned publications checked; output: {args.output}')


if __name__ == '__main__':
    main()
