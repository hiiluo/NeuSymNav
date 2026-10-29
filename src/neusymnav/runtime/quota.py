"""Run-wide conservative disk reservations, including temporary/WAL files."""
import os
from pathlib import Path
import stat
from threading import RLock


class QuotaExceeded(RuntimeError): pass


class RunQuota:
    def __init__(self,root,*,raw_cap=2*1024**3,total_cap=8*1024**3):
        if any(type(v) is not int or v<=0 for v in (raw_cap,total_cap)) or raw_cap>total_cap:
            raise ValueError('invalid disk caps')
        self.root=Path(os.path.abspath(root));self.raw_root=self.root/'keyframes';self.raw_cap=raw_cap;self.total_cap=total_cap
        self.lock=RLock();self.reservations={};self._covers={};self.peak_total=0;self.peak_raw=0
        self._publish_metrics()

    def _publish_metrics(self):
        # Replaced as one immutable-by-convention reference by the reservation
        # owner. Readers never join a potentially slow filesystem scan.
        self._metrics=dict(raw_cap=self.raw_cap,total_cap=self.total_cap,
            reserved_total=sum(v[0] for v in self.reservations.values()),
            peak_total=self.peak_total,peak_raw=self.peak_raw)

    @staticmethod
    def tree_bytes(root,*,excluded=()):
        # Includes staging, SQLite -wal/-shm, recorder manifests, archives, refs.
        # Prune before scandir enters a covered directory: a long archive must
        # not add one stat/enumeration operation per payload to every admission.
        root=Path(root);excluded=set(excluded);total=0
        try:root_stat=root.lstat()
        except FileNotFoundError:return 0
        if stat.S_ISLNK(root_stat.st_mode):raise ValueError('run quota cannot follow symlinks')
        if root in excluded:return 0
        def scan_error(error):raise error
        for directory,dirs,files in os.walk(root,topdown=True,followlinks=False,onerror=scan_error):
            directory_names=set(dirs)
            for name in dirs[:]+files:
                path=Path(directory)/name
                try:entry=path.lstat()
                except FileNotFoundError:continue
                if stat.S_ISLNK(entry.st_mode):raise ValueError('run quota cannot follow symlinks')
                if name in directory_names and path in excluded:dirs.remove(name)
                elif stat.S_ISREG(entry.st_mode):total+=entry.st_size
        return total

    def _cover_identity(self,path):
        # Do not resolve away a symlink in either the cover or its ancestors.
        for component in (path,*path.parents):
            try:entry=component.lstat()
            except FileNotFoundError:raise ValueError('covered path must be an existing directory') from None
            if stat.S_ISLNK(entry.st_mode):raise ValueError('run quota cannot follow symlinks')
            if not stat.S_ISDIR(entry.st_mode):raise ValueError('covered path must be a directory')
            if component==path:identity=(entry.st_dev,entry.st_ino)
        return identity

    def reserve(self,key,total_bytes,raw_bytes=0,*,covered_path=None):
        """Reserve pending bytes, or charge a fixed independently bounded subtree.

        A cover is an exclusive directory owned by a writer which enforces its
        own total disk bound (including staging/metadata) and forbids symlinks.
        Its entire reservation stays charged while payloads are not rescanned.
        The directory and reservation cannot change until explicit release;
        callers must stop the writer before release. Raw covers charge the full
        bound to raw as well as total. Uncovered disk is always scanned afresh.
        Disk scans belong on worker lanes; submit only checks cached queue caps.
        """
        with self.lock:
            if any(type(v) is not int or v<0 for v in (total_bytes,raw_bytes)) or raw_bytes>total_bytes:
                raise ValueError('invalid disk reservation')
            cover=None if covered_path is None else Path(os.path.abspath(covered_path))
            existing=self._covers.get(key)
            if existing is not None and (cover!=existing[0] or self.reservations[key]!=(total_bytes,raw_bytes)):
                raise ValueError('covered reservation is fixed until release')
            for path,identity in self._covers.values():
                if self._cover_identity(path)!=identity:raise ValueError('covered directory identity changed')
            new_cover=cover is not None and existing is None
            if new_cover:
                if key in self.reservations:raise ValueError('release existing reservation before adding a cover')
                if cover==self.root or not cover.is_relative_to(self.root):raise ValueError('covered path must be inside run')
                if self.raw_root.is_relative_to(cover) and cover!=self.raw_root:
                    raise ValueError('cover cannot contain the raw root')
                expected_raw=total_bytes if cover.is_relative_to(self.raw_root) else 0
                if total_bytes<=0 or raw_bytes!=expected_raw:raise ValueError('covered reservation must fully charge its disk category')
                if any(cover.is_relative_to(path) or path.is_relative_to(cover) for path,_ in self._covers.values()):
                    raise ValueError('covered paths overlap')
                identity=self._cover_identity(cover)
                if self.tree_bytes(cover)>total_bytes:raise QuotaExceeded('existing covered payload exceeds reservation')
            excluded=tuple(path for path,_ in self._covers.values())+((cover,) if new_cover else ())
            total=self.tree_bytes(self.root,excluded=excluded) if excluded else self.tree_bytes(self.root)
            raw=self.tree_bytes(self.raw_root,excluded=excluded) if excluded else self.tree_bytes(self.raw_root)
            other=[v for k,v in self.reservations.items() if k!=key]
            if total+sum(v[0] for v in other)+total_bytes>self.total_cap or raw+sum(v[1] for v in other)+raw_bytes>self.raw_cap:
                raise QuotaExceeded('run_disk_quota; accepted evidence retained for replay')
            self.reservations[key]=(total_bytes,raw_bytes)
            if new_cover:self._covers[key]=(cover,identity)
            self.peak_total=max(self.peak_total,total+sum(v[0] for v in self.reservations.values()))
            self.peak_raw=max(self.peak_raw,raw+sum(v[1] for v in self.reservations.values()))
            self._publish_metrics()

    def release(self,key):
        with self.lock:
            self.reservations.pop(key,None);self._covers.pop(key,None);self._publish_metrics()

    def snapshot(self):
        return dict(self._metrics)
