"""Habitat-side helpers for OFFLINE evaluation (geodesic oracle, scripted agents).

Import only from the Habitat interpreter. Privileged data (navmesh paths, goal
view points) used here must never reach the robot runtime: these helpers serve
the scorer and the validation agents only.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np

# HM3D ObjectNav challenge agent (habitat-lab objectnav_hm3d): radius 0.18 m, height 0.88 m.
AGENT_RADIUS_M = 0.18
AGENT_HEIGHT_M = 0.88
FORWARD_STEP_M = 0.25
TURN_DEG = 30.0
MAX_STEPS = 500


def open_scene(scene_path: str, dataset_config: Optional[str], *, with_actions: bool = True):
    """A sensorless simulator for geodesic queries (and discrete validation actions)."""
    import habitat_sim
    sim_cfg = habitat_sim.SimulatorConfiguration()
    sim_cfg.scene_id = scene_path
    if dataset_config:
        sim_cfg.scene_dataset_config_file = dataset_config
    sim_cfg.enable_physics = False
    sim_cfg.allow_sliding = True
    agent_cfg = habitat_sim.agent.AgentConfiguration()
    agent_cfg.radius = AGENT_RADIUS_M
    agent_cfg.height = AGENT_HEIGHT_M
    agent_cfg.sensor_specifications = []
    if with_actions:
        spec, act = habitat_sim.agent.ActionSpec, habitat_sim.agent.ActuationSpec
        agent_cfg.action_space = {
            'move_forward': spec('move_forward', act(amount=FORWARD_STEP_M)),
            'turn_left': spec('turn_left', act(amount=TURN_DEG)),
            'turn_right': spec('turn_right', act(amount=TURN_DEG)),
        }
    sim = habitat_sim.Simulator(habitat_sim.Configuration(sim_cfg, [agent_cfg]))
    if not sim.pathfinder.is_loaded:
        sim.close()
        raise RuntimeError('navmesh not loaded for %s' % scene_path)
    return sim


def distance_to_goal(sim, position: Sequence[float], view_points: Sequence[Sequence[float]]) -> float:
    """Geodesic distance to the nearest view point; inf when unreachable."""
    import habitat_sim
    path = habitat_sim.MultiGoalShortestPath()
    path.requested_start = np.asarray(position, dtype=np.float32)
    path.requested_ends = [np.asarray(v, dtype=np.float32) for v in view_points]
    if not sim.pathfinder.find_path(path):
        return float('inf')
    return float(path.geodesic_distance)


def shortest_path(sim, position: Sequence[float], view_points: Sequence[Sequence[float]]) -> List[List[float]]:
    """Way points of the shortest path to the nearest view point ([] when unreachable)."""
    import habitat_sim
    path = habitat_sim.MultiGoalShortestPath()
    path.requested_start = np.asarray(position, dtype=np.float32)
    path.requested_ends = [np.asarray(v, dtype=np.float32) for v in view_points]
    if not sim.pathfinder.find_path(path):
        return []
    return [[float(c) for c in p] for p in path.points]


def place_agent(sim, position: Sequence[float], rotation_xyzw: Sequence[float]) -> None:
    import habitat_sim
    import quaternion  # numpy-quaternion ships with habitat_sim
    state = habitat_sim.AgentState()
    state.position = np.asarray(position, dtype=np.float32)
    x, y, z, w = (float(c) for c in rotation_xyzw)
    state.rotation = quaternion.quaternion(w, x, y, z)
    sim.get_agent(0).set_state(state)


def agent_position(sim) -> List[float]:
    return [float(c) for c in sim.get_agent(0).get_state().position]
