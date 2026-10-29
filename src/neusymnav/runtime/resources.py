"""Independent process-tree/GPU sampling, explicitly not a memory-cap certificate.

No sampler work executes in producer/control/graph locks. Providers can hang; they
run in daemon threads, close has one shared deadline and reports pending workers.
A pending worker is never reported as clean shutdown. No GPU probe is implicit.
"""
from dataclasses import dataclass
import math
import os
from pathlib import Path
from threading import Event, Lock, Thread
import time
from .proc_scope import (rooted_census, check_deadline, ScopeIdentityError,
                         ScopeLimitError, ScopeDeadlineError)

MAX_COUNTER = (1 << 63)-1


def _integer(value, name, minimum=0):
    if type(value) is not int or value < minimum or value > MAX_COUNTER:
        raise ValueError(f'{name} must be an integer >= {minimum}')
    return value


def _duration(value, name, maximum=60):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f'{name} must be finite and in (0, {maximum}]')
    return float(value)


@dataclass(frozen=True, slots=True)
class ResourceReading:
    sampled_at_ns: int
    rss_bytes: int | None
    process_count: int
    missing_processes: int = 0
    read_errors: int = 0
    identity_changes: int = 0
    scope_truncated: bool = False
    schema_version: str = 'process_tree_resource_reading_v1'

    def __post_init__(self):
        if type(self.schema_version) is not str or self.schema_version != 'process_tree_resource_reading_v1':
            raise ValueError('unknown resource schema')
        for name in ('sampled_at_ns', 'process_count', 'missing_processes', 'read_errors', 'identity_changes'):
            _integer(getattr(self, name), name)
        if self.rss_bytes is not None:
            _integer(self.rss_bytes, 'rss_bytes')
        if type(self.scope_truncated) is not bool:
            raise ValueError('scope_truncated must be bool')


@dataclass(frozen=True, slots=True)
class GpuReading:
    """Injected provider owns PID/starttime attribution and obeys call deadline.

    Valid bytes must mean usage attributed to this process tree, not device total.
    No provider ships in this primitive; unavailable is the default.
    """
    used_bytes: int | None
    unavailable_reason: str | None = None
    scope: str = 'process_tree_attributed_gpu_memory'
    schema_version: str = 'gpu_resource_reading_v1'

    def __post_init__(self):
        if (type(self.schema_version) is not str or self.schema_version != 'gpu_resource_reading_v1' or
                type(self.scope) is not str or self.scope != 'process_tree_attributed_gpu_memory'):
            raise ValueError('unknown GPU schema/scope')
        if self.used_bytes is not None:
            _integer(self.used_bytes, 'used_bytes')
            if self.unavailable_reason is not None:
                raise ValueError('supported GPU sample cannot have unavailable reason')
        elif (type(self.unavailable_reason) is not str or
              not 1 <= len(self.unavailable_reason) <= 128):
            raise ValueError('unavailable GPU sample requires bounded reason')


class _ProviderDiagnostics:
    """Small sidecar counters; never inserted into the closed resource artifact."""
    def __init__(self):
        self._lock = Lock()
        self._counts = dict(calls=0, attempts=0, failed_attempts=0, retries=0,
                            missing_processes=0, read_errors=0, identity_changes=0,
                            scope_changes=0, scope_truncations=0, query_errors=0,
                            deadline_exhaustions=0, attempt_limit_exhaustions=0)
        self._saturated = False

    def add(self, **increments):
        with self._lock:
            for name, amount in increments.items():
                value = self._counts[name]+amount
                if value > MAX_COUNTER:
                    self._saturated = True
                self._counts[name] = min(MAX_COUNTER, value)

    def snapshot(self):
        with self._lock:
            return dict(schema_version=1, **self._counts, counter_saturated=self._saturated)


class ProcTreeProvider:
    """Sample one stable rooted process closure, with bounded fresh retries.

    A trial enumerates all threads' children and validates PID/ppid/starttime
    around RSS reads and a second census. Only a wholly valid trial returns a
    value. Failed trials remain in diagnostics; returned missing samples remain
    missing forever in ResourceSampler. Sequential reads are sampled, not an
    instantaneous peak or continuous memory-cap certificate.
    """
    def __init__(self, *, root_pid=None, proc_root='/proc', max_processes=4096,
                 max_directory_entries=32768, max_attempts=3, sample_timeout_s=.1,
                 retry_wait_s=.005):
        self.root_pid = os.getpid() if root_pid is None else _integer(root_pid, 'root_pid', 1)
        self.proc_root = Path(proc_root)
        self.max_processes = _integer(max_processes, 'max_processes', 1)
        self.max_directory_entries = _integer(max_directory_entries, 'max_directory_entries', 1)
        self.max_attempts = _integer(max_attempts, 'max_attempts', 1)
        self.sample_timeout_s = _duration(sample_timeout_s, 'sample_timeout_s', 1.)
        if (type(retry_wait_s) not in (int,float) or not 0<=retry_wait_s<=.25 or
                not math.isfinite(retry_wait_s)):
            raise ValueError('retry_wait_s must be finite and in [0, .25]')
        self.retry_wait_s=float(retry_wait_s)
        if (self.max_processes > 65536 or self.max_directory_entries > 262144 or
                self.max_attempts > 3):
            raise ValueError('proc scope/retry cap too large')
        self._diagnostics = _ProviderDiagnostics()
        try:
            self._root_start = self._stat(self.root_pid)[1]
        except (OSError, ValueError):
            self._root_start = None

    def _stat(self, pid):
        with (self.proc_root/str(pid)/'stat').open() as handle:
            text = handle.read(8193)
        if len(text) > 8192:
            raise ValueError('oversized stat')
        end = text.rfind(')')
        if end < 0:
            raise ValueError('invalid stat')
        fields = text[end+1:].split()
        if len(fields) < 20:
            raise ValueError('short stat')
        return _integer(int(fields[1]), 'ppid'), _integer(int(fields[19]), 'starttime')

    def _rss(self, pid):
        with (self.proc_root/str(pid)/'status').open() as handle:
            text = handle.read(65537)
        if len(text) > 65536:
            raise ValueError('oversized status')
        for line in text.splitlines():
            if line.startswith('VmRSS:'):
                fields = line.split()
                if len(fields) != 3 or fields[2] != 'kB':
                    raise ValueError('invalid RSS unit')
                return _integer(_integer(int(fields[1]), 'VmRSS')*1024, 'RSS bytes')
        # A dead leader can still have live threads sharing a resident mm.
        # Require the sole task to be a zombie and explicit zero statm; absent
        # VmRSS alone is never zero. Caller still guards PID identity/closure.
        def sole_zombie(status):
            states=[line.split()[1:] for line in status.splitlines() if line.startswith('State:')]
            threads=[line.split()[1:] for line in status.splitlines() if line.startswith('Threads:')]
            return len(states)==1 and states[0]==['Z','(zombie)'] and threads==[['1']]
        if sole_zombie(text):
            def only_task():
                names=[]
                with os.scandir(self.proc_root/str(pid)/'task') as entries:
                    for entry in entries:
                        names.append(entry.name)
                        if len(names)>1:return False
                return names==[str(pid)]
            if only_task():
                with (self.proc_root/str(pid)/'statm').open() as handle:
                    statm=handle.read(4097)
                if len(statm)<=4096 and statm.split()==['0']*7:
                    with (self.proc_root/str(pid)/'status').open() as handle:
                        final_status=handle.read(65537)
                    if len(final_status)<=65536 and sole_zombie(final_status) and only_task():
                        return 0
        return self._live_thread_rss(pid, text)

    def _live_thread_rss(self, pid, leader_status):
        """Read one shared-mm RSS, never a sum of the thread status values.

        Linux thread groups share their mm (kernel/fork.c CLONE_THREAD checks);
        proc status obtains that mm from the selected task. A zombie leader may
        lack it while a surviving thread retains it. Require a stable complete
        task set and positive identity proof; missing fields never mean zero.
        This local work deadline does not replace the caller's original trial
        deadline: __call__ still rejects any trial that finishes after that.
        """
        deadline = time.monotonic_ns()+int(self.sample_timeout_s*1e9)

        def read(path, limit=65536):
            check_deadline(deadline)
            with path.open() as handle:
                value = handle.read(limit+1)
            check_deadline(deadline)
            if len(value)>limit:
                raise ScopeLimitError('thread RSS proc text cap')
            return value

        def metadata(text, tid, *, leader=False):
            fields = {}
            names = {'State', 'Tgid', 'Pid', 'Threads', 'VmRSS'}
            for line in text.splitlines():
                name, separator, value = line.partition(':')
                if separator and name in names:
                    if name in fields:
                        raise ValueError('duplicate thread RSS field')
                    fields[name] = value.split()
            for name, expected in (('Tgid', pid), ('Pid', tid)):
                if fields.get(name) != [str(expected)]:
                    raise ScopeIdentityError('thread RSS group identity mismatch')
            count = fields.get('Threads', [])
            if (len(count)!=1 or not count[0].isascii() or not count[0].isdecimal() or
                    not 1<int(count[0])<=self.max_directory_entries):
                raise ValueError('invalid thread RSS group size')
            state = fields.get('State', [])
            states = {'R': ['(running)'], 'S': ['(sleeping)'], 'D': ['(disk', 'sleep)'],
                      'T': ['(stopped)'], 't': ['(tracing', 'stop)'], 'X': ['(dead)'],
                      'Z': ['(zombie)'], 'P': ['(parked)'], 'I': ['(idle)']}
            if not state or state[0] not in states or state[1:] != states[state[0]]:
                raise ValueError('invalid thread RSS state')
            rss = fields.get('VmRSS')
            if rss is not None:
                if (len(rss)!=2 or rss[1]!='kB' or not rss[0].isascii() or
                        not rss[0].isdecimal()):
                    raise ValueError('invalid thread RSS value')
                rss = _integer(_integer(int(rss[0]), 'VmRSS')*1024, 'RSS bytes')
            if leader:
                if state[0]!='Z' or rss is not None:
                    raise ValueError('thread RSS fallback requires mm-less zombie leader')
            elif state[0] not in ('Z', 'X') and rss is None:
                raise ValueError('live thread RSS unavailable')
            return int(count[0]), state[0], rss

        count, _, _ = metadata(leader_status, pid, leader=True)
        leader_identity = self._stat(pid)

        def tasks():
            identities = {}
            entries_seen = 0
            with os.scandir(self.proc_root/str(pid)/'task') as entries:
                for entry in entries:
                    check_deadline(deadline)
                    entries_seen += 1
                    if entries_seen>self.max_directory_entries:
                        raise ScopeLimitError('thread RSS enumeration cap')
                    name = entry.name
                    if (not name.isascii() or not name.isdecimal() or len(name)>10 or
                            int(name)<=0 or str(int(name))!=name or int(name) in identities):
                        raise ValueError('invalid thread RSS task identity')
                    tid = int(name)
                    if tid==pid:
                        identity = self._stat(pid)
                    else:
                        text = read(self.proc_root/str(pid)/'task'/name/'stat',8192)
                        end = text.rfind(')');fields = text[end+1:].split()
                        if (end<0 or text.split(' ',1)[0]!=name or len(fields)<20 or
                                any(not field.isascii() or not field.isdecimal()
                                    for field in (fields[1], fields[19]))):
                            raise ValueError('invalid thread RSS stat')
                        identity = (_integer(int(fields[1]), 'ppid'),
                                    _integer(int(fields[19]), 'starttime'))
                    identities[tid] = identity
            if pid not in identities or len(identities)!=count:
                raise ScopeIdentityError('thread RSS task set differs from group size')
            return identities

        before = tasks()
        selected_rss = None
        for tid in sorted(before):
            if tid==pid:
                continue
            # Read every task's bounded metadata so an ambiguous task cannot be
            # silently skipped to find a convenient supported thread instead.
            threads, state, value = metadata(read(self.proc_root/str(pid)/'task'/str(tid)/'status'), tid)
            if threads!=count:
                raise ScopeIdentityError('thread RSS count changed')
            if state not in ('Z', 'X') and selected_rss is None:
                selected_rss = value
        if selected_rss is None:
            raise ValueError('no verified live thread RSS')
        final_count, _, _ = metadata(read(self.proc_root/str(pid)/'status'), pid, leader=True)
        if final_count!=count or tasks()!=before or self._stat(pid)!=leader_identity:
            raise ScopeIdentityError('thread RSS identity or topology changed')
        check_deadline(deadline)
        return selected_rss

    def _census(self, deadline_ns):
        return rooted_census(self, deadline_ns)

    def diagnostics(self):
        return self._diagnostics.snapshot()

    def __call__(self):
        deadline_ns = time.monotonic_ns()+int(self.sample_timeout_s*1e9)
        self._diagnostics.add(calls=1)
        result = None
        for attempt in range(self.max_attempts):
            if attempt and time.monotonic_ns()<deadline_ns and self.retry_wait_s:
                # Give the owning parent a bounded scheduling opportunity to
                # reap a transient exited child before a wholly fresh census.
                # The shared sample deadline and three-trial cap do not move.
                time.sleep(min(self.retry_wait_s,max(0.,(deadline_ns-time.monotonic_ns())/1e9)))
            if time.monotonic_ns() >= deadline_ns:
                self._diagnostics.add(deadline_exhaustions=1)
                return ResourceReading(time.monotonic_ns(), None, 0, scope_truncated=True)
            self._diagnostics.add(attempts=1, retries=int(attempt > 0))
            now = time.monotonic_ns()
            selected = {}
            try:
                selected = self._census(deadline_ns)
                rss = 0
                for pid, identity in selected.items():
                    check_deadline(deadline_ns)
                    if self._stat(pid) != identity:
                        raise ScopeIdentityError('identity changed before RSS read')
                    rss += self._rss(pid)
                    if rss > MAX_COUNTER:
                        raise ValueError('RSS counter overflow')
                    if self._stat(pid) != identity:
                        raise ScopeIdentityError('identity changed after RSS read')
                if self._census(deadline_ns) != selected:
                    self._diagnostics.add(scope_changes=1)
                    raise ScopeIdentityError('process closure changed during RSS trial')
                check_deadline(deadline_ns)
                return ResourceReading(now, rss, len(selected))
            except ScopeDeadlineError:
                self._diagnostics.add(failed_attempts=1, deadline_exhaustions=1)
                return ResourceReading(now, None, len(selected), scope_truncated=True)
            except ScopeLimitError:
                self._diagnostics.add(failed_attempts=1, scope_truncations=1)
                result = ResourceReading(now, None, len(selected), scope_truncated=True)
            except ScopeIdentityError:
                self._diagnostics.add(failed_attempts=1, identity_changes=1)
                result = ResourceReading(now, None, len(selected), identity_changes=1)
            except FileNotFoundError:
                self._diagnostics.add(failed_attempts=1, missing_processes=1)
                result = ResourceReading(now, None, len(selected), missing_processes=1)
            except (OSError, ValueError):
                self._diagnostics.add(failed_attempts=1, read_errors=1)
                result = ResourceReading(now, None, len(selected), read_errors=1)
        self._diagnostics.add(attempt_limit_exhaustions=1)
        return result


class ResourceSampler:
    def __init__(self, *, provider=None, gpu_provider=None, interval_s=.1,
                 gpu_interval_s=1., gpu_timeout_s=1., rss_cap_bytes=None,
                 gpu_cap_bytes=None, on_cap_breach=None):
        self._provider = ProcTreeProvider() if provider is None else provider
        self._gpu_provider = gpu_provider
        if not callable(self._provider) or (gpu_provider is not None and not callable(gpu_provider)):
            raise ValueError('resource providers must be callable')
        if on_cap_breach is not None and not callable(on_cap_breach):
            raise ValueError('on_cap_breach must be callable')
        self.interval_s = _duration(interval_s, 'interval_s')
        self.gpu_interval_s = _duration(gpu_interval_s, 'gpu_interval_s')
        self.gpu_timeout_s = _duration(gpu_timeout_s, 'gpu_timeout_s', 1.)
        for name, value in (('rss_cap_bytes',rss_cap_bytes), ('gpu_cap_bytes',gpu_cap_bytes)):
            if value is not None:
                _integer(value, name, 1)
        self._caps = dict(rss=rss_cap_bytes, gpu=gpu_cap_bytes)
        self._callback = on_cap_breach
        self._lock = Lock()
        self._stop = Event()
        self._threads = {}
        self._started = False
        self._closed = False
        self._start_requested_ns = None
        self._stop_requested_ns = None
        self._shutdown_observed_ns = None
        self._breached = set()
        self._callback_errors = 0
        self._counter_saturated = False
        self._scope_proof = dict(method='injected_provider_unverified', root_pid=None,
                                 root_starttime_ticks=None, proc_root=None)
        if type(self._provider) is ProcTreeProvider:
            self._scope_proof = dict(method='linux_proc_pid_starttime_guard', root_pid=self._provider.root_pid,
                                     root_starttime_ticks=self._provider._root_start,
                                     proc_root=str(self._provider.proc_root))
        self._rss = dict(samples=0, support=0, sampled_peak_bytes=None,
                         missing_processes=0, read_errors=0, identity_changes=0,
                         truncated_samples=0, first_sample_ns=None, last_sample_ns=None,
                         max_sample_gap_ns=None, method='sampled_process_tree_rss_sum')
        self._gpu = dict(samples=0, support=0, sampled_peak_bytes=None,
                         unavailable_reason='no_usable_provider' if gpu_provider is None else 'not_sampled',
                         errors=0, timeouts=0, method='injected_process_tree_attributed_gpu_sample')

    def _add(self, state, name, amount=1):
        value = state[name]+amount
        if value > MAX_COUNTER:
            self._counter_saturated = True
        state[name] = min(MAX_COUNTER, value)

    def start(self):
        with self._lock:
            if self._started or self._closed:
                raise RuntimeError('sampler cannot start twice or after close')
            self._started = True
            self._start_requested_ns = time.monotonic_ns()
            self._threads['rss'] = Thread(target=self._run_rss, name='resource-rss', daemon=True)
            if self._gpu_provider is not None:
                self._threads['gpu'] = Thread(target=self._run_gpu, name='resource-gpu', daemon=True)
            # Starting while lifecycle lock is held avoids close racing a not-yet-started thread.
            for thread in self._threads.values():
                thread.start()

    def _check_cap(self, resource, value):
        payload = None
        with self._lock:
            cap = self._caps[resource]
            if value is not None and cap is not None and value > cap and resource not in self._breached:
                self._breached.add(resource)
                payload = dict(resource=resource, sampled_bytes=value, cap_bytes=cap)
        if payload is not None and self._callback is not None:
            try:
                self._callback(payload)
            except Exception:
                with self._lock:
                    if self._callback_errors == MAX_COUNTER:
                        self._counter_saturated = True
                    else:
                        self._callback_errors += 1

    def _run_rss(self):
        while not self._stop.is_set():
            try:
                sample = self._provider()
                if type(sample) is not ResourceReading:
                    raise ValueError('ResourceReading required')
            except Exception:
                sample = ResourceReading(time.monotonic_ns(), None, 0, read_errors=1)
            # A late response after close is discarded; pending close remains truthful.
            if self._stop.is_set():
                break
            with self._lock:
                state = self._rss
                self._add(state, 'samples')
                for name in ('missing_processes','read_errors','identity_changes'):
                    self._add(state, name, getattr(sample, name))
                self._add(state, 'truncated_samples', int(sample.scope_truncated))
                previous = state['last_sample_ns']
                valid = (sample.rss_bytes is not None and not sample.missing_processes and
                         not sample.read_errors and not sample.identity_changes and not sample.scope_truncated)
                if previous is not None and sample.sampled_at_ns < previous:
                    self._add(state, 'read_errors')
                    valid = False
                else:
                    if previous is not None:
                        gap = sample.sampled_at_ns-previous
                        state['max_sample_gap_ns'] = max(state['max_sample_gap_ns'] or 0, gap)
                    state['last_sample_ns'] = sample.sampled_at_ns
                    if state['first_sample_ns'] is None:
                        state['first_sample_ns'] = sample.sampled_at_ns
                value = sample.rss_bytes if valid else None
                if valid:
                    self._add(state, 'support')
                    state['sampled_peak_bytes'] = max(state['sampled_peak_bytes'] or 0, value)
            self._check_cap('rss', value)
            self._stop.wait(self.interval_s)

    def _run_gpu(self):
        while not self._stop.is_set():
            started = time.monotonic_ns()
            deadline = started+int(self.gpu_timeout_s*1e9)
            try:
                sample = self._gpu_provider(deadline)
                if type(sample) is not GpuReading:
                    raise ValueError('GpuReading required')
                error = False
            except Exception:
                sample = GpuReading(None, 'provider_error')
                error = True
            finished = time.monotonic_ns()
            if self._stop.is_set():
                break
            late = finished > deadline
            with self._lock:
                state = self._gpu
                self._add(state, 'samples')
                self._add(state, 'errors', int(error))
                self._add(state, 'timeouts', int(late))
                value = None if late else sample.used_bytes
                if value is not None:
                    self._add(state, 'support')
                    state['sampled_peak_bytes'] = max(state['sampled_peak_bytes'] or 0, value)
                    state['unavailable_reason'] = None
                else:
                    state['unavailable_reason'] = 'provider_timeout' if late else sample.unavailable_reason
            self._check_cap('gpu', value)
            self._stop.wait(self.gpu_interval_s)

    def provider_diagnostics(self):
        # Only built-in providers own this contract. Never invoke arbitrary
        # injected-provider callbacks while taking a sampler snapshot.
        rss = self._provider.diagnostics() if type(self._provider) is ProcTreeProvider else None
        from .gpu_provider import NvidiaSmiProvider
        gpu = self._gpu_provider.diagnostics() if type(self._gpu_provider) is NvidiaSmiProvider else None
        return dict(schema_version=1, rss=rss, gpu=gpu)

    def snapshot(self):
        with self._lock:
            pending = [name for name, thread in self._threads.items() if thread.is_alive()]
            rss = dict(self._rss)
            gpu = dict(self._gpu)
            complete = (self._closed and not pending and rss['samples'] > 0 and
                        rss['support'] == rss['samples'] and not self._breached and
                        not self._callback_errors and not self._counter_saturated and
                        (self._gpu_provider is None or gpu['support'] == gpu['samples'] > 0))
            return dict(schema_version='runtime_resource_samples_v1', scope='provider_root_and_descendants',
                        scope_proof=dict(self._scope_proof), counter_saturated=self._counter_saturated,
                        start_requested_monotonic_ns=self._start_requested_ns,
                        stop_requested_monotonic_ns=self._stop_requested_ns,
                        shutdown_observed_monotonic_ns=self._shutdown_observed_ns,
                        rss=rss, gpu=gpu, interval_s=self.interval_s,
                        gpu_interval_s=self.gpu_interval_s, gpu_timeout_s=self.gpu_timeout_s,
                        worker_pending=bool(pending), pending_workers=pending,
                        complete=bool(complete), cap_breached=bool(self._breached),
                        breached_resources=sorted(self._breached), callback_errors=self._callback_errors,
                        boundedness_certified=False,
                        limitation='sampled peaks; allocations between samples may exceed caps; no absolute peak proof')

    def close(self, *, timeout_s=.5):
        if type(timeout_s) not in (int,float) or not math.isfinite(timeout_s) or not 0 <= timeout_s <= 60:
            raise ValueError('timeout_s must be finite and in [0, 60]')
        deadline = time.monotonic()+timeout_s
        with self._lock:
            self._closed = True
            if self._stop_requested_ns is None:
                self._stop_requested_ns = time.monotonic_ns()
            self._stop.set()
            threads = tuple(self._threads.values())
        for thread in threads:
            # Callbacks may request shutdown from their own sampler thread.
            from threading import current_thread
            if thread is not current_thread():
                thread.join(max(0., deadline-time.monotonic()))
        with self._lock:
            if self._shutdown_observed_ns is None and not any(thread.is_alive() for thread in threads):
                self._shutdown_observed_ns = time.monotonic_ns()
        return self.snapshot()
