"""Canonical multi-goal planner; shared Dijkstra and single-goal A* are ported."""
from dataclasses import dataclass
from ..contracts import NavSnapshot
from ..mapping.occupancy import RobotGeometry
from ._grid import adapt
from ._planner_core import AStarPlanner, PlannerConfig


@dataclass(frozen=True)
class PlanResult:
    success: bool
    cells: tuple[tuple[int,int],...]
    cost_m: float
    map_revision: int
    reason: str
    origin_xy: tuple[float,float]
    resolution_m: float
    episode_id: str
    robot_geometry_id: str

    def valid_for(self, nav: NavSnapshot) -> bool:
        return self.success and (self.map_revision,self.origin_xy,self.resolution_m,self.episode_id,self.robot_geometry_id)==(
            nav.revision,nav.origin_xy,nav.resolution_m,nav.episode_id,nav.robot_geometry_id)


class Planner:
    def __init__(self, robot: RobotGeometry, *, allow_diagonal=True,max_expansions=500_000):
        self.robot=robot
        self.core=AStarPlanner(PlannerConfig(robot.radius_m,robot.margin_m,allow_diagonal,max_expansions))

    def _result(self,nav,result):
        return PlanResult(result.success,result.cells,result.cost_m,result.map_revision,result.reason,
            nav.origin_xy,nav.resolution_m,nav.episode_id,nav.robot_geometry_id)

    def plan(self, nav: NavSnapshot, start_xy: tuple[float,float], goal: tuple[int,int]) -> PlanResult:
        return self._result(nav,self.core.plan(adapt(nav,self.robot.height_m,self.robot.geometry_id),start_xy,goal))

    def plan_many(self, nav: NavSnapshot, start_xy: tuple[float,float], goals: tuple[tuple[int,int],...]) -> dict:
        grid=adapt(nav,self.robot.height_m,self.robot.geometry_id)
        return {goal:self._result(nav,result) for goal,result in self.core.plan_many(grid,start_xy,goals).items()}
