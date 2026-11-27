#!/usr/bin/env bash
# Build and test the patched binding separately from the installed Hydra runtime.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.."
tools_dir="$PWD/tools/native/hydra_object_journal"
workspace="$PWD/.runtime/hydra_ws"
output="$(realpath -m -- "${1:?Pass a new build output directory within the workspace}")"
jobs="${JOBS:-3}"
case "$output" in
  "$PWD"/*) ;;
  *) echo "Build output must be within $PWD" >&2; exit 2 ;;
esac

hydra_commit=2e58a35baea629eee8838409771876acff015daf
nanoflann_commit=9a653cb243db6a09c94f833b28732b62f033e2b5
test "$(git -C "$workspace/src/hydra" rev-parse HEAD)" = "$hydra_commit"
test "$(git -C "$workspace/vendor/nanoflann" rev-parse HEAD)" = "$nanoflann_commit"
test -z "$(git -C "$workspace/vendor/nanoflann" status --short)"

mkdir -- "$output"
mkdir -- "$output/source"
git -C "$workspace/src/hydra" archive "$hydra_commit" | tar -x -C "$output/source"
patch --batch -d "$output/source" -p1 < "$tools_dir/hydra.patch"
set +u
source "$workspace/env.sh"
set -u
cmake -S "$output/source" -B "$output/build" \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="$CMAKE_CXX_FLAGS" \
  -DFETCHCONTENT_FULLY_DISCONNECTED=ON -DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON \
  -DFETCHCONTENT_SOURCE_DIR_NANOFLANN="$workspace/vendor/nanoflann" \
  -DPython3_EXECUTABLE="$workspace/.venv/bin/python" -DBUILD_TESTING=OFF \
  -DHYDRA_ENABLE_EVAL=OFF -DHYDRA_ENABLE_GNN=OFF -DHYDRA_ENABLE_PYTHON=ON \
  -DHYDRA_ENABLE_ROS_INSTALL_LAYOUT=ON \
  -DNEUSYMNAV_OBJECT_JOURNAL_TEST="$tools_dir/owner_test.cpp"
cmake --build "$output/build" --parallel "$jobs" --target _hydra_bindings hydra_object_journal_test
bash "$tools_dir/probe-build.sh" "$output/build" "$output"
