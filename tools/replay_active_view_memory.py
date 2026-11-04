#!/usr/bin/env python3
"""Passive B/M view selection on identical retained committed detections."""
import argparse
from collections import defaultdict
from contextlib import closing
import json
import itertools
import math
import numpy as np
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from neusymnav.contracts.serialization import loads
from neusymnav.objects.assets import AssetStore
from neusymnav.verification.best_views import BestViewSelector
from neusymnav.verification.ledger import VerificationOwner
from neusymnav.verification.view_memory import ViewMemory, read_committed_views


def replay(run, predictions):
    run=Path(run)
    exported=json.loads(Path(predictions).read_text())
    frames={x['frame_index'] for x in exported['frames']}
    snapshot=loads((run/'objects.json').read_text())
    assets=run/'objects'/'assets'
    if not assets.is_dir():raise ValueError('missing committed asset directory')
    memory=ViewMemory(snapshot.episode_id)
    baseline={}
    total=accepted=0
    evidence={}
    with closing(sqlite3.connect((run/'objects'/'objects.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as conn, \
            closing(sqlite3.connect((run/'verification'/'verification.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)) as verification:
        conn.row_factory=verification.row_factory=sqlite3.Row
        config=json.loads(conn.execute("SELECT value FROM metadata WHERE key='config'").fetchone()[0])
        owner=SimpleNamespace(ledger=SimpleNamespace(connection=conn),assets=AssetStore(assets),_config=config)
        batches=defaultdict(list)
        for row in conn.execute('SELECT event_id,data FROM views WHERE object_id IS NOT NULL ORDER BY rowid'):
            source=json.loads(row['data'])['source']
            if source['frame_index'] in frames:batches[source['frame_index']].append(row['event_id'])
        for frame in sorted(batches):
            ids=batches[frame]
            total+=len(ids)
            views=read_committed_views(owner,SimpleNamespace(snapshot=snapshot,committed_event_ids=tuple(ids)))
            for view in views:
                row=verification.execute("SELECT * FROM views WHERE event_id=? AND kind='detected'",(view.event_id,)).fetchone()
                if row is None:continue
                b=VerificationOwner._best(row,view.object_id)
                if b.source!=view.source or b.geometry_hash!=view.geometry_hash:
                    raise ValueError('baseline view binding mismatch')
                accepted+=1
                evidence[view.event_id]=view
                baseline.setdefault(view.object_id,BestViewSelector(view.object_id)).offer(b)
                memory.offer(view)
    modern=memory.snapshot(snapshot.revision)
    rows=[]
    def diversity(refs):
        pairs=[(float(np.linalg.norm(a.camera_pose_world[:3,3]-b.camera_pose_world[:3,3])),
                math.degrees(math.acos(float(np.clip(a.view_direction @ b.view_direction,-1,1)))))
               for a,b in itertools.combinations((evidence[r] for r in refs),2)]
        return dict(pairs=len(pairs),minimum_baseline_m=min((x[0] for x in pairs),default=None),
                    minimum_angle_deg=min((x[1] for x in pairs),default=None),
                    independent_pairs=sum(x>=.3 and y>=15 for x,y in pairs))

    for oid,selector in sorted(baseline.items()):
        b=selector.snapshot();m=modern.views.get(oid,())
        rows.append(dict(object_id=oid,baseline_refs=[v.event_id for v in b],memory_refs=[v.event_id for v in m],
                         baseline_views=len(b),memory_views=len(m),
                         baseline_diversity=diversity([v.event_id for v in b]),
                         memory_diversity=diversity([v.event_id for v in m])))
    return dict(schema_version=1, episode_id=snapshot.episode_id, source_frames=len(frames),
                committed_rows=total, shared_valid_views=accepted, missing_or_invalid=total-accepted,
                baseline_retained=sum(r['baseline_views'] for r in rows),
                memory_retained=sum(r['memory_views'] for r in rows), memory_charged_bytes=modern.charged_bytes,
                memory_evictions=dict(modern.eviction_counters),objects=rows,
                limitation='Fixed committed source frames and final canonical aliases. Passive view retention only; no changed association/admission, no counterfactual future frames, no recall or precision gain inferred.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',required=True);p.add_argument('--predictions',required=True);p.add_argument('--out',required=True)
    a=p.parse_args()
    result=replay(a.run,a.predictions)
    Path(a.out).write_text(json.dumps(result,indent=2)+'\n')
