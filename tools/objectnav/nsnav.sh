#!/usr/bin/env bash
# nsnav: short commands for ObjectNav policy development (docs/objectnav/policy-dev-cheatsheet.md).
# Every run lives in runs/objectnav/<name>/. Run `bash tools/objectnav/nsnav.sh help`.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT" || exit 1
PY=".venv/bin/python"
HAB="${HABITAT_PYTHON:-$HOME/miniconda3/envs/habitat/bin/python}"
B0_OUTCOMES="docs/objectnav/results/b0-dev60-v3h/trajectories+evidence-outcomes.jsonl"
DEV_SPLIT="configs/objectnav/splits/hm3d_v2-val-dev.json"
TEST_SPLIT="configs/objectnav/splits/hm3d_v2-val-test.json"
SMOKE_SPLIT="configs/objectnav/splits/hm3d_v2-val-dev-smoke.json"
DEFAULT_POLICY=b0; DEFAULT_CFG=lockstep-b0-v3h; DEFAULT_POL=b0-policy-v3
LOG_FILTER='^\[[0-9:]+\]|^(I|W)[0-9]{4} |GL_|mesa-|no-layout|^Using |^Renderer|^OpenGL'

die() { echo "nsnav: $*" >&2; exit 1; }
need_name() { [ -n "${1:-}" ] || die "missing run name (see: nsnav help)"; }
run_dir() { echo "runs/objectnav/$1"; }
busy() { ps -eo args | grep -E "python[^ ]* .*(tools/objectnav/run_episodes.py|habitat_worker.py|neusymnav.cli run)" | grep -v grep; }
load_env() {   # settings saved by `nsnav run`, else defaults
    POLICY=$DEFAULT_POLICY; CFG=$DEFAULT_CFG; POL=$DEFAULT_POL
    [ -f "$1/nsnav.env" ] && . "$1/nsnav.env"
    return 0
}
outcomes_of() {   # best outcomes file of a run (with evidence if present)
    if [ -f "$1/trajectories+evidence-outcomes.jsonl" ]; then echo "$1/trajectories+evidence-outcomes.jsonl"
    elif [ -f "$1/trajectories-outcomes.jsonl" ]; then echo "$1/trajectories-outcomes.jsonl"
    else die "$1 is not scored yet (run: nsnav score $(basename "$1"))"; fi
}

usage() {
cat <<'EOF'
nsnav — ObjectNav policy development helper (run from anywhere)

Pick episodes
  nsnav list [dev|test]                 list uids (dev also shows the B0 result)
  nsnav pick [filters]                  print DEV uids matching the B0 result, for `nsnav new`
      --mode M       OK | never_seen | budget_exhausted | wrong_object_stop | stopped_too_far
                     | seen_not_detected | stopped_elsewhere   (repeatable)
      --scene S      e.g. TEEsavR23oF (repeatable)
      --cat C        sofa | chair | bed | toilet | plant | tv_monitor (repeatable)
      --limit N      at most N uids
  nsnav show <uid | scene>              B0 numbers for one episode, or the episodes of a scene

Daily loop  (<name> = folder under runs/objectnav/; a new name for every code change)
  nsnav new <name> [--set smoke|dev] [--from <run>] [uid ...]
                                        create runs/objectnav/<name>/manifest.json
      --set smoke    the fixed 12-episode check set (2 per DEV scene, B0 6/12, ~55 min with B0)
      --set dev      all 60 DEV episodes
      --from <run>   the same episodes as an earlier run
      uid            full or short (LT9Jq6dN3Ea/1); sources can be combined
  nsnav run <name> [--policy P] [--cfg C] [--pol F]
                                        run, then score + per-episode table + comparison with B0
                                        (default b0, lockstep-b0-v3h, b0-policy-v3; resumable)
  nsnav why <name>                      failure evidence + per-mode table + report.md
  nsnav why <name> --stuck              stuck / no-motion diagnosis instead

Look again at a finished run
  nsnav score <name>                    SR / SPL / OSR (re-scoring replaces old score files)
  nsnav eps <name>                      one line per episode: result, SPL, DTG, path, time
  nsnav compare <name> [<other>]        paired comparison with B0 (or with another run)
  nsnav runs                            list runs: SR, SPL, settings, code id

Full evaluation and checks
  nsnav dev60 <name> [--policy P] [--cfg C] [--pol F]
                                        60 DEV episodes, ~5 h, resumable (tools/objectnav/b0/run_dev60.sh)
  nsnav test [all]                      ObjectNav tests (all = whole CPU suite, ~4 min)
  nsnav ps                              is a simulator / demo running?

Examples
  nsnav new v1 --set smoke && nsnav run v1 --policy mypolicy
  nsnav new v2 --from v1   && nsnav run v2 --policy mypolicy && nsnav compare v2 v1
  nsnav new fix $(nsnav pick --mode never_seen --scene TEEsavR23oF --limit 4) LT9Jq6dN3Ea/1
EOF
}

cmd_list() {
    case "${1:-dev}" in
        dev) python3 - "$B0_OUTCOMES" "$DEV_SPLIT" <<'PY'
import json, sys
b0 = {r['uid']: r for r in map(json.loads, open(sys.argv[1]))}
for u in json.load(open(sys.argv[2]))['uids']:
    r = b0.get(u)
    print('%-34s %-11s %s' % (u, r['category'] if r else '?', ('OK' if r['success'] else r['failure_mode']) if r else '-'))
PY
        ;;
        test) python3 -c "import json,sys; print('\n'.join(json.load(open(sys.argv[1]))['uids']))" "$TEST_SPLIT"
              echo "nsnav: TEST is for the final, one-time evaluation of a frozen policy" >&2 ;;
        *) die "list dev|test" ;;
    esac
}

cmd_pick() {
    python3 - "$B0_OUTCOMES" "$@" <<'PY'
import json, sys
rows = list(map(json.loads, open(sys.argv[1])))
args, modes, scenes, cats, limit = sys.argv[2:], set(), set(), set(), None
i = 0
while i < len(args):
    k = args[i]; v = args[i + 1] if i + 1 < len(args) else None
    if v is None: sys.exit('nsnav pick: %s needs a value' % k)
    if k == '--mode': modes.add(v)
    elif k == '--scene': scenes.add(v)
    elif k == '--cat': cats.add(v)
    elif k == '--limit': limit = int(v)
    else: sys.exit('nsnav pick: unknown option %s' % k)
    i += 2
out = []
for r in rows:
    mode = 'OK' if r['success'] else r['failure_mode']
    if (not modes or mode in modes) and (not scenes or r['scene'] in scenes) and (not cats or r['category'] in cats):
        out.append(r['uid'])
if not out: print('nsnav pick: no DEV episode matches', file=sys.stderr)
print('\n'.join(out[:limit] if limit else out))
PY
}

cmd_show() {
    [ -n "${1:-}" ] || die "show <uid | scene>   e.g. nsnav show LT9Jq6dN3Ea/1  or  nsnav show LT9Jq6dN3Ea"
    python3 - "$B0_OUTCOMES" "$1" <<'PY'
import json, sys
rows = list(map(json.loads, open(sys.argv[1])))
arg = sys.argv[2].strip().strip('/')
uid = arg if arg.startswith('hm3d_v2/') else 'hm3d_v2/val/' + arg
hit = [r for r in rows if r['uid'] == uid]
if hit:
    r = hit[0]
    keys = ('uid', 'scene', 'category', 'success', 'failure_mode', 'spl', 'soft_spl', 'dtg_start_m', 'dtg_end_m',
            'dtg_min_m', 'oracle_success', 'path_length_m', 'steps', 'sim_time_s', 'called_stop')
    for k in keys: print('%-15s %s' % (k, r.get(k)))
    sys.exit(0)
scene = [r for r in rows if r['scene'] == arg]
if scene:
    print('scene %s: %d DEV episodes, B0 %d OK' % (arg, len(scene), sum(r['success'] for r in scene)))
    for r in scene:
        print('  %-34s %-11s %-18s SPL %.3f  DTG %.2f m' % (r['uid'], r['category'],
              'OK' if r['success'] else r['failure_mode'], r['spl'], r['dtg_end_m']))
    print('details: nsnav show %s' % scene[0]['uid'])
    sys.exit(0)
scenes = sorted({r['scene'] for r in rows})
sys.exit('nsnav: "%s" is neither a DEV episode nor a DEV scene.\n'
         '  episode: nsnav show LT9Jq6dN3Ea/1   (or hm3d_v2/val/LT9Jq6dN3Ea/1)\n'
         '  scene  : nsnav show LT9Jq6dN3Ea\n'
         '  DEV scenes: %s' % (sys.argv[2], ' '.join(scenes)))
PY
}

cmd_new() {
    need_name "${1:-}"; local name=$1; shift
    case "$name" in -*) die "new <name> ...: the run name comes first" ;; esac
    local from="" set="" uids=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --from) from=${2:?--from needs a run name}; shift 2 ;;
            --set) set=${2:?--set needs smoke or dev}; shift 2 ;;
            -*) die "new: unknown option $1" ;;
            *) uids+=("$1"); shift ;;
        esac
    done
    local src_from="" src_set=""
    if [ -n "$from" ]; then
        src_from="$(run_dir "$from")/manifest.json"
        [ -f "$src_from" ] || die "no run '$from' to copy episodes from (nsnav runs)"
    fi
    case "$set" in
        "") ;; smoke) src_set=$SMOKE_SPLIT ;; dev) src_set=$DEV_SPLIT ;;
        *) die "new: --set smoke | dev" ;;
    esac
    [ -n "$src_from$src_set" ] || [ ${#uids[@]} -gt 0 ] || \
        die "new <name> [--set smoke|dev] [--from <run>] [uid ...]  (tip: nsnav pick ...)"
    local out; out=$(run_dir "$name")
    [ -e "$out" ] && die "$out already exists; use another name"
    mkdir -p "$out"
    python3 - "$out/manifest.json" "$name" "$DEV_SPLIT" "$TEST_SPLIT" "$src_set" "$src_from" ${uids[@]+"${uids[@]}"} <<'PY'
import json, sys
path, name, dev, test, src_set, src_from, uids = *sys.argv[1:7], sys.argv[7:]
known_dev = set(json.load(open(dev))['uids']); known_test = set(json.load(open(test))['uids'])
uids = [u if u.startswith('hm3d_v2/') else 'hm3d_v2/val/' + u.strip('/') for u in uids]
for src in (src_set, src_from):
    if src: uids = json.load(open(src))['uids'] + uids
bad = [u for u in uids if u not in known_dev | known_test]
if bad: sys.exit('nsnav new: unknown uid %s (see: nsnav list)' % bad[0])
if any(u in known_test for u in uids): print('nsnav: WARNING: TEST episodes included; do not tune on TEST', file=sys.stderr)
uids = list(dict.fromkeys(uids))
json.dump({'schema_version': 1, 'name': name, 'uids': uids}, open(path, 'w'), indent=1)
print('created %s with %d episode(s)' % (path, len(uids)))
PY
    local rc=$?; [ $rc -eq 0 ] || rm -rf "$out"; return $rc
}

parse_run_opts() {
    POLICY=$DEFAULT_POLICY; CFG=$DEFAULT_CFG; POL=$DEFAULT_POL
    while [ $# -gt 0 ]; do
        case "$1" in
            --policy) POLICY=${2:?}; shift 2 ;;
            --cfg) CFG=${2%.json}; shift 2 ;;
            --pol) POL=${2%.json}; shift 2 ;;
            *) die "unknown option $1" ;;
        esac
    done
    [ -f "configs/objectnav/$CFG.json" ] || die "no configs/objectnav/$CFG.json"
    [ -f "configs/objectnav/$POL.json" ] || die "no configs/objectnav/$POL.json"
}

cmd_run() {
    need_name "${1:-}"; local name=$1; shift
    local out; out=$(run_dir "$name")
    [ -f "$out/manifest.json" ] || die "$out/manifest.json missing (nsnav new $name <uid> ...)"
    if [ -f "$out/nsnav.env" ] && [ $# -eq 0 ]; then load_env "$out"; else parse_run_opts "$@"; fi
    if [ -f "$out/nsnav.env" ]; then
        local prev; prev=$(cat "$out/nsnav.env")
        local prev_line; prev_line=$(tr '\n' ' ' < "$out/nsnav.env")
        [ "$prev" = "$(printf 'POLICY=%s\nCFG=%s\nPOL=%s' "$POLICY" "$CFG" "$POL")" ] || \
            die "$out was started with other settings (${prev_line% }); use a new name"
    fi
    busy >/dev/null && die "a simulator/demo is already running (nsnav ps)"
    local code; code=$(code_state "$out") || exit 1
    printf 'POLICY=%s\nCFG=%s\nPOL=%s\n' "$POLICY" "$CFG" "$POL" > "$out/nsnav.env"
    echo "== run $name: policy $POLICY, runner $CFG, policy config $POL, $code ($(date '+%H:%M:%S'))"
    PYTHONPATH=src "$PY" tools/objectnav/run_episodes.py --set hm3d_v2 --split val \
        --manifest "$out/manifest.json" --policy "$POLICY" --run-id "$name" --out-dir "$out" \
        --config "configs/objectnav/$CFG.json" --b0-config "configs/objectnav/$POL.json" 2>&1 \
        | grep -v -E "$LOG_FILTER"
    local rc=${PIPESTATUS[0]}
    echo "== run exit $rc ($(date '+%H:%M:%S'))"
    [ "$rc" -eq 0 ] || { echo "nsnav: run did not finish; run 'nsnav run $name' again to resume" >&2; return "$rc"; }
    echo "== score"; cmd_score "$name" || return 1
    echo "== episodes"; cmd_eps "$name"
    echo "== vs B0"; cmd_compare "$name"
}

# Fingerprint of the code a run uses (working-tree content of the policy/runner sources).
# First start: saved to <run>/code.json (+ code.diff when there are uncommitted changes).
# Later starts: refuse when the code differs, so one run never mixes two code versions.
code_state() {
    python3 - "$1" <<'PY'
import hashlib, json, subprocess, sys, time
from pathlib import Path
out = Path(sys.argv[1]); paths = ['src', 'configs/objectnav', 'tools/objectnav/run_episodes.py']
g = lambda *a: subprocess.run(['git', *a], capture_output=True, text=True, check=True).stdout
files = sorted(set(g('ls-files', '-c', '-o', '--exclude-standard', '-z', '--', *paths).split('\0')) - {''})
h = hashlib.sha256()
for f in files:
    p = Path(f)
    h.update(f.encode() + b'\0' + (hashlib.sha256(p.read_bytes()).digest() if p.is_file() else b'deleted'))
code = h.hexdigest()[:10]
changed = [l[3:] for l in g('status', '--porcelain', '--', *paths).splitlines()]
head = g('rev-parse', '--short', 'HEAD').strip()
saved = out / 'code.json'
if saved.exists():
    old = json.loads(saved.read_text())['code']
    if old != code:
        sys.exit('nsnav: the code changed since run "%s" started (%s -> %s).\n'
                 '  Use a new name with the same episodes: nsnav new <new> --from %s' % (out.name, old, code, out.name))
else:
    saved.write_text(json.dumps({'code': code, 'head': head, 'branch': g('rev-parse', '--abbrev-ref', 'HEAD').strip(),
                                 'uncommitted': changed, 'paths': paths,
                                 'started': time.strftime('%Y-%m-%dT%H:%M:%S%z')}, indent=1) + '\n')
    if changed: (out / 'code.diff').write_text(g('diff', 'HEAD', '--', *paths))
print('code %s (HEAD %s%s)' % (code, head, ', %d uncommitted file(s)' % len(changed) if changed else ''))
PY
}

cmd_score() {
    need_name "${1:-}"; local out; out=$(run_dir "$1")
    [ -s "$out/trajectories.jsonl" ] || die "$out has no trajectories (nsnav run $1)"
    rm -f "$out/trajectories-outcomes.jsonl" "$out/trajectories-summary.json"
    PYTHONPATH=src "$HAB" tools/objectnav/score_trajectories.py "$out/trajectories.jsonl" \
        --set hm3d_v2 --split val 2>/dev/null
}

cmd_why() {
    need_name "${1:-}"; local out; out=$(run_dir "$1"); load_env "$out"
    [ -s "$out/trajectories.jsonl" ] || die "$out has no trajectories (nsnav run $1)"
    case "${2:-}" in
        "") ;; --stuck) cmd_stuck "$1"; return ;;
        *) die "why <name> [--stuck]" ;;
    esac
    [ -d "$out/evidence" ] || die "$out/evidence missing: the policy must write B0-format evidence for this step"
    rm -f "$out/trajectories-evidence.jsonl" "$out/trajectories+evidence.jsonl" \
          "$out/trajectories+evidence-outcomes.jsonl" "$out/trajectories+evidence-summary.json"
    PYTHONPATH=src "$HAB" tools/objectnav/b0/failure_evidence.py "$out" --set hm3d_v2 --split val \
        --runner-config "configs/objectnav/$CFG.json" 2>&1 | grep -v -E "$LOG_FILTER" | tail -n 4 || return 1
    PYTHONPATH=src "$HAB" tools/objectnav/score_trajectories.py "$out/trajectories+evidence.jsonl" \
        --set hm3d_v2 --split val 2>/dev/null
    PYTHONPATH=src "$PY" tools/objectnav/b0/summarize_run.py "$out" >/dev/null && echo "report: $out/report.md"
}

cmd_stuck() {
    need_name "${1:-}"; local out; out=$(run_dir "$1"); load_env "$out"
    PYTHONPATH=src "$HAB" tools/objectnav/b0/diagnose_stuck.py "$out" --set hm3d_v2 --split val \
        --runner-config "configs/objectnav/$CFG.json" 2>&1 | grep -v -E "$LOG_FILTER" | tail -n 25
    PYTHONPATH=src "$HAB" tools/objectnav/b0/diagnose_no_motion.py "$out" --set hm3d_v2 --split val \
        --runner-config "configs/objectnav/$CFG.json" 2>&1 | grep -v -E "$LOG_FILTER" | tail -n 25
}

cmd_eps() {
    need_name "${1:-}"; local f; f=$(outcomes_of "$(run_dir "$1")") || exit 1
    python3 - "$f" "$B0_OUTCOMES" <<'PY'
import json, sys
b0 = {r['uid']: r for r in map(json.loads, open(sys.argv[2]))}
print('%-34s %-11s %-18s %6s %6s %6s %6s %6s  %s' % ('uid', 'category', 'result', 'SPL', 'DTG', 'minDTG', 'path', 'sim_s', 'B0'))
for r in map(json.loads, open(sys.argv[1])):
    res = 'OK' if r['success'] else (r['failure_mode'] or '-')
    b = b0.get(r['uid']); bres = ('OK' if b['success'] else b['failure_mode']) if b else '-'
    print('%-34s %-11s %-18s %6.3f %6.2f %6.2f %6.1f %6.0f  %s' % (r['uid'], r['category'], res, r['spl'], r['dtg_end_m'],
          r.get('dtg_min_m') or float('nan'), r['path_length_m'], r['sim_time_s'] or float('nan'), bres))
PY
}

cmd_compare() {
    need_name "${1:-}"; local new ref
    new=$(outcomes_of "$(run_dir "$1")") || exit 1
    if [ -n "${2:-}" ]; then ref=$(outcomes_of "$(run_dir "$2")") || exit 1; else ref=$B0_OUTCOMES; fi
    python3 - "$ref" "$new" <<'PY'
import json, math, sys
load = lambda p: {r['uid']: r for r in map(json.loads, open(p))}
a, b = load(sys.argv[1]), load(sys.argv[2])
u = sorted(a.keys() & b.keys())
if not u: sys.exit('nsnav compare: no common episodes')
sr = lambda d: sum(d[k]['success'] for k in u)
spl = lambda d: sum(d[k]['spl'] for k in u) / len(u)
wins = [k for k in u if b[k]['success'] and not a[k]['success']]
loss = [k for k in u if a[k]['success'] and not b[k]['success']]
n, k = len(wins) + len(loss), min(len(wins), len(loss))
p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n) if n else 1.0
print('reference : %s' % sys.argv[1]); print('new       : %s' % sys.argv[2])
print('episodes in common: %d' % len(u))
print('SR   ref %d/%d (%.3f)   new %d/%d (%.3f)' % (sr(a), len(u), sr(a) / len(u), sr(b), len(u), sr(b) / len(u)))
print('SPL  ref %.3f   new %.3f' % (spl(a), spl(b)))
print('paired: new wins %d, new losses %d, exact McNemar p = %.3f%s' % (len(wins), len(loss), p,
      '' if n else ' (no disagreement)'))
for tag, ks in (('wins', wins), ('losses', loss)):
    for k_ in ks: print('  %-6s %s %s' % (tag, k_, b[k_]['category']))
if len(u) < 60: print('note: fewer than 60 episodes; use this to debug, judge the policy on nsnav dev60')
PY
}

cmd_dev60() {
    need_name "${1:-}"; local name=$1; shift
    parse_run_opts "$@"
    busy >/dev/null && die "a simulator/demo is already running (nsnav ps)"
    local out; out=$(run_dir "$name")
    mkdir -p "$out"; printf 'POLICY=%s\nCFG=%s\nPOL=%s\n' "$POLICY" "$CFG" "$POL" > "$out/nsnav.env"
    OUT="$out" RUN_ID="$name" POLICY="$POLICY" CFG="$CFG" POL="$POL" bash tools/objectnav/b0/run_dev60.sh
}

cmd_test() {
    if [ "${1:-}" = all ]; then
        QT_QPA_PLATFORM=offscreen OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONPATH=src:.:tests \
            "$PY" -m pytest tests -q -m "not native" -p no:cacheprovider --tb=line 2>&1 | grep -E "^(FAILED|ERROR)|passed|failed"
    else
        PYTHONPATH=src:.:tests "$PY" -m pytest -q -p no:cacheprovider tests/test_objectnav_*.py 2>&1 | tail -n 3
    fi
}

cmd_ps() { busy || echo "nothing running"; }

cmd_runs() {
    python3 - <<'PY'
import json
from pathlib import Path
for d in sorted(Path('runs/objectnav').glob('*/'), key=lambda p: p.stat().st_mtime):
    s = d / 'trajectories+evidence-summary.json'
    s = s if s.exists() else d / 'trajectories-summary.json'
    n = sum(1 for _ in open(d / 'trajectories.jsonl')) if (d / 'trajectories.jsonl').exists() else 0
    env = (d / 'nsnav.env').read_text().replace('\n', ' ').strip() if (d / 'nsnav.env').exists() else ''
    if (d / 'code.json').exists():
        c = json.loads((d / 'code.json').read_text())
        env += '  code %s (%s%s)' % (c['code'], c['head'], '+' if c['uncommitted'] else '')
    if s.exists():
        o = json.loads(s.read_text())['overall']
        print('%-22s %3d ep  SR %.3f  SPL %.3f  %s' % (d.name, o['episodes'], o['success_rate'], o['spl'], env))
    elif n or (d / 'manifest.json').exists():
        print('%-22s %3d ep  (not scored)  %s' % (d.name, n, env))
PY
}

sub=${1:-help}; [ $# -gt 0 ] && shift
case "$sub" in
    list) cmd_list "$@" ;; pick) cmd_pick "$@" ;; show) cmd_show "$@" ;;
    new) cmd_new "$@" ;; run) cmd_run "$@" ;; score) cmd_score "$@" ;; why) cmd_why "$@" ;;
    eps) cmd_eps "$@" ;; compare) cmd_compare "$@" ;;
    stuck) die "use: nsnav why ${1:-<name>} --stuck" ;;
    try) die "use: nsnav new ${1:-<name>} <uid ...> && nsnav run ${1:-<name>}  (run now scores and compares)" ;;
    dev60) cmd_dev60 "$@" ;; test) cmd_test "$@" ;; ps) cmd_ps ;; runs) cmd_runs ;;
    help|-h|--help) usage ;;
    *) usage; exit 2 ;;
esac
