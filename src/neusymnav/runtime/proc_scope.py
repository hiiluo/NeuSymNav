"""Bounded Linux process-tree census via every reachable thread's children.

Global /proc churn is outside this scope. A missing reachable node or thread is
ambiguous and fails the trial; callers may start a fully fresh bounded trial.
"""
import os
from pathlib import Path
import time


class ScopeIdentityError(ValueError):
    pass


class ScopeLimitError(ValueError):
    pass


class ScopeDeadlineError(TimeoutError):
    pass


def check_deadline(deadline_ns):
    if time.monotonic_ns() >= deadline_ns:
        raise ScopeDeadlineError('process scope deadline')


def rooted_census(provider, deadline_ns):
    """Return PID -> (ppid, starttime) only for one root and its descendants."""
    selected = {}
    pending = [(provider.root_pid, None)]
    entries_seen = 0
    if provider._root_start is None:
        raise ScopeIdentityError('root identity unavailable')
    while pending:
        check_deadline(deadline_ns)
        pid, expected_parent = pending.pop()
        if pid in selected:
            raise ScopeIdentityError('duplicate or cyclic child scope')
        if len(selected) >= provider.max_processes:
            raise ScopeLimitError('selected process cap')
        identity = provider._stat(pid)
        if (pid == provider.root_pid and identity[1] != provider._root_start) or (
                expected_parent is not None and identity[0] != expected_parent):
            raise ScopeIdentityError('process identity or parent changed')
        selected[pid] = identity
        thread_count = 0
        with os.scandir(provider.proc_root/str(pid)/'task') as entries:
            for entry in entries:
                check_deadline(deadline_ns)
                entries_seen += 1
                if entries_seen > provider.max_directory_entries:
                    raise ScopeLimitError('thread enumeration cap')
                if not entry.name.isascii() or not entry.name.isdecimal():
                    continue
                if len(entry.name) > 10 or int(entry.name) <= 0:
                    raise ValueError('invalid thread identity')
                thread_count += 1
                with (Path(entry.path)/'children').open() as handle:
                    text = handle.read(65537)
                if len(text) > 65536:
                    raise ScopeLimitError('children text cap')
                for child in text.split():
                    check_deadline(deadline_ns)
                    if (not child.isascii() or not child.isdecimal() or
                            len(child) > 10 or int(child) <= 0):
                        raise ValueError('invalid child identity')
                    if len(selected)+len(pending) >= provider.max_processes:
                        raise ScopeLimitError('pending process cap')
                    pending.append((int(child), pid))
        if not thread_count or provider._stat(pid) != identity:
            raise ScopeIdentityError('process changed during thread enumeration')
    check_deadline(deadline_ns)
    if provider._stat(provider.root_pid)[1] != provider._root_start:
        raise ScopeIdentityError('root identity changed')
    return selected
