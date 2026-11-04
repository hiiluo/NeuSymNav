#!/usr/bin/env python3
"""Run fixed-input, offline active-perception diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path

from neusymnav.evaluation.active_perception import evaluate_retained, oracle_frame


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gt', required=True, type=Path)
    p.add_argument('--predictions', required=True, type=Path)
    p.add_argument('--replay', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--ledger',type=Path)
    p.add_argument('--oracle-label-out',type=Path)
    args = p.parse_args()
    if (args.ledger is None)!=(args.oracle_label_out is None):p.error('label oracle requires --ledger and --oracle-label-out')
    paths = (args.gt, args.predictions, args.replay)
    raw = [path.read_bytes() for path in paths]
    gt,pred,replay=map(json.loads,raw)
    report=evaluate_retained(gt,pred,replay)
    if args.oracle_label_out is not None:
        from neusymnav.evaluation.graph_admission import replay_owner
        labels={}
        gt_by={f['frame_id']:f for f in gt['frames']}
        for f in pred['frames']:
            g=gt_by[f['frame_id']]['objects'];d=f['objects']
            pairs=oracle_frame([dict(id=o['id'],label=o['label'],box=o['bbox']) for o in g],
                              [dict(id=o['id'],label=o['label'],box=o['bbox']) for o in d])['pairs']
            labels[f['frame_id']]={d[i]['id']:g[j]['label'] for i,j in pairs}
        oracle=replay_owner(args.ledger,args.predictions,args.oracle_label_out,label_oracle=labels)
        if oracle['ledger_logical_sha256']!=replay['ledger_logical_sha256']:
            raise ValueError('oracle and baseline ledger digest mismatch')
        report['owner_replay_label_oracle']=dict(
            label_overrides=oracle['label_overrides'],
            diagnostic=evaluate_retained(gt,pred,oracle))

    report['input_sha256'] = {str(path): hashlib.sha256(b).hexdigest() for path, b in zip(paths, raw)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
