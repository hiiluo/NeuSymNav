"""Bounded, immutable display-only history of measured occupancy."""
from dataclasses import dataclass
import math
from types import MappingProxyType
import numpy as np
from ..contracts import NavSnapshot


def _immutable(array):
    array=np.ascontiguousarray(array, dtype=np.int8)
    return np.frombuffer(array.tobytes(),dtype=np.int8).reshape(array.shape)


@dataclass(frozen=True)
class MapOverview:
    source_nav: NavSnapshot
    origin_xy: tuple[float,float]
    resolution_m: float
    states: np.ndarray
    complete: bool = True
    policy: str = 'measured_occupancy_overview_v1'

    def __post_init__(self):
        if not isinstance(self.source_nav,NavSnapshot): raise ValueError('source NavSnapshot required')
        if (len(self.origin_xy)!=2 or not all(math.isfinite(x) for x in self.origin_xy)
                or not math.isfinite(self.resolution_m) or self.resolution_m<=0): raise ValueError('invalid geometry')
        ratio=self.resolution_m/self.source_nav.resolution_m
        if ratio<1 or not math.isclose(ratio,round(ratio),rel_tol=1e-10): raise ValueError('unaligned resolution')
        if any(not math.isclose((v-base)/self.source_nav.resolution_m,round((v-base)/self.source_nav.resolution_m),abs_tol=1e-6)
               for v,base in zip(self.origin_xy,self.source_nav.origin_xy)): raise ValueError('unaligned origin')
        if not isinstance(self.states,np.ndarray) or self.states.ndim!=2 or not self.states.size or self.states.size>1_000_000 or self.states.dtype!=np.int8 or not np.isin(self.states,[-1,0,100]).all(): raise ValueError('invalid states')
        if type(self.complete) is not bool or self.policy!='measured_occupancy_overview_v1': raise ValueError('invalid overview metadata')
        object.__setattr__(self,'origin_xy',tuple(self.origin_xy))
        object.__setattr__(self,'states',_immutable(self.states))


@dataclass(frozen=True)
class OverviewTiles:
    source_nav: NavSnapshot
    origin_xy: tuple[float,float]
    resolution_m: float
    tile_size: int
    tiles: object
    complete: bool = True


def update_tiles(previous, nav, grid, cells, free_threshold, occupied_threshold, *, max_tiles=4096):
    """Apply every dirty canonical cell, preserving previous immutable tiles."""
    size=grid.tile_size_cells
    max_tiles=min(max_tiles, (16*1024*1024)//(size*size))
    tiles={} if previous is None else dict(previous.tiles)
    complete=True if previous is None else previous.complete
    rows,cols=cells.rows,cells.cols
    planar,height=cells.planar_log_odds,cells.height_log_odds
    occupied=(planar>=occupied_threshold)|np.any(height[:,1:]>=occupied_threshold,axis=1)
    free=(planar<=free_threshold)&np.all(height[:,1:]<=free_threshold,axis=1)&cells.floor_supported&~occupied
    values=np.full(len(rows),-1,np.int8); values[free]=0; values[occupied]=100
    keys=np.column_stack((rows//size,cols//size))
    if len(keys):
        order=np.lexsort((keys[:,1],keys[:,0]))
        sorted_keys=keys[order]
        starts=np.r_[0, np.flatnonzero(np.any(sorted_keys[1:]!=sorted_keys[:-1],axis=1))+1]
        ends=np.r_[starts[1:],len(order)]
        for start,end in zip(starts,ends):
            tr,tc=sorted_keys[start]; key=(int(tr),int(tc)); mask=order[start:end]
            if key not in tiles and not np.any(values[mask]!=-1): continue
            if key not in tiles and len(tiles)>=max_tiles:
                complete=False
                continue
            tile=np.full((size,size),-1,np.int8) if key not in tiles else tiles[key].copy()
            tile[rows[mask]%size,cols[mask]%size]=values[mask]
            if np.any(tile!=-1): tiles[key]=_immutable(tile)
            else: tiles.pop(key,None)
    return OverviewTiles(nav,(grid.origin_x_m,grid.origin_z_m),grid.resolution_m,size,MappingProxyType(tiles),complete)


def build_overview(tiles, *, max_cells=1_000_000):
    if not isinstance(tiles,OverviewTiles): raise ValueError('OverviewTiles required')
    if type(max_cells) is not int or not 1<=max_cells<=1_000_000: raise ValueError('invalid cell budget')
    size=tiles.tile_size; bounds=[]
    for (tr,tc),tile in tiles.tiles.items():
        r,c=np.nonzero(tile!=-1)
        if len(r): bounds.append((int(r.min())+tr*size,int(c.min())+tc*size,int(r.max())+tr*size,int(c.max())+tc*size))
    if not bounds:
        return MapOverview(tiles.source_nav,tiles.origin_xy,tiles.resolution_m,np.full((1,1),-1,np.int8),tiles.complete)
    minr=min(b[0] for b in bounds); minc=min(b[1] for b in bounds)
    maxr=max(b[2] for b in bounds); maxc=max(b[3] for b in bounds)
    factor=1
    while ((maxr-minr)//factor+1)*((maxc-minc)//factor+1)>max_cells: factor*=2
    shape=((maxr-minr)//factor+1,(maxc-minc)//factor+1)
    counts=np.zeros(shape,np.int64); occupied=np.zeros(shape,bool)
    for (tr,tc),tile in tiles.tiles.items():
        r,c=np.nonzero(tile!=-1)
        if not len(r): continue
        rr=(r+tr*size-minr)//factor; cc=(c+tc*size-minc)//factor
        vals=tile[r,c]; np.add.at(counts,(rr,cc),vals==0)
        np.logical_or.at(occupied,(rr,cc),vals==100)
    states=np.full(shape,-1,np.int8); states[counts==factor*factor]=0; states[occupied]=100
    origin=(tiles.origin_xy[0]+minc*tiles.resolution_m,tiles.origin_xy[1]+minr*tiles.resolution_m)
    return MapOverview(tiles.source_nav,origin,tiles.resolution_m*factor,states,tiles.complete)
