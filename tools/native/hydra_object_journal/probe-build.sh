#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.."
workspace="$PWD/.runtime/hydra_ws"
build="$(realpath -- "${1:?Pass the patched build directory}")"
output="$(realpath -- "${2:?Pass the output directory}")"
shift 2
set +u
source "$workspace/env.sh"
set -u
export LD_LIBRARY_PATH="$build:${LD_LIBRARY_PATH:-}"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=2

"$build/hydra_object_journal_test"
binding_name="_hydra_bindings$("$workspace/.venv/bin/python" -c 'import sysconfig; print(sysconfig.get_config_var("EXT_SUFFIX"))')"
package="$output/journal-python/hydra_python"
mkdir -p -- "$package"
(
  cd -- "$workspace/python/site-packages/hydra_python"
  find . -name '*.py' -type f -exec cp --parents -- '{}' "$package/" \;
)
cp -- "$build/python/$binding_name" "$package/$binding_name"
export PYTHONPATH="$output/journal-python:$PWD/src:$PWD:${PYTHONPATH:-}"
sha256sum "$build/libhydra.so" "$package/$binding_name" \
  tools/native/hydra_object_journal/{hydra.patch,owner_test.cpp,probe.py} > "$output/journal-build.sha256"
"$workspace/.venv/bin/python" tools/native/hydra_object_journal/probe.py --frames 18 \
  --expected-library "$build/libhydra.so" --output "$output" "$@"
