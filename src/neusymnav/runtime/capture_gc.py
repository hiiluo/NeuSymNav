"""Optional cyclic-GC scheduling outside one fresh capture/control transaction.

Reference counting remains active. Automatic cyclic GC is restored after the
synchronous actuator returns, including every exception/continue path. Hydra
only: legacy association's independent GC decorator cannot share this scope.
"""
import gc
import time


class CaptureGCWindow:
    def __init__(self,enabled,*,collector=gc,now_ns=time.monotonic_ns):
        if type(enabled) is not bool:raise ValueError('GC window enabled must be boolean')
        self.enabled=enabled;self.collector=collector;self.now_ns=now_ns
        self._active=False;self._restore=False;self._last=None
        self._windows=0;self._collections=0;self._events=[];self._dropped=0
        self._total_ns=0;self._max_ns=0

    def __enter__(self):
        if self._active:raise RuntimeError('GC capture window is already active')
        self._restore=False
        if self.enabled and self.collector.isenabled():
            now=self.now_ns()
            if self._last is None or now-self._last>=1_000_000_000:
                # No new control capture exists yet. This pause can consume run
                # time, but cannot renew an old source or eat the new source TTL.
                self.collector.collect(2)
                end=self.now_ns();elapsed=max(0,end-now)
                self._last=end;self._collections+=1;self._total_ns+=elapsed
                self._max_ns=max(self._max_ns,elapsed)
                if len(self._events)<1024:self._events.append((now,end))
                else:self._dropped+=1
            self.collector.disable();self._restore=True
        self._active=True;self._windows+=1
        return self

    def __exit__(self,*exc):
        try:
            if self._restore:self.collector.enable()
        finally:self._active=False;self._restore=False
        return False

    def snapshot(self):
        return dict(enabled=self.enabled,policy='cyclic_gc_before_capture_v1',
            period_ns=1_000_000_000,windows=self._windows,collections=self._collections,
            collection_total_ns=self._total_ns,collection_max_ns=self._max_ns,
            events=list(self._events),events_dropped=self._dropped,
            limitation='process-wide cyclic GC only; refcount/descheduling/explicit child GC unaffected')
