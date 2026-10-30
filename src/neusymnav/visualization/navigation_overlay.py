"""Bounded view of actual frontier planning, built outside the control lane."""
from dataclasses import dataclass
import itertools
import math
from ..contracts import FrameKey

MAX_FRONTIER_POINTS=8192
MAX_VIEWPOINTS=64
MAX_DISPLAY_PATH=2048


def _points(value,limit):
    if type(value) is not tuple or len(value)>limit:
        raise ValueError('navigation display point count/type bound')
    if any(type(p) is not tuple or len(p)!=2 or any(type(x) not in (int,float) or not math.isfinite(x) for x in p) for p in value):
        raise ValueError('finite navigation display coordinates required')


@dataclass(frozen=True,slots=True)
class NavigationOverlay:
    source: FrameKey
    capture_monotonic_ns: int
    clock_domain: str
    map_revision: int
    computed_monotonic_ns: int
    frontier_points: tuple[tuple[float,float],...]
    viewpoints: tuple[tuple[float,float],...]
    goal_id: str | None
    goal_xy: tuple[float,float] | None
    path: tuple[tuple[float,float],...]
    status: str
    truncated: bool = False

    def __post_init__(self):
        if (not isinstance(self.source,FrameKey) or not isinstance(self.clock_domain,str) or not self.clock_domain
                or type(self.capture_monotonic_ns) is not int or self.capture_monotonic_ns<0
                or type(self.map_revision) is not int or self.map_revision<0
                or type(self.computed_monotonic_ns) is not int or self.computed_monotonic_ns<self.capture_monotonic_ns
                or not isinstance(self.status,str) or not 0<len(self.status)<=256 or type(self.truncated) is not bool):
            raise ValueError('invalid navigation display provenance/status')
        _points(self.frontier_points,MAX_FRONTIER_POINTS);_points(self.viewpoints,MAX_VIEWPOINTS);_points(self.path,MAX_DISPLAY_PATH)
        if (self.goal_id is None)!=(self.goal_xy is None):raise ValueError('goal ID/position must be paired')
        if self.goal_id is not None:
            if not isinstance(self.goal_id,str) or not 0<len(self.goal_id)<=256:raise ValueError('bounded goal ID required')
            _points((self.goal_xy,),1)
        elif self.path:raise ValueError('display route requires an active selected goal')


def from_plan(nav,frontiers,decision,reason,computed_ns,*,clear_goal=False,held_goal=None):
    """Copy one actual extractor/decision bundle; never rerun navigation."""
    if decision.map_revision!=nav.revision or (frontiers is not None and frontiers.map_revision!=nav.revision):
        raise ValueError('planner display input map revision mismatch')
    candidates=() if frontiers is None else frontiers.frontiers
    cells=tuple(itertools.islice((cell for f in candidates for cell in f.boundary_cells),MAX_FRONTIER_POINTS+1))
    def world(cell):
        row,col=cell
        if not 0<=row<nav.states.shape[0] or not 0<=col<nav.states.shape[1]:raise ValueError('frontier display cell outside source map')
        return (nav.origin_xy[0]+(col+.5)*nav.resolution_m,nav.origin_xy[1]+(row+.5)*nav.resolution_m)
    points=tuple(world(cell) for cell in cells[:MAX_FRONTIER_POINTS])
    viewpoints=tuple(world(f.viewpoint_cell) for f in candidates[:MAX_VIEWPOINTS])
    goal_id=None if clear_goal or not decision.goal_id or not decision.path else decision.goal_id
    goal=None if goal_id is None else decision.path[-1]
    path=() if goal is None or len(decision.path)>MAX_DISPLAY_PATH else decision.path
    # A commitment is intent, not an executable route. Keep its marker when
    # blocked while omitting the rejected/absent route and labeling the wait.
    if goal is None and held_goal is not None:
        goal_id,goal=held_goal
        reason='held_goal:'+str(reason)
    return NavigationOverlay(nav.source,nav.capture_monotonic_ns,nav.clock_domain,nav.revision,computed_ns,
        points,viewpoints,goal_id,goal,path,str(reason)[:256],
        len(cells)>MAX_FRONTIER_POINTS or len(candidates)>MAX_VIEWPOINTS or len(decision.path)>MAX_DISPLAY_PATH)
