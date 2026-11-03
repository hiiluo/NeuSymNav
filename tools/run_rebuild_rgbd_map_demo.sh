#!/usr/bin/env bash
# Opt-in Rebuild M1-M5 RGB-D room-map profile, version 1.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

usage() {
    cat >&2 <<'EOF'
Usage:
  bash tools/run_rebuild_rgbd_map_demo.sh MAP [duration_seconds|--preflight] [new_output_directory]
  bash tools/run_rebuild_rgbd_map_demo.sh --config CONFIG [duration_seconds|--preflight] [new_output_directory]

MAP is any safe map identifier, for example 00805 or 00770. By default its
calibrated local profile is configs/demo-MAP.local.json. --config accepts an
explicit calibrated local profile. Set NEUSYMNAV_REBUILD_ROOT to select the
Rebuild checkout; otherwise the adjacent Rebuild_3DScene_OccuSG checkout is used.
EOF
    exit 2
}

(( $# >= 1 && $# <= 4 )) || usage
selector="$1"; shift
if [[ "$selector" == --config ]]; then
    (( $# >= 1 )) || usage
    base_config="$(realpath -m -- "$1")"; shift
    [[ -f "$base_config" ]] || { echo "Map profile not found: $base_config" >&2; exit 1; }
    map="$(basename -- "$base_config")"
    map="${map%.json}"
    map="${map#demo-}"
    map="${map%.local}"
else
    map="$selector"
    [[ "$map" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || {
        echo "Invalid map identifier: $map" >&2; exit 2;
    }
    base_config="$project_root/configs/demo-${map}.local.json"
    [[ -f "$base_config" ]] || {
        echo "No calibrated local profile for map $map. Expected $base_config, or pass --config PATH." >&2
        exit 1
    }
fi
[[ "$map" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$ ]] || {
    echo "Invalid map identifier derived from profile: $map" >&2; exit 2;
}

source_root="${NEUSYMNAV_REBUILD_ROOT:-$(dirname -- "$project_root")/Rebuild_3DScene_OccuSG}"
source_root="$(realpath -m -- "$source_root")"
m23_binary="$source_root/build/native-m3/occupancy/standalone_sg_octomap_fixture_runner"
m4_binary="$source_root/build/native-m4-dude/occusg_dude_worker"
profile_dir="$project_root/.runtime/rebuild-rgbd-m1-m5-v1"
config_dir="$profile_dir/configs"
config="$config_dir/map-${map}.json"
mkdir -p "$config_dir"

"$project_root/.venv/bin/python" - "$base_config" "$config" "$source_root" "$m23_binary" "$m4_binary" <<'PY'
import hashlib, json, os, sys
from pathlib import Path

base, output, source_root, m23, m4 = map(Path, sys.argv[1:])
expected_m23 = "617477524aa81acb0a0a46575741497aa15ed9b095f8fd72f92e09a81043cdc6"
expected_m4 = "6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693"
expected_source = "60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0"

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

for path in (m23, m4):
    if not path.is_file() or not os.access(path, os.X_OK):
        raise SystemExit(f"missing executable Rebuild binary: {path}")
actual_m23, actual_m4 = sha256(m23), sha256(m4)
package = source_root / "src" / "standalone_sg"
files = sorted(package.rglob("*.py"))
if len(files) != 50:
    raise SystemExit(f"Rebuild Python source file count changed: expected 50, got {len(files)}")
digest = hashlib.sha256()
for path in files:
    digest.update(path.relative_to(package).as_posix().encode())
    digest.update(b"\0")
    digest.update(bytes.fromhex(sha256(path)))
actual_source = digest.hexdigest()
if (actual_m23, actual_m4, actual_source) != (expected_m23, expected_m4, expected_source):
    raise SystemExit("Rebuild source pin mismatch: "
        f"M23={actual_m23} M4={actual_m4} source={actual_source}")

data = json.loads(base.read_text())
if (not isinstance(data, dict) or "sensor_config" not in data
        or "floor" not in data or "episode" not in data):
    raise SystemExit(f"profile is missing required calibrated RGB-D fields: {base}")
if not data.get("sensor_config", {}).get("scene", {}).get("path"):
    raise SystemExit(f"profile is missing a simulator scene asset path: {base}")
data["profile"] = "rebuild-rgbd-m1-m5-v1"
data.setdefault("workers", {}).setdefault("sensor", {})["timeout_s"] = 60.0
data.setdefault("workers", {}).pop("region", None)
data.setdefault("workers", {})["room_pipeline"] = {
    "source_root": str(source_root),
    "m23_binary": {"path": str(m23), "sha256": actual_m23},
    "m4_binary": {"path": str(m4), "sha256": actual_m4},
    "resolution_m": 0.05,
    "backprojection_stride": 1,
    "min_depth_m": 0.1,
    "max_depth_m": 10.0,
    "max_range_m": 5.0,
    "ipc_timeout_s": 60.0,
    "m23_timeout_s": 15.0,
    "m4_timeout_s": 30.0,
}
output.parent.mkdir(parents=True, exist_ok=True)
tmp = output.with_suffix(output.suffix + ".tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
os.replace(tmp, output)
print(f"profile={data['profile']}")
print(f"config={output}")
print(f"m23_sha256={actual_m23}")
print(f"m4_sha256={actual_m4}")
print(f"source_tree_sha256={actual_source}")
PY

export NEUSYMNAV_DEMO_CONFIG="$config"
if [[ "${1:-}" == --preflight && $# == 1 ]]; then
    exec bash "$project_root/tools/run_local_demo.sh" --preflight
fi
(( $# <= 2 )) || usage
exec bash "$project_root/tools/run_local_demo.sh" "${1:-600}" \
    "${2:-runs/rebuild-rgbd-${map}-$(date +%Y%m%d-%H%M%S-%N)}"
