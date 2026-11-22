# B1 analysis: dump the map when an episode ends and count frontiers (raw / blacklisted / unreachable).
# usage (repo root): .venv/bin/python tools/objectnav/b1/frontier_exhaustion_diag.py --dump DIR <run_paper_episodes.py args>
import sys, json, math, numpy as np, runpy
sys.path.insert(0, 'src'); sys.path.insert(0, 'tools/objectnav')
from neusymnav.objectnav.paper import b0 as B
orig = B.PaperB0Policy.end_episode
def end(self):
    nav = self.nav; m = nav.map
    raw = m.frontiers(nav.trav, nav.cfg.min_frontier_cells)
    bl = [f for f in raw if any(math.dist(f.xy, b) < nav.cfg.frontier_blacklist_m for b in nav.blacklist)]
    unr = [f for f in raw if f not in bl and not math.isfinite(nav.field.distance(f.cell))]
    raw_small = m.frontiers(nav.trav, 1)
    rec = dict(uid=self.episode.uid, step=self.step, raw=len(raw), raw_any=len(raw_small), blacklisted=len(bl), unreachable=len(unr),
               blacklist=len(nav.blacklist), relaxed=nav.relaxed, levels=len(m.levels), level_z=m.level.z_m,
               unreach_d=[round(math.dist(f.xy, nav.robot_xy), 1) for f in unr][:8],
               explored_m2=round(m.explored_area_m2(), 1))
    open(DUMP + '/fx.jsonl', 'a').write(json.dumps(rec) + '\n')
    np.savez_compressed(DUMP + '/' + self.episode_tag + '.npz', explored=m.explored, obstacle=m.obstacle,
                        trav=nav.trav, origin=np.array(m.origin), res=m.res, path=np.array(nav._recent),
                        blacklist=np.array(nav.blacklist).reshape(-1, 2))
    return orig(self)
B.PaperB0Policy.end_episode = end
i = sys.argv.index('--dump'); DUMP = sys.argv[i + 1]; del sys.argv[i:i + 2]
sys.argv[0] = 'tools/objectnav/run_paper_episodes.py'
runpy.run_path('tools/objectnav/run_paper_episodes.py', run_name='__main__')
