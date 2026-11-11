"""Optional warmed, exact maintenance of rolling evidence; NumPy fallback owned by rolling."""
from __future__ import annotations
import numpy as np
try:
    from numba import njit
except ImportError:
    njit=None


def _maintain(p,h,f,ps,hs,fs,row0,col0,minr,minc,endr,endc,now,ttl):
    ep=eh=ef=dp=dh=df=0
    for r in range(p.shape[0]):
        for c in range(p.shape[1]):
            outside=(row0+r<minr or row0+r>=endr or col0+c<minc or col0+c>=endc)
            if ps[r,c]>=0 and now-ps[r,c]>=ttl:
                ep+=1;p[r,c]=np.nan;ps[r,c]=-1
            if fs[r,c]>=0 and now-fs[r,c]>=ttl:
                ef+=1;f[r,c]=False;fs[r,c]=-1
            if outside:
                dp+=int(not np.isnan(p[r,c]));df+=int(f[r,c])
                p[r,c]=np.nan;f[r,c]=False;ps[r,c]=-1;fs[r,c]=-1
            for b in range(h.shape[2]):
                if hs[r,c,b]>=0 and now-hs[r,c,b]>=ttl:
                    eh+=1;h[r,c,b]=np.nan;hs[r,c,b]=-1
                if outside:
                    dh+=int(not np.isnan(h[r,c,b]))
                    h[r,c,b]=np.nan;hs[r,c,b]=-1
    return ep,eh,ef,dp,dh,df


_dispatcher=None if njit is None else njit(cache=True,nogil=True)(_maintain)
_entry=None


def warmup_maintenance_kernel():
    """Compile exactly the contiguous tile layout before capture/timing."""
    global _entry
    if _dispatcher is None:return False
    if _entry is not None:return True
    p=np.full((1,1),np.nan,np.float32);h=p.reshape(1,1,1).copy();f=np.zeros((1,1),bool)
    ps=np.full((1,1),-1,np.int64);hs=ps.reshape(1,1,1).copy();fs=ps.copy()
    _dispatcher(p,h,f,ps,hs,fs,0,0,0,0,1,1,0,1)
    signature=_dispatcher.signatures[0]
    _entry=_dispatcher.overloads[signature].entry_point
    return True


def apply_maintenance(tile,key,size,window,now_ns,retention_ns):
    """Return None without mutation for unwarmed/unsupported layouts; never JIT here."""
    if _entry is None:return None
    arrays=(tile.planar_log_odds,tile.height_log_odds,tile.floor_support,
            tile.planar_last_ns,tile.height_last_ns,tile.floor_last_ns)
    dtypes=(np.float32,np.float32,np.bool_,np.int64,np.int64,np.int64)
    shape=(size,size)
    for i,(a,dtype) in enumerate(zip(arrays,dtypes)):
        if (not isinstance(a,np.ndarray) or a.dtype!=dtype or not a.flags.c_contiguous
                or not a.flags.writeable):return None
        if a.shape!=(shape+(tile.height_log_odds.shape[2],) if i in (1,4) else shape):return None
    scalars=(key[0]*size,key[1]*size,window.min_row,window.min_col,window.end_row,
             window.end_col,now_ns,retention_ns)
    if any(type(x) is not int or not -(1<<63)<=x<(1<<63) for x in scalars):return None
    return _entry(*arrays,*scalars)
