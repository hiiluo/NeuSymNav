#!/usr/bin/env python3
"""Evaluate frozen room-label predictions against one physical-room annotation."""
import argparse
import hashlib
import json
from pathlib import Path

from neusymnav.evaluation.room_labels import evaluate_room_label_pilot


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True,help='JSON rows joining annotation and predictions')
    parser.add_argument('--model-version',required=True)
    parser.add_argument('--out',required=True)
    args=parser.parse_args(argv)
    path=Path(args.input); raw=path.read_bytes(); rows=json.loads(raw)
    if not isinstance(rows,list):
        raise ValueError('input must be a JSON array')
    report=evaluate_room_label_pilot(rows,model_version=args.model_version)
    report['input_sha256']=hashlib.sha256(raw).hexdigest()
    report['input_path']=str(path)
    output=Path(args.out); output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
