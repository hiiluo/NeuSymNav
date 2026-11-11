#!/usr/bin/env bash
set -eo pipefail
setup_script="${1:?Hydra setup script is required}"
shift
source "$setup_script"
set -u
exec "$@"
