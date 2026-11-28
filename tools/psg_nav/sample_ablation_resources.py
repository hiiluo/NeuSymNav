import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

output, separator, *command = sys.argv[1:]
if separator != '--':
    raise SystemExit('expected -- before executable')
process = subprocess.Popen(command)
owner = psutil.Process(process.pid)
started = time.monotonic()
with Path(output).open('w', buffering=1) as stream:
    while process.poll() is None:
        processes = [owner, *owner.children(recursive=True)]
        tree = {}
        for child in processes:
            try:
                tree[child.pid] = child.memory_info().rss
            except psutil.NoSuchProcess:
                continue
        try:
            result = subprocess.run(('nvidia-smi', '--query-compute-apps=pid,used_memory',
                                     '--format=csv,noheader,nounits'), capture_output=True,
                                    text=True, timeout=1, check=True)
            vram = {}
            for line in result.stdout.splitlines():
                pid, mib = (part.strip() for part in line.split(',', 1))
                if int(pid) in tree:
                    vram[int(pid)] = int(mib)
        except (OSError, ValueError, subprocess.SubprocessError):
            vram = None
        sample = dict(wall_s=round(time.monotonic() - started, 3), host_rss_bytes=tree.get(owner.pid),
                      tree_rss_bytes=sum(tree.values()), processes=len(tree), compute_vram_mib=vram)
        stream.write(json.dumps(sample) + '\n')
        try:
            process.wait(timeout=2.)
        except subprocess.TimeoutExpired:
            pass
raise SystemExit(process.wait())
