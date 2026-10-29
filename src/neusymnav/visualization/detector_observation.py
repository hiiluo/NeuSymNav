"""Read-only bounded display projection from already committed detector assets.

Runs on the graph publication lane. No inference, sensor call, or control wait.
"""
import hashlib
from pathlib import Path
import sqlite3

from ..contracts.serialization import loads
from ..contracts.observations import validate_detection_batch
from .publisher import DisplayImage, DisplayInstance, DisplayObservation, MAX_IMAGE_BYTES


class CommittedObservationReader:
    def __init__(self, assets_root, *, clock_domain):
        self.root=Path(assets_root)
        self.domain=clock_domain
        self._cached=None
        self._refs=None

    def _asset(self, ref):
        if not isinstance(ref,str) or len(ref)!=64 or any(c not in '0123456789abcdef' for c in ref):
            raise ValueError('invalid display asset reference')
        path=self.root/ref
        if path.is_symlink() or path.stat().st_size>64*1024**2:
            raise ValueError('display asset exceeds byte bound or is a symlink')
        payload=path.read_bytes()
        if hashlib.sha256(payload).hexdigest()!=ref:
            raise ValueError('display asset checksum mismatch')
        return loads(payload.decode())

    def read(self, processed_source):
        if processed_source is None:return None
        database=self.root.parent/'objects.sqlite3'
        if not database.exists():return None
        with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05) as conn:
            row=conn.execute('SELECT source_asset,batch_asset FROM batches ORDER BY rowid DESC LIMIT 1').fetchone()
        if row is None:return None
        if row==self._refs:
            value=self._cached
            return value if value.image.source==processed_source else None
        obs=self._asset(row[0]);batch=self._asset(row[1])
        validate_detection_batch(obs,batch)
        if obs.key!=processed_source or obs.clock_domain!=self.domain:return None
        image=DisplayImage('rgb',obs.key,obs.capture_monotonic_ns,obs.clock_domain,obs.rgb)
        items=[];used=0
        for detection in batch.detections:
            if len(items)>=64 or used+detection.mask.nbytes>MAX_IMAGE_BYTES:break
            items.append(DisplayInstance(detection.detection_id[:256],detection.raw_label[:256],detection.score,detection.mask))
            used+=detection.mask.nbytes
        value=DisplayObservation(image,tuple(items),len(batch.detections),batch.completion,batch.cap_reached)
        self._refs=row;self._cached=value
        return value
