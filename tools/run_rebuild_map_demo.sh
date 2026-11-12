#!/usr/bin/env bash
# Reproducible opt-in Rebuild M4 + M5 room backend on the local map profile.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if (( $# < 1 || $# > 3 )); then
    echo 'Usage: bash tools/run_rebuild_map_demo.sh MAP [duration_seconds|--preflight] [new_output_directory]' >&2
    exit 2
fi
map="$1"; shift
if [[ ! "$map" =~ ^0080[0-9]$ ]]; then
    echo "Rebuild room demo requires a calibrated local map such as 00805; got: $map" >&2
    exit 2
fi
base_config="$project_root/configs/demo-${map}.local.json"
if [[ ! -f "$base_config" ]]; then
    echo "Map $map has not been calibrated; expected $base_config" >&2
    exit 1
fi
source_root="/home/kiettran05/Desktop/test_Room_segmentation/Rebuild_3DScene_OccuSG"
worker="$source_root/build/native-m4-dude/occusg_dude_worker"
config_dir="$project_root/.runtime/rebuild-backend-20261102/configs"
pin_dir="$project_root/.runtime/rebuild-backend-20261102/worker"
config="$config_dir/map-${map}.json"
mkdir -p "$config_dir" "$pin_dir"
"$project_root/.venv/bin/python" - "$base_config" "$config" "$source_root" "$worker" "$pin_dir/source-pins.json" <<'PY'
import hashlib, json, os, sys
from pathlib import Path
base, output, source_root, worker, pin_file = map(Path, sys.argv[1:])
expected_worker = "6ff1fb5ba2275c9311004bcb7bd41995a7f4c64c76107dda8fba785d964a3693"
expected_source = "60aebf8a0433afa23dbdf94e6ed8415347b03e58464a0f7a71c3b8c7d07b0da0"
if not worker.is_file() or not os.access(worker, os.X_OK):
    raise SystemExit(f"missing executable Rebuild worker: {worker}")
digest = hashlib.sha256(worker.read_bytes()).hexdigest()
package = source_root / "src" / "standalone_sg"
h = hashlib.sha256()
source_files = sorted(package.rglob("*.py"))
if not source_files:
    raise SystemExit(f"missing Rebuild Python source package: {package}")
for path in source_files:
    h.update(path.relative_to(package).as_posix().encode())
    h.update(b"\0")
    h.update(bytes.fromhex(hashlib.sha256(path.read_bytes()).hexdigest()))
source_digest = h.hexdigest()
if digest != expected_worker or source_digest != expected_source:
    raise SystemExit(f"Rebuild pin mismatch: worker={digest} source={source_digest}")
data = json.loads(base.read_text())
data.setdefault("workers", {})["region"] = {
    "backend": "rebuild_m4_m5",
    "source_root": str(source_root),
    "executable": {"path": str(worker), "sha256": digest},
    "timeout_s": 30.0,
}
output.parent.mkdir(parents=True, exist_ok=True)
tmp = output.with_suffix(output.suffix + ".tmp")
tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
os.replace(tmp, output)
pin_file.write_text(json.dumps({"worker_path": str(worker), "worker_sha256": digest,
    "source_root": str(source_root), "python_file_count": len(source_files),
    "source_tree_sha256": source_digest,
    "preprocessing_policy": "source"}, indent=2, sort_keys=True) + "\n")
print(f"config={output}")
print(f"worker_sha256={digest}")
print(f"source_tree_sha256={source_digest}")
PY
export NEUSYMNAV_DEMO_CONFIG="$config"
if [[ "${1:-}" == --preflight && $# == 1 ]]; then
    exec bash "$project_root/tools/run_local_demo.sh" --preflight
fi
if (( $# > 2 )); then
    echo 'Usage: bash tools/run_rebuild_map_demo.sh MAP [duration_seconds] [new_output_directory]' >&2
    exit 2
fi
duration="${1:-600}"
out="${2:-runs/rebuild-${map}-$(date +%Y%m%d-%H%M%S-%N)}"
exec bash "$project_root/tools/run_local_demo.sh" "$duration" "$out"
