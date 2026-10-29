"""Explicit opt-in read-only nvidia-smi samples, attributed to one process tree.

No device query occurs at import/construction. Missing devices, ambiguous scope,
PID reuse or command errors are unsupported, never device-total VRAM usage.
"""
from __future__ import annotations
import os
import math
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
from .resources import GpuReading, ProcTreeProvider, _ProviderDiagnostics, _integer
from .proc_scope import ScopeIdentityError, ScopeLimitError, ScopeDeadlineError


class _GpuScopeChanged(ValueError):
    pass


class _GpuScopeMissing(FileNotFoundError):
    pass


class _GpuScopeReadError(ValueError):
    pass


class NvidiaSmiProvider:
    def __init__(self,*,executable,gpu_uuid,root_pid=None,proc_root='/proc',max_attempts=3):
        self.executable=Path(executable)
        if not self.executable.is_absolute() or not self.executable.is_file():raise ValueError('explicit existing absolute nvidia-smi executable required')
        if type(gpu_uuid) is not str or re.fullmatch(r'GPU-[A-Za-z0-9-]{1,100}',gpu_uuid) is None:raise ValueError('explicit bounded GPU UUID required')
        self.gpu_uuid=gpu_uuid
        self.max_attempts=_integer(max_attempts,'max_attempts',1)
        if self.max_attempts>3:raise ValueError('GPU retry cap too large')
        self._scope=ProcTreeProvider(root_pid=root_pid,proc_root=proc_root)
        self._diagnostics=_ProviderDiagnostics()
    def diagnostics(self):
        return self._diagnostics.snapshot()
    def _tree(self,deadline):
        try:
            return self._scope._census(int(deadline*1e9))
        except (ScopeIdentityError,ScopeLimitError,ScopeDeadlineError):
            raise
        except FileNotFoundError as exc:
            raise _GpuScopeMissing('reachable process/thread missing') from exc
        except (OSError,ValueError) as exc:
            raise _GpuScopeReadError('reachable scope unreadable') from exc
    def _query(self,argument,deadline):
        if time.monotonic()>=deadline:raise TimeoutError('GPU deadline')
        process=subprocess.Popen([str(self.executable),argument,'--format=csv,noheader,nounits'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
        output=bytearray();selector=None
        try:
            selector=selectors.DefaultSelector()
            selector.register(process.stdout,selectors.EVENT_READ)
            while selector.get_map():
                remaining=deadline-time.monotonic()
                if remaining<=0:raise TimeoutError('GPU query deadline')
                for key,_ in selector.select(remaining):
                    chunk=os.read(key.fileobj.fileno(),4096)
                    if not chunk:selector.unregister(key.fileobj);break
                    if len(output)+len(chunk)>65536:raise ValueError('GPU output bound')
                    output.extend(chunk)
            status=process.wait(timeout=max(.001,deadline-time.monotonic()))
            if status or time.monotonic()>deadline:raise ValueError('GPU command failed or late')
            return output.decode('ascii',errors='strict')
        finally:
            # This private process group belongs to this query. Reap/kill it
            # on every exit, including output overflow while descendants keep
            # the pipe open and the group leader has already exited.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            if selector is not None:
                try:selector.close()
                except OSError:pass
            try:process.stdout.close()
            except OSError:pass
            try:process.wait(timeout=.2)
            except subprocess.TimeoutExpired:pass
    def _sample(self,deadline):
        before=self._tree(deadline)
        devices=self._query('--query-gpu=uuid',deadline)
        if time.monotonic()>=deadline:raise ScopeDeadlineError('GPU enumeration late')
        devices=devices.splitlines()
        if len(devices)>4096:raise ValueError('GPU device row cap')
        devices=[line.strip() for line in devices if line.strip()]
        if len(set(devices))!=len(devices) or any(re.fullmatch(r'GPU-[A-Za-z0-9-]{1,100}',line) is None for line in devices):raise ValueError('malformed GPU enumeration')
        if self.gpu_uuid not in devices:return GpuReading(None,'selected_gpu_unavailable')
        text=self._query('--query-compute-apps=pid,gpu_uuid,used_gpu_memory',deadline)
        if time.monotonic()>=deadline:raise ScopeDeadlineError('GPU memory query late')
        total=0;seen=set()
        lines=text.splitlines()
        if len(lines)>4096:raise ValueError('GPU row cap')
        for line in lines:
            if not line.strip():continue
            fields=[s.strip() for s in line.split(',')]
            if len(fields)!=3 or not fields[0].isascii() or not fields[0].isdecimal() or len(fields[0])>10:raise ValueError('invalid GPU row')
            pid=int(fields[0]);uuid=fields[1]
            if len(uuid)>104 or (pid,uuid) in seen:raise ValueError('duplicate or oversized GPU row')
            seen.add((pid,uuid))
            if uuid!=self.gpu_uuid or pid not in before:continue
            if not fields[2].isascii() or not fields[2].isdecimal() or len(fields[2])>12:raise ValueError('unsupported GPU memory')
            total+=int(fields[2])*1024**2
            if total>2**63-1:raise ValueError('GPU counter overflow')
        after=self._tree(deadline)
        if before!=after:raise _GpuScopeChanged('process tree changed during GPU query')
        if time.monotonic()>=deadline:raise ScopeDeadlineError('GPU sample late')
        return GpuReading(total)

    def __call__(self,deadline):
        # One absolute host-monotonic nanosecond budget covers every fresh trial.
        self._diagnostics.add(calls=1)
        if type(deadline) is not int or not 0<deadline<2**63:return GpuReading(None,'invalid_or_expired_deadline')
        remaining_ns=deadline-time.monotonic_ns()
        if not 0<remaining_ns<=1_000_000_000:return GpuReading(None,'invalid_or_expired_deadline')
        deadline_ns=deadline
        deadline=deadline/1e9
        reason='gpu_query_or_scope_unavailable'
        for attempt in range(self.max_attempts):
            if time.monotonic_ns()>=deadline_ns:
                self._diagnostics.add(deadline_exhaustions=1)
                return GpuReading(None,'provider_timeout')
            self._diagnostics.add(attempts=1,retries=int(attempt>0))
            try:
                result=self._sample(deadline)
                if time.monotonic_ns()>=deadline_ns:raise ScopeDeadlineError('GPU sample late')
                if result.used_bytes is None:self._diagnostics.add(failed_attempts=1,query_errors=1)
                return result
            except (ScopeDeadlineError,TimeoutError):
                self._diagnostics.add(failed_attempts=1,deadline_exhaustions=1)
                return GpuReading(None,'provider_timeout')
            except _GpuScopeChanged:
                self._diagnostics.add(failed_attempts=1,scope_changes=1)
                reason='process_tree_changed_during_gpu_query'
            except ScopeIdentityError:
                self._diagnostics.add(failed_attempts=1,identity_changes=1)
                reason='process_scope_identity_changed'
            except ScopeLimitError:
                self._diagnostics.add(failed_attempts=1,scope_truncations=1)
                reason='process_scope_truncated'
            except _GpuScopeMissing:
                self._diagnostics.add(failed_attempts=1,missing_processes=1)
                reason='process_scope_missing'
            except _GpuScopeReadError:
                self._diagnostics.add(failed_attempts=1,read_errors=1)
                reason='process_scope_unreadable'
            except (OSError,ValueError,UnicodeError,IndexError,subprocess.SubprocessError):
                if time.monotonic_ns()>=deadline_ns:
                    self._diagnostics.add(failed_attempts=1,deadline_exhaustions=1)
                    return GpuReading(None,'provider_timeout')
                self._diagnostics.add(failed_attempts=1,query_errors=1)
                return GpuReading(None,'gpu_query_or_scope_unavailable')
        self._diagnostics.add(attempt_limit_exhaustions=1)
        return GpuReading(None,reason)
