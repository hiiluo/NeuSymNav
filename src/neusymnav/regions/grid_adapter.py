"""Narrow, unchanged raster conversion; no secondary inflation or floor guesses."""
from ..contracts import RegionGrid, NavSnapshot

def from_nav(nav: NavSnapshot) -> RegionGrid:
    return RegionGrid.from_nav(nav)
