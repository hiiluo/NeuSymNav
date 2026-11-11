#!/usr/bin/env bash
# Source only inside the branch2 Hydra child environment.
NEUSYMNAV_HYDRA_WS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/jazzy/setup.bash
source "${NEUSYMNAV_HYDRA_WS}/install/setup.bash"
export PATH="${NEUSYMNAV_HYDRA_WS}/.venv/bin:${PATH}"
export PYTHONPATH="${NEUSYMNAV_HYDRA_WS}/python/site-packages${PYTHONPATH:+:${PYTHONPATH}}"
export LD_LIBRARY_PATH="${NEUSYMNAV_HYDRA_WS}/install/hydra/lib:${NEUSYMNAV_HYDRA_WS}/install/spark_dsg/lib:${NEUSYMNAV_HYDRA_WS}/install/spatial_hash/lib:${NEUSYMNAV_HYDRA_WS}/install/teaserpp/lib:${NEUSYMNAV_HYDRA_WS}/install/kimera_pgmo/lib:${NEUSYMNAV_HYDRA_WS}/install/kimera_rpgo/lib:${NEUSYMNAV_HYDRA_WS}/install/config_utilities/lib:${NEUSYMNAV_HYDRA_WS}/sysroot/opt/ros/jazzy/lib/x86_64-linux-gnu:${NEUSYMNAV_HYDRA_WS}/sysroot/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
export CMAKE_PREFIX_PATH="${NEUSYMNAV_HYDRA_WS}/install/hydra:${NEUSYMNAV_HYDRA_WS}/install/spark_dsg:${NEUSYMNAV_HYDRA_WS}/install/spatial_hash:${NEUSYMNAV_HYDRA_WS}/install/teaserpp:${NEUSYMNAV_HYDRA_WS}/install/kimera_pgmo:${NEUSYMNAV_HYDRA_WS}/install/kimera_rpgo:${NEUSYMNAV_HYDRA_WS}/install/config_utilities:${NEUSYMNAV_HYDRA_WS}/sysroot/opt/ros/jazzy:${NEUSYMNAV_HYDRA_WS}/sysroot/usr:/opt/ros/jazzy:/usr${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"
export CMAKE_CXX_FLAGS="-isystem ${NEUSYMNAV_HYDRA_WS}/sysroot/usr/include -isystem ${NEUSYMNAV_HYDRA_WS}/sysroot/opt/ros/jazzy/include${CMAKE_CXX_FLAGS:+ ${CMAKE_CXX_FLAGS}}"
