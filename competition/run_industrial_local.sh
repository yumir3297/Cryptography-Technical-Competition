#!/bin/sh
# One owned local simulator installation. Never initialize at service startup.
set -eu
: "${ZJJ_PYTHON:?Set ZJJ_PYTHON to a Python environment with the repository requirements}"
zjj_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$zjj_root"
if [ "$(uname -s)" = Darwin ]; then
    exec /usr/bin/caffeinate -i env -u PYTHONHOME "$ZJJ_PYTHON" -m competition.application.local_runtime --config "$@"
fi
exec env -u PYTHONHOME "$ZJJ_PYTHON" -m competition.application.local_runtime --config "$@"
