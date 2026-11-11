"""A long preview must not veto a fully observed, shorter bounded pulse."""
import json
import math
from pathlib import Path
from neusymnav.contracts import from_dict
from neusymnav.mapping.occupancy import RobotGeometry
from neusymnav.navigation._grid import adapt, PathResult
from neusymnav.navigation._controller_core import Controller, ControllerConfig
from neusymnav.navigation.planner import Planner


def test_recorded_corner_can_be_approached_with_the_actual_pulse_horizon():
    data=json.loads((Path(__file__).parent/'fixtures/movement_corner.json').read_text())
    nav=from_dict(data['nav']);robot=RobotGeometry(**data['robot'])
    grid=adapt(nav,robot.height_m,robot.geometry_id);planner=Planner(robot)
    cells=tuple(tuple(cell) for cell in data['path'])
    assert planner.core.plan(grid,tuple(data['robot_xy']),cells[-1]).success
    path=PathResult(True,cells,1.,nav.revision,grid_origin_x_m=grid.origin_x_m,
                    grid_origin_y_m=grid.origin_y_m,grid_resolution_m=grid.resolution_m)
    controller=Controller(ControllerConfig(discrete_heading_control=True),
                          traversable=planner.core.traversable)
    command=controller.tick(robot_xy=tuple(data['robot_xy']),yaw_rad=data['yaw'],
        now_monotonic_s=grid.host_monotonic_s+.1,dt_s=.1,
        depth_host_monotonic_s=grid.host_monotonic_s,depth_front_min_m=None,
        depth_coverage_ok=True,snapshot=grid,path=path,frame_id=grid.as_of_frame_id,
        goal_world_xy=tuple(data['goal']))
    assert command.reason == 'tracking'
    assert 0. < command.linear_mps <= .2
    assert command.yaw_rate_radps == 0.
    assert command.linear_mps*.1 <= .02
