#!/usr/bin/env python3
"""Evaluate a fixed JSON graph/GT bundle; no detector or simulator is invoked."""
import argparse
import hashlib
import json
from pathlib import Path

from neusymnav.evaluation.graph_admission import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    report = evaluate(json.loads(raw))
    report['input_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
