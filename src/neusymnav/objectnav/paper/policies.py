"""Paper-mode policies without perception (P4 checks). Object policies live in paper/b0.py."""
from __future__ import annotations

import math
from typing import Optional

from .nav import NavConfig, PaperNav


class ScriptedPolicy:
    """Replays a fixed action list, then STOP (runner tests)."""
    name = 'paper_scripted'

    def __init__(self, actions):
        self.actions = list(actions)

    def reset(self, episode):
        self.i = 0

    def act(self, ctx):
        if self.i < len(self.actions):
            self.i += 1
            return self.actions[self.i - 1]
        return 'stop'


class FrontierExplorePolicy:
    """Spin once, then always drive to the nearest reachable frontier; STOP when none is left.

    Never looks for the target: it measures what the map + planner + simulator collisions can
    explore in 500 steps (OSR / target-seen come from the offline evidence and the scorer)."""
    name = 'paper_explore'

    def __init__(self, nav_config: Optional[NavConfig] = None, spin_turns: int = 12):
        self.nav_config, self.spin_turns = nav_config, spin_turns

    def reset(self, episode):
        self.nav = None
        self.spin = self.spin_turns
        self.target = None
        self.blocks = 0
        self._goal_xy = None
        self.events = dict(frontier_unreachable=0, frontier_stuck=0, frontier_reached=0)

    def act(self, ctx):
        if self.nav is None:
            self.nav = PaperNav(ctx.protocol, self.nav_config)
        self.nav.observe(ctx.obs, ctx.last_action)
        if self.spin > 0:
            self.spin -= 1
            return 'turn_left'
        for _ in range(4):
            if self.target is None:
                frontiers = self.nav.frontiers()
                if not frontiers:
                    return ('stop', 'frontiers_exhausted')
                self.target = min(frontiers, key=lambda f: self.nav.path_length_m(f.cell))
                if self._goal_xy is None or math.dist(self._goal_xy, self.target.xy) > self.nav.cfg.frontier_blacklist_m:
                    self.nav.reset_progress()          # same goal re-chosen: keep counting toward 'stuck'
                    self._goal_xy = self.target.xy
            result = self.nav.go_to_cells([self.target.cell])
            if result.action is not None:
                return result.action
            self.events['frontier_' + result.status] = self.events.get('frontier_' + result.status, 0) + 1
            if result.status == 'blocked':                 # the map now marks the bump: turn away, replan
                self.blocks += 1
                if self.blocks < self.nav.cfg.blocked_give_up:
                    return self.nav.escape_turn()
            if result.status in ('stuck', 'blocked'):      # unreachable = map changed: just re-choose
                self.nav.blacklist.append(self.target.xy)
            self.target = None
            self.blocks = 0
        return 'turn_left'           # several goals failed in one step: look around and retry

    def end_episode(self):
        explored = self.nav.map.explored_area_m2() if self.nav and self.nav.map else 0.0
        return dict(events=self.events, explored_m2=round(explored, 2),
                    collision_marks=self.nav.map.collision_marks if self.nav and self.nav.map else 0,
                    repeat_bumps=self.nav.map.repeat_bumps if self.nav and self.nav.map else 0,
                    levels=len(self.nav.map.levels) if self.nav and self.nav.map else 0,
                    relaxed_plan_steps=self.nav.relaxed_steps if self.nav else 0)
