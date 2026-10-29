#!/usr/bin/env python3
"""Check Git-selected source payload; findings never contain matched secret values.

This bounded heuristic complements review; it is not a comprehensive secret or
license scanner. It changes neither the index nor the working tree.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import subprocess

MAX_FILE_BYTES=10*1024**2
FORBIDDEN_ROOTS={'.runtime','.venv','runs','data','datasets','models','checkpoints','local-assets','.ssh','.aws','.codex','.agents'}
BINARY_SUFFIXES={'.pt','.pth','.ckpt','.safetensors','.onnx','.engine','.glb','.navmesh','.a','.o','.so'}
PATTERNS={
    'private_key':re.compile(rb'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    'github_token':re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{60,255})\b'),
    'aws_access_key':re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
}


def audit(root: Path, *, candidates: bool=False) -> dict:
    args=['git','-C',str(root),'ls-files','--cached','-z']
    if candidates:args[4:4]=['--others','--exclude-standard']
    result=subprocess.run(args,capture_output=True,check=False)
    if result.returncode:
        raise ValueError('root must be a readable Git repository')
    paths=sorted(set(p.decode('utf-8') for p in result.stdout.split(b'\0') if p))
    index={}
    if not candidates:
        staged=subprocess.run(['git','-C',str(root),'ls-files','--stage','-z'],capture_output=True,check=True)
        for row in staged.stdout.split(b'\0'):
            if not row:continue
            info,name=row.split(b'\t',1);mode,oid,stage=info.decode().split()
            if stage!='0':raise ValueError('resolve unmerged index before publication')
            index[name.decode('utf-8')]=(mode,oid)
    findings=[];total=0
    for name in paths:
        relative=Path(name);path=root/relative
        def flag(kind):findings.append(dict(path=name,kind=kind))
        if relative.is_absolute() or '..' in relative.parts:
            flag('unsafe_path');continue
        if (relative.parts[0] in FORBIDDEN_ROOTS or relative.parts[:3]==('native','dude','upstream')
                or relative.suffix.lower() in BINARY_SUFFIXES
                or relative.name=='.git-credentials' or relative.name=='.env' or relative.name.startswith('.env.') and relative.name!='.env.example'
                or relative.suffix.lower() in {'.pem','.key'}):
            flag('excluded_material');continue
        if candidates:
            if path.is_symlink():flag('symlink');continue
            if not path.is_file():flag('missing_regular_file');continue
            size=path.stat().st_size;total+=size
            if size>MAX_FILE_BYTES:flag('file_over_10MiB');continue
            content=path.read_bytes()
        else:
            mode,oid=index[name]
            if mode not in ('100644','100755'):flag('non_regular_index_entry');continue
            size=int(subprocess.check_output(['git','-C',str(root),'cat-file','-s',oid]));total+=size
            if size>MAX_FILE_BYTES:flag('file_over_10MiB');continue
            content=subprocess.check_output(['git','-C',str(root),'cat-file','blob',oid])
        for kind,pattern in PATTERNS.items():
            if pattern.search(content):flag(kind)
    return dict(ready=not findings,scope='git candidates' if candidates else 'exact git index blobs',
                file_count=len(paths),total_bytes=total,max_file_bytes=MAX_FILE_BYTES,findings=findings,
                limitation='heuristic patterns; review licensing, contents and staged changes before publication')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path.cwd());p.add_argument('--candidates',action='store_true');args=p.parse_args()
    try:value=audit(args.root.absolute(),candidates=args.candidates)
    except (ValueError,OSError,UnicodeError) as exc:
        print(json.dumps(dict(ready=False,error=str(exc))));return 2
    print(json.dumps(value,indent=2));return 0 if value['ready'] else 1


if __name__=='__main__':raise SystemExit(main())
