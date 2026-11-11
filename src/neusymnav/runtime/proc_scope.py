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
    def __init__(self, message='process scope deadline', *, phase='unknown', pid=None):
        super().__init__(message)
        self.phase=phase
        self.pid=pid


def check_deadline(deadline_ns, *, phase='deadline_check', pid=None):
    if time.monotonic_ns() >= deadline_ns:
        raise ScopeDeadlineError('process scope deadline',phase=phase,pid=pid)


def rooted_census(provider, deadline_ns, *, phase='census'):
    """Return PID -> (ppid, starttime) only for one root and its descendants."""
    selected = {}
    pending = [(provider.root_pid, None)]
    entries_seen = 0
    if provider._root_start is None:
        raise ScopeIdentityError('root identity unavailable')
    while pending:
        pid, expected_parent = pending.pop()
        provider._diagnostic_phase=phase+':process';provider._diagnostic_pid=pid
        check_deadline(deadline_ns,phase=phase+':process',pid=pid)
        if pid in selected:
            raise ScopeIdentityError('duplicate or cyclic child scope')
        if len(selected) >= provider.max_processes:
            raise ScopeLimitError('selected process cap')
        identity = provider._stat(pid)
        check_deadline(deadline_ns,phase=phase+':process_stat',pid=pid)
        if (pid == provider.root_pid and identity[1] != provider._root_start) or (
                expected_parent is not None and identity[0] != expected_parent):
            raise ScopeIdentityError('process identity or parent changed')
        selected[pid] = identity
        thread_count = 0
        provider._diagnostic_phase=phase+':thread_children_open';provider._diagnostic_pid=pid
        with os.scandir(provider.proc_root/str(pid)/'task') as entries:
            for entry in entries:
                provider._diagnostic_phase=phase+':thread_children';provider._diagnostic_pid=pid
                check_deadline(deadline_ns,phase=phase+':thread_children',pid=pid)
                entries_seen += 1
                if entries_seen > provider.max_directory_entries:
                    raise ScopeLimitError('thread enumeration cap')
                if not entry.name.isascii() or not entry.name.isdecimal():
                    continue
                if len(entry.name) > 10 or int(entry.name) <= 0:
                    raise ValueError('invalid thread identity')
                thread_count += 1
                provider._diagnostic_phase=phase+':children_read';provider._diagnostic_pid=pid
                try:
                    with (Path(entry.path)/'children').open() as handle:
                        text = handle.read(65537)
                except FileNotFoundError:
                    # /proc/<pid>/task/<tid> can disappear between scandir
                    # and reading children when a thread exits. Ignore only
                    # that vanished task directory; a missing children file
                    # under a still-live task remains an unsupported census.
                    try:os.stat(entry.path)
                    except FileNotFoundError:
                        if provider._stat(pid)!=identity:
                            raise ScopeIdentityError('process changed as thread exited')
                        continue
                    raise
                if len(text) > 65536:
                    raise ScopeLimitError('children text cap')
                for child in text.split():
                    check_deadline(deadline_ns,phase=phase+':child_list',pid=pid)
                    if (not child.isascii() or not child.isdecimal() or
                            len(child) > 10 or int(child) <= 0):
                        raise ValueError('invalid child identity')
                    if len(selected)+len(pending) >= provider.max_processes:
                        raise ScopeLimitError('pending process cap')
                    pending.append((int(child), pid))
        if not thread_count:
            raise ScopeIdentityError('process changed during thread enumeration')
        provider._diagnostic_phase=phase+':process_recheck';provider._diagnostic_pid=pid
        final_identity=provider._stat(pid)
        check_deadline(deadline_ns,phase=phase+':process_recheck',pid=pid)
        if final_identity!=identity:
            raise ScopeIdentityError('process changed during thread enumeration')
    check_deadline(deadline_ns,phase=phase+':complete')
    provider._diagnostic_phase=phase+':root_recheck';provider._diagnostic_pid=provider.root_pid
    root_identity=provider._stat(provider.root_pid)
    check_deadline(deadline_ns,phase=phase+':root_recheck',pid=provider.root_pid)
    if root_identity[1] != provider._root_start:
        raise ScopeIdentityError('root identity changed')
    return selected
