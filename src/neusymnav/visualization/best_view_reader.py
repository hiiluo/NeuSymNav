"""Read one selected object's committed crop in the UI process, never control."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import numpy as np
from ..contracts import FrameKey
from .publisher import DisplayImage, MAX_IMAGE_BYTES


class SelectedBestViewReader:
    def __init__(self, assets_root, *, clock_domain):
        self.root=Path(assets_root)
        self.domain=clock_domain
        self._key=None
        self._image=None  # one bounded crop, independent of graph object count

    def _pixels(self, ref):
        if not isinstance(ref,str) or len(ref)!=64 or any(c not in '0123456789abcdef' for c in ref):
            raise ValueError('invalid crop asset reference')
        path=self.root/ref
        if path.is_symlink() or path.stat().st_size>MAX_IMAGE_BYTES+65536:
            raise ValueError('invalid crop asset size/path')
        payload=path.read_bytes()
        if len(payload)>MAX_IMAGE_BYTES+65536 or hashlib.sha256(payload).hexdigest()!=ref:
            raise ValueError('crop checksum/size mismatch')
        stream=io.BytesIO(payload);version=np.lib.format.read_magic(stream)
        if version==(1,0):shape,fortran,dtype=np.lib.format.read_array_header_1_0(stream)
        elif version==(2,0):shape,fortran,dtype=np.lib.format.read_array_header_2_0(stream)
        else:raise ValueError('unsupported crop array format')
        if (dtype!=np.dtype('uint8') or len(shape)!=3 or shape[2]!=3
                or any(n<=0 for n in shape) or shape[0]*shape[1]*3>MAX_IMAGE_BYTES
                or len(payload)-stream.tell()!=shape[0]*shape[1]*3):
            raise ValueError('bounded RGB crop required')
        return np.frombuffer(payload,dtype=np.uint8,offset=stream.tell()).reshape(shape,order='F' if fortran else 'C')

    def read(self, envelope, object_id):
        sources=envelope.sources;objects=sources.objects;verification=sources.verification
        if objects is None or verification is None or envelope.clock_domain!=self.domain:return None
        try:
            canonical=objects.resolve_id(object_id)
            record=verification.objects[canonical]
            if (verification.episode_id!=objects.episode_id or verification.object_revision!=objects.revision
                    or record.episode_id!=objects.episode_id):return None
            key=(objects.episode_id,objects.revision,canonical,record.evidence)
            if key==self._key:return self._image
            database=self.root.parent/'objects.sqlite3'
            if not database.exists():return None
            with sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=.05) as conn:
                for proof in record.evidence:
                    if (proof.clock_domain!=self.domain or proof.source.episode_id!=objects.episode_id
                            or proof.evidence_ref not in objects.objects[canonical].evidence_refs):continue
                    row=conn.execute("SELECT object_id,crop_asset,data FROM views WHERE event_id=? AND length(data)<=65536 LIMIT 1",(proof.evidence_ref,)).fetchone()
                    if row is None:continue
                    try:
                        owner,ref,data=row;data=json.loads(data)
                        if (objects.resolve_id(owner)!=canonical or data['evidence_kind']!='detected'
                                or FrameKey(**data['source'])!=proof.source
                                or data['object_revision']!=proof.object_revision
                                or proof.object_revision>objects.revision
                                or data['capture_monotonic_ns']!=proof.capture_monotonic_ns
                                or data['clock_domain']!=proof.clock_domain):continue
                        image=DisplayImage('best_view',proof.source,proof.capture_monotonic_ns,
                            proof.clock_domain,self._pixels(ref),canonical,objects.revision,proof.evidence_ref)
                    except (OSError,ValueError,KeyError,TypeError):continue
                    self._key=key;self._image=image
                    return image
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error):return None
        return None
