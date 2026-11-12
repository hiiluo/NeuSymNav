#!/usr/bin/env bash
# Source only in the dedicated probe child, after providing the private library directory.
source "$(dirname "${BASH_SOURCE[0]}")/../../../.runtime/hydra_ws/env.sh"
export LD_LIBRARY_PATH="${NEUSYMNAV_GVD_PROBE_LIBDIR:?set probe library directory}:${LD_LIBRARY_PATH}"
