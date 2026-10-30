"""Small dependency-free polygon operations for M8 simple rings."""
from __future__ import annotations
import math
import struct
from functools import lru_cache
from typing import Sequence
from ._types import Point2, Polygon2D, Ring2D, ring_area

_EPS=1e-10

def _cross(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def _on_segment(p,a,b,eps=_EPS):
    return abs(_cross(a,b,p))<=eps and min(a[0],b[0])-eps<=p[0]<=max(a[0],b[0])+eps and min(a[1],b[1])-eps<=p[1]<=max(a[1],b[1])+eps

def ring_covers(point: Point2, ring: Ring2D) -> bool:
    inside=False; x,y=point
    for i,a in enumerate(ring):
        b=ring[(i+1)%len(ring)]
        if _on_segment(point,a,b): return True
        if (a[1]>y)!=(b[1]>y) and x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]: inside=not inside
    return inside

def point_in_polygon(point: Point2, polygon: Polygon2D) -> bool:
    if not ring_covers(point,polygon.outer): return False
    # Covers includes ring boundary; strict hole interiors are excluded.
    for hole in polygon.holes:
        if ring_covers(point,hole) and not any(_on_segment(point,hole[i],hole[(i+1)%len(hole)]) for i in range(len(hole))):
            return False
    return True

def _distance_segment(p,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]; den=dx*dx+dy*dy
    if den==0:return math.dist(p,a)
    t=max(0.0,min(1.0,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/den))
    return math.hypot(p[0]-(a[0]+t*dx),p[1]-(a[1]+t*dy))

def distance_to_polygon(point,polygon):
    if point_in_polygon(point,polygon): return 0.0
    return min(_distance_segment(point,ring[i],ring[(i+1)%len(ring)]) for ring in (polygon.outer,*polygon.holes) for i in range(len(ring)))

def _triangulate(ring):
    """Source ear clipping without cross-publication geometry retention."""
    points=list(ring)
    if len(points)>1 and points[0]==points[-1]: points.pop()
    if len(points)<3:return []
    indices=list(range(len(points)))
    if sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points)))<0: indices.reverse()
    tris=[]; guard=0
    while len(indices)>3 and guard<len(points)*len(points):
        guard+=1; found=False
        for j,cur in enumerate(indices):
            prev=indices[j-1]; nxt=indices[(j+1)%len(indices)]
            a,b,c=points[prev],points[cur],points[nxt]
            if _cross(a,b,c)<=_EPS: continue
            if any(_point_in_triangle(points[k],a,b,c) for k in indices if k not in (prev,cur,nxt)): continue
            tris.append((a,b,c)); indices.pop(j); found=True; break
        if not found: return []
    if len(indices)==3: tris.append(tuple(points[i] for i in indices))
    return tuple(tris)

def _point_in_triangle(p,a,b,c):
    return _cross(a,b,p)>=-_EPS and _cross(b,c,p)>=-_EPS and _cross(c,a,p)>=-_EPS

def _clip_convex(subject,clip):
    out=list(subject)
    for i,a in enumerate(clip):
        b=clip[(i+1)%len(clip)]; inp=out; out=[]
        if not inp: break
        prev=inp[-1]
        for cur in inp:
            cin=_cross(a,b,cur)>=-_EPS; pin=_cross(a,b,prev)>=-_EPS
            if cin:
                if not pin: out.append(_intersection(prev,cur,a,b))
                out.append(cur)
            elif pin: out.append(_intersection(prev,cur,a,b))
            prev=cur
    return out

def _intersection(p1,p2,q1,q2):
    x1,y1=p1; x2,y2=p2; x3,y3=q1; x4,y4=q2
    den=(x1-x2)*(y3-y4)-(y1-y2)*(x3-x4)
    if abs(den)<_EPS:return p2
    det1=x1*y2-y1*x2; det2=x3*y4-y3*x4
    return ((det1*(x3-x4)-(x1-x2)*det2)/den,(det1*(y3-y4)-(y1-y2)*det2)/den)

def _ring_intersection_area_uncached(a,b):
    total=0.0
    triangles_a,triangles_b=_triangulate(a),_triangulate(b)
    for ta in triangles_a:
        for tb in triangles_b:
            clipped=_clip_convex(ta,tb)
            if len(clipped)>=3: total+=ring_area(tuple(clipped))
    return total

def _ring_key(ring):
    # Exact float bytes preserve signed zero. Only bounded ordinary finite
    # coordinates enter this pure geometry cache; no source IDs or verdicts
    # about map freshness, lineage or membership are retained.
    if not isinstance(ring,(tuple,list)) or len(ring)>MAX_RING_VERTICES:return None
    if any(not isinstance(p,(tuple,list)) or len(p)!=2 or
           any(type(v) is not float or not math.isfinite(v) for v in p) for p in ring):return None
    return struct.pack('!'+str(2*len(ring))+'d',*(v for p in ring for v in p))

def _key_ring(key):return tuple(struct.iter_unpack('!dd',key))

@lru_cache(maxsize=64)
def _cached_ring_intersection_area(a,b):
    return _ring_intersection_area_uncached(_key_ring(a),_key_ring(b))

def _ring_intersection_area(a,b):
    ka,kb=_ring_key(a),_ring_key(b)
    if ka is None or kb is None:return _ring_intersection_area_uncached(a,b)
    return _cached_ring_intersection_area(ka,kb)

def intersection_area(a: Polygon2D,b: Polygon2D):
    value=_ring_intersection_area(a.outer,b.outer)
    for hole in a.holes: value-=_ring_intersection_area(hole,b.outer)
    for hole in b.holes: value-=_ring_intersection_area(a.outer,hole)
    for ha in a.holes:
        for hb in b.holes: value+=_ring_intersection_area(ha,hb)
    return max(0.0,value)

def polygon_area(p): return max(0.0,ring_area(p.outer)-sum(ring_area(h) for h in p.holes))

def covers_bounds(p,bounds):
    x0,y0,x1,y1=bounds
    return any(point_in_polygon(pt,p) for pt in ((x0,y0),(x1,y0),(x1,y1),(x0,y1))) or any(x0<=x<=x1 and y0<=y<=y1 for x,y in p.outer)


# Shared fail-closed simple-ring predicate for wire, owner and membership.
# Includes an optional repeated closing vertex; reject before quadratic work.
MAX_RING_VERTICES=1024
def _segments_intersect(a,b,c,d,eps=1e-9):
    def orient(p,q,r):return (q[0]-p[0])*(r[1]-p[1])-(q[1]-p[1])*(r[0]-p[0])
    def on(p,q,r):return min(p[0],q[0])-eps<=r[0]<=max(p[0],q[0])+eps and min(p[1],q[1])-eps<=r[1]<=max(p[1],q[1])+eps and abs(orient(p,q,r))<=eps
    o1,o2,o3,o4=orient(a,b,c),orient(a,b,d),orient(c,d,a),orient(c,d,b)
    return (((o1>eps and o2 < -eps) or (o1 < -eps and o2>eps)) and ((o3>eps and o4 < -eps) or (o3 < -eps and o4>eps))) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b)


def valid_ring(ring):
    try:
        if len(ring)>MAX_RING_VERTICES:return False
    except TypeError:
        return False
    try:
        normalized=tuple(tuple(float(v) for v in point) for point in ring)
    except (TypeError,ValueError,OverflowError):
        return False
    if any(len(point)!=2 or not all(math.isfinite(v) for v in point) for point in normalized):return False
    return _cached_valid_ring(_ring_key(normalized))

@lru_cache(maxsize=64)
def _cached_valid_ring(key):
    return _valid_ring(_key_ring(key))


def _valid_ring(ring):
    """Simple nonzero ring, with a complete triangulation (fail closed)."""
    ring=tuple(map(tuple,ring))
    if len(ring)>1 and ring[0]==ring[-1]:ring=ring[:-1]
    if len(ring)<3 or any(a==ring[(i+1)%len(ring)] for i,a in enumerate(ring)):return False
    for i,b in enumerate(ring):
        a,c=ring[i-1],ring[(i+1)%len(ring)]
        # Adjacent collinear edges may continue straight, but cannot retrace.
        if abs(_cross(a,b,c))<=1e-9 and (b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1])<0:return False
    for i,a in enumerate(ring):
        for j in range(i+1,len(ring)):
            if j==i+1 or (i==0 and j==len(ring)-1):continue
            if _segments_intersect(a,ring[(i+1)%len(ring)],ring[j],ring[(j+1)%len(ring)]):return False
    tris=_triangulate(ring)
    return bool(tris) and ring_area(ring)>1e-12 and abs(sum(ring_area(t) for t in tris)-ring_area(ring))<1e-7



def room_center(polygon):
    """Area centroid, with a bounded interior-clearance anchor for concave rings.

    This is a presentation anchor for accepted geometry, not semantic room truth
    or a navigable robot pose. No cross-revision geometry is retained.
    """
    import heapq
    import numpy as np
    values=np.asarray(polygon,dtype=float)
    if values.ndim!=2 or values.shape[1]!=2 or not 3<=len(values)<=MAX_RING_VERTICES or not np.isfinite(values).all():
        raise ValueError('valid bounded room polygon required')
    ring=tuple(map(tuple,values))
    if not valid_ring(ring):raise ValueError('simple nonzero room polygon required')
    return _cached_room_center(ring)


@lru_cache(maxsize=64)
def _cached_room_center(ring):
    # Pure exact geometry cache, never source/revision/membership freshness.
    import heapq
    import numpy as np
    values=np.asarray(ring,dtype=float)
    # Translation reduces loss of precision for large world origins.
    base=values[0];p=values-base;nxt=np.roll(p,-1,axis=0)
    cross=p[:,0]*nxt[:,1]-nxt[:,0]*p[:,1]
    center=((p+nxt)*cross[:,None]).sum(axis=0)/(3*cross.sum())+base
    candidate=tuple(map(float,center))
    if ring_covers(candidate,ring) and min(_distance_segment(candidate,a,ring[(i+1)%len(ring)]) for i,a in enumerate(ring))>1e-9:
        return candidate
    low=values.min(axis=0);high=values.max(axis=0);width,height=high-low
    size=max(min(width,height),max(width,height)/32)
    if not math.isfinite(size) or size<=0:raise ValueError('nonzero room extent required')
    def distance(x,y):
        point=(x,y)
        d=min(_distance_segment(point,a,ring[(i+1)%len(ring)]) for i,a in enumerate(ring))
        return d if ring_covers(point,ring) else -d
    heap=[];serial=0
    def push(x,y,half):
        nonlocal serial
        d=distance(x,y);serial+=1
        heapq.heappush(heap,(-(d+half*math.sqrt(2)),serial,x,y,half,d))
    # Triangulation supplies a certified interior seed even in a very thin arm.
    triangles=_triangulate(ring)
    if not triangles:raise ValueError('room interior cannot be established')
    seeds=[tuple(sum(t[i][axis] for i in range(3))/3 for axis in range(2)) for t in triangles]
    best=max(((distance(*point),point) for point in seeds),key=lambda item:(item[0],-item[1][0],-item[1][1]))
    for x in np.arange(low[0],high[0],size):
        for y in np.arange(low[1],high[1],size):push(float(x+size/2),float(y+size/2),float(size/2))
    tolerance=max(.01,max(width,height)*1e-5)
    for _ in range(4096):
        if not heap:break
        bound,_,x,y,half,d=heapq.heappop(heap)
        if d>best[0]:best=(d,(x,y))
        if -bound-best[0]<=tolerance:continue
        half/=2
        for dx,dy in ((-1,-1),(-1,1),(1,-1),(1,1)):push(x+dx*half,y+dy*half,half)
    if best[0]<=0:raise ValueError('room interior cannot be established')
    return best[1]


def normalize_room_ring(polygon):
    """Remove exact zero-area consecutive collinear/duplicate wire vertices.

    No rounding, hull, buffer or arbitrary intersection repair. The resulting
    ring must still pass the unchanged simple-ring validator before publication.
    """
    try:ring=tuple(tuple(float(v) for v in point) for point in polygon)
    except (ValueError,TypeError,OverflowError) as exc:raise ValueError('invalid room ring') from exc
    if not 3<=len(ring)<=MAX_RING_VERTICES or any(len(p)!=2 or not all(math.isfinite(v) for v in p) for p in ring):
        raise ValueError('invalid bounded finite room ring')
    points=list(ring)
    if len(points)>3 and points[-1]==points[0]:points.pop()
    while len(points)>3:
        changed=False
        for i,b in enumerate(points):
            a=points[i-1];c=points[(i+1)%len(points)]
            if b==a or b==c or _cross(a,b,c)==0.:
                points.pop(i);changed=True;break
        if not changed:break
    return tuple(points),len(ring)-len(points)
