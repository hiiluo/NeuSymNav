"""CPU priority for optional workers: Control > Hydra > Detector > UI/SLM.

The control process and the Habitat sensor worker keep the default nice 0;
only optional/perception workers are lowered. Linux nice is per thread and
inherited by threads and children created afterwards, so a worker is either
started under ``nice`` (``nice_prefix``) or, when it is spawned elsewhere,
every existing thread of the process tree is lowered right after launch
(``renice_tree``). Raising priority (lower nice) is never attempted.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil

PRIORITY_WORKERS = ('hydra', 'detector', 'ui')
MAX_NICE = 19


def validate_process_priority(value) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError('runtime.process_priority must be a mapping')
    unknown = set(value) - set(PRIORITY_WORKERS)
    if unknown:
        raise ValueError(f'runtime.process_priority has unknown workers: {sorted(unknown)}')
    result = {}
    for name, nice in value.items():
        if type(nice) is not int or not 0 <= nice <= MAX_NICE:
            raise ValueError(f'runtime.process_priority.{name} must be an int nice in [0, 19]')
        result[name] = nice
    return result


def nice_prefix(nice: int) -> tuple[str, ...]:
    """Command prefix that starts a process (and all its children) at ``nice``."""
    if not nice:
        return ()
    binary = shutil.which('nice')
    if binary is None:
        raise RuntimeError('nice binary unavailable for configured process priority')
    return (str(Path(binary).resolve()), '-n', str(int(nice)))


def _descendant_pids(pid: int) -> list[int]:
    seen, stack = [], [pid]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.append(current)
        task_root = Path(f'/proc/{current}/task')
        try:
            tasks = list(task_root.iterdir())
        except OSError:
            continue
        for task in tasks:
            try:
                children = (task / 'children').read_text().split()
            except OSError:
                continue
            stack.extend(int(child) for child in children if child.isdigit())
    return seen


def renice_tree(pid, nice: int) -> dict:
    """Lower every thread of ``pid`` and its descendants to ``nice``; never raises."""
    report = {'nice': nice, 'threads': 0, 'failed': 0}
    if not nice or not isinstance(pid, int) or pid <= 0:
        return report
    for process in _descendant_pids(pid):
        try:
            tids = [int(t.name) for t in Path(f'/proc/{process}/task').iterdir()]
        except OSError:
            tids = [process]
        for tid in tids:
            try:
                if os.getpriority(os.PRIO_PROCESS, tid) < nice:
                    os.setpriority(os.PRIO_PROCESS, tid, nice)
                report['threads'] += 1
            except (OSError, PermissionError):
                report['failed'] += 1
    return report
