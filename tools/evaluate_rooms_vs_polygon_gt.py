#!/usr/bin/env python3
"""Score Hydra room segmentation of a run against hand-drawn room polygons.

    python3 tools/evaluate_rooms_vs_polygon_gt.py runs/<run> docs/results/gt/00806-rooms-gt-v1.json

Reads the final Hydra graph published to the UI (``<run>/ui/publication.json``)
and assigns every place node to the GT polygon containing it (places outside
every polygon are *unlabeled*, not errors). Reports, per GT room, the dominant
Hydra room and its share (coverage), per Hydra room its dominant GT room and
share of labeled places (purity), merges (one Hydra room holding >= 20 % of
two GT rooms), splits (one GT room spread >= 20 % over two Hydra rooms) and a
greedy one-to-one matching. Place-level only; Hydra positions are used as-is.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path


def inside(point, polygon):
    x, y = point
    hit = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
    return hit


def load_graph(run):
    publication = json.loads((Path(run) / 'ui' / 'publication.json').read_text())
    graph = publication['payload']['fields']['sources']['fields']['hydra_graph']['fields']
    nodes = [n['fields'] for n in graph['nodes']['items']]
    rooms = {n['node_id']: n['native_id'] for n in nodes if n['layer_id'] == 4}
    places = [(tuple(n['position']['items'][:2]), rooms.get(n.get('parent_id'), 'no_room'))
              for n in nodes if n['layer_id'] == 3]
    return graph.get('graph_revision'), rooms, places


def evaluate(places, gt_rooms, share=0.2):
    table = defaultdict(Counter)  # gt -> hydra -> count
    unlabeled = Counter()
    for xy, hydra in places:
        gt = next((r['id'] for r in gt_rooms if inside(xy, r['polygon'])), None)
        if gt is None:
            unlabeled[hydra] += 1
        else:
            table[gt][hydra] += 1
    by_hydra = defaultdict(Counter)
    for gt, row in table.items():
        for hydra, count in row.items():
            by_hydra[hydra][gt] += count
    gt_report = {}
    for room in gt_rooms:
        row = table.get(room['id'], Counter())
        total = sum(row.values())
        best, count = (row.most_common(1)[0] if row else (None, 0))
        gt_report[room['id']] = dict(places=total, best_hydra=best,
            coverage=round(count / total, 3) if total else None,
            split=[h for h, c in row.items() if total and c / total >= share and h != 'no_room'][1:] and
                  sorted(h for h, c in row.items() if c / total >= share and h != 'no_room'),
            hydra=dict(row.most_common()))
    hydra_report = {}
    for hydra, row in sorted(by_hydra.items()):
        total = sum(row.values())
        best, count = row.most_common(1)[0]
        merged = sorted(g for g, c in row.items()
                        if c / max(1, sum(table[g].values())) >= share)
        hydra_report[hydra] = dict(labeled_places=total, unlabeled_places=unlabeled.get(hydra, 0),
            best_gt=best, purity=round(count / total, 3), merges=merged if len(merged) > 1 else [],
            gt=dict(row.most_common()))
    # Greedy one-to-one matching by overlap.
    pairs = sorted(((c, g, h) for g, row in table.items() for h, c in row.items() if h != 'no_room'),
                   reverse=True)
    used_g, used_h, matching = set(), set(), {}
    for count, g, h in pairs:
        if g not in used_g and h not in used_h:
            matching[g] = h; used_g.add(g); used_h.add(h)
    labeled = sum(sum(r.values()) for r in table.values())
    matched_places = sum(table[g][h] for g, h in matching.items())
    return dict(places=len(places), labeled_places=labeled, unlabeled_places=sum(unlabeled.values()),
                matching=matching,
                matched_place_accuracy=round(matched_places / labeled, 3) if labeled else None,
                gt_rooms_matched=f'{len(matching)}/{len(gt_rooms)}',
                gt=gt_report, hydra=hydra_report)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run')
    parser.add_argument('gt')
    parser.add_argument('--json', action='store_true', help='print the full report as JSON')
    args = parser.parse_args(argv)
    gt = json.loads(Path(args.gt).read_text())
    if gt.get('kind') != 'room_polygon_gt':
        raise SystemExit('not a room_polygon_gt file')
    revision, rooms, places = load_graph(args.run)
    report = dict(run=str(args.run), graph_revision=revision, hydra_rooms=len(rooms),
                  **evaluate(places, gt['rooms']))
    if args.json:
        print(json.dumps(report, indent=1))
        return 0
    print(f"run {report['run']} · Hydra r{revision} · {len(rooms)} rooms · {report['places']} places "
          f"({report['labeled_places']} inside GT, {report['unlabeled_places']} unlabeled)")
    print(f"GT rooms matched {report['gt_rooms_matched']} · matched place accuracy "
          f"{report['matched_place_accuracy']}")
    for g, row in report['gt'].items():
        print(f"  GT {g:10s} places {row['places']:4d} → best {row['best_hydra']} "
              f"coverage {row['coverage']} split {row['split'] or '-'} {row['hydra']}")
    for h, row in report['hydra'].items():
        print(f"  Hydra {h:8s} labeled {row['labeled_places']:4d} (+{row['unlabeled_places']} unlabeled) → "
              f"{row['best_gt']} purity {row['purity']} merges {row['merges'] or '-'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
