#!/usr/bin/env python3
"""Phase 2, step 3: score detector predictions against episode goal instances (project venv).

    PYTHONPATH=src .venv/bin/python tools/objectnav/detector_eval/score_detector.py \
        --views runs/objectnav/detector_eval/views --predictions runs/objectnav/detector_eval/predictions.jsonl \
        --out-dir runs/objectnav/detector_eval/report

Writes report.json, report.md and matches.jsonl.gz (mask-free rows, for re-analysis).
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

from neusymnav.objectnav.detector_eval.categories import DEFAULT_MAPPING, GoalCategories  # noqa: E402
from neusymnav.objectnav.detector_eval.masks import rle_decode  # noqa: E402
from neusymnav.objectnav.detector_eval.scoring import (confirmation_markdown, confirmation_table, markdown,  # noqa: E402
                                                       match_frame, summarize)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--views', type=Path, required=True)
    ap.add_argument('--predictions', type=Path, required=True)
    ap.add_argument('--out-dir', type=Path, required=True)
    ap.add_argument('--mapping', type=Path, default=DEFAULT_MAPPING)
    a = ap.parse_args(argv)
    categories = GoalCategories.load(a.mapping)
    scenes = json.loads((a.views / 'scenes.json').read_text())['scenes']
    goals = {s: {int(g['object_id']): cat for cat, items in m['goal_instances'].items() for g in items}
             for s, m in scenes.items()}
    names = {s: {int(k): v for k, v in m['names'].items()} for s, m in scenes.items()}
    # Names the episodes use for goal instances of each category (all dev scenes).
    name_cats = {}
    for m in scenes.values():
        for cat, items in m['goal_instances'].items():
            for g in items:
                name_cats.setdefault(g['name'].strip().casefold(), set()).add(cat)
    unlisted = {s: {oid: next(iter(name_cats[n.strip().casefold()])) for oid, n in names[s].items()
                    if oid not in goals[s] and len(name_cats.get(n.strip().casefold(), ())) == 1}
                for s in scenes}
    views = [json.loads(l) for l in (a.views / 'views.jsonl').read_text().splitlines() if l.strip()]
    preds = {}
    for line in a.predictions.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            preds[row['frame_id']] = row
    missing = [v['frame_id'] for v in views if v['frame_id'] not in preds]
    if missing:
        raise SystemExit('%d frames have no predictions (e.g. %s); finish step 2 first' % (len(missing), missing[0]))
    a.out_dir.mkdir(parents=True, exist_ok=True)
    gt_rows, pred_rows, scores, capped = [], [], [], 0
    for view in views:
        with np.load(a.views / 'frames' / (view['frame_id'] + '.npz')) as arrays:
            ids = arrays['semantic']
        gt_masks = {int(g['object_id']): ids == int(g['object_id']) for g in view['goals_visible']}
        frame_preds = []
        for d in preds[view['frame_id']]['detections']:
            frame_preds.append(dict(label=d['label'], score=d['score'], mask=rle_decode(d['rle'])))
            scores.append(d['score'])
        capped += bool(preds[view['frame_id']].get('cap_reached'))
        g, p = match_frame(view, ids, gt_masks, frame_preds, categories, goals[view['scene']], names[view['scene']],
                           unlisted[view['scene']])
        gt_rows += g
        pred_rows += p
    report = summarize(gt_rows, pred_rows, frames=len(views), scenes=sorted(scenes), categories=categories.categories)
    report['confirmation'] = confirmation_table(gt_rows, pred_rows, scenes=sorted(scenes),
                                                categories=categories.categories)
    recipe_path = a.predictions.with_suffix('.recipe.json')
    report.update(mapping=categories.name, detector=json.loads(recipe_path.read_text()) if recipe_path.exists() else None,
                  prediction_scores=dict(count=len(scores), min=min(scores) if scores else None,
                                         frames_at_cap=capped),
                  view_kinds={k: sum(v['kind'] == k for v in views) for k in ('path', 'scan')},
                  unlisted_instances={s: len(u) for s, u in unlisted.items()},
                  alignment={s: m['alignment'] for s, m in scenes.items()},
                  goal_instances_seen={s: {cat: '%d/%d' % (sum(g['seen'] for g in items), len(items))
                                           for cat, items in m['goal_instances'].items()} for s, m in scenes.items()})
    (a.out_dir / 'report.json').write_text(json.dumps(report, indent=1) + '\n')
    md = markdown(report) + '\n' + confirmation_markdown(report['confirmation'], categories.categories)
    md += '\n## Data checks\n\n- Lowest prediction score seen: %s (if >= the runtime 0.25, the exported model filters internally and thresholds below it are not measurable)\n- Frames at the 30-detection cap: %d\n- View kinds: %s\n- Alignment (annotated vs runtime render): %s\n' % (
        report['prediction_scores']['min'], capped, report['view_kinds'],
        {s: '%d/%d' % (v['passed'], v['frames']) for s, v in report['alignment'].items()})
    (a.out_dir / 'report.md').write_text(md)
    with gzip.open(a.out_dir / 'matches.jsonl.gz', 'wt') as stream:
        for row in gt_rows:
            stream.write(json.dumps({'row_type': 'gt', **row}) + '\n')
        for row in pred_rows:
            stream.write(json.dumps({'row_type': 'pred', **row}) + '\n')
    print(md)


if __name__ == '__main__':
    main()
