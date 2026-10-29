"""Immutable content-addressed evidence, durable before any SQLite reference."""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
import re
import tempfile


class AssetStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, ref):
        if not isinstance(ref, str) or not re.fullmatch(r'[0-9a-f]{64}', ref):
            raise ValueError('asset reference must be a sha256 digest')
        return self.root / ref

    def _sync_directory(self):
        directory_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def put(self, data: bytes):
        ref = hashlib.sha256(data).hexdigest()
        path = self.path(ref)
        if path.exists():
            if self.read(ref) != data:
                raise ValueError('asset checksum conflict')
            # A previous writer may have died after atomic publication but
            # before syncing the directory. Visibility alone is insufficient.
            self._sync_directory()
            return ref
        # A killed writer may leave this unreferenced staging file. It must
        # never leave a partial file under the digest name used by retries.
        fd, temporary = tempfile.mkstemp(prefix='.staged-', dir=self.root)
        temporary = Path(temporary)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                # Atomic no-replace publication: an existing accepted asset
                # is verified, never overwritten to conceal corruption.
                os.link(temporary, path)
            except FileExistsError:
                if self.read(ref) != data:
                    raise ValueError('asset checksum conflict')
            temporary.unlink()
            self._sync_directory()
        finally:
            temporary.unlink(missing_ok=True)
        return ref

    def read(self, ref):
        data = self.path(ref).read_bytes()
        if hashlib.sha256(data).hexdigest() != ref:
            raise ValueError(f'asset checksum mismatch: {ref}')
        return data
