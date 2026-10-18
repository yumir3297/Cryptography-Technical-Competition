#!/bin/sh
# Keep only this validation process awake on macOS. Never change protocol clocks.
set -eu
zjj_repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$zjj_repo_root"
zjj_python=${ZJJ_PYTHON:-python3}
zjj_output=${1:-integration-evidence/joint-final}
if [ "$(uname -s)" = Darwin ]; then
    exec /usr/bin/caffeinate -i env -u PYTHONHOME "$zjj_python" integration-evidence/diagnostic_runner.py "$zjj_output"
fi
exec env -u PYTHONHOME "$zjj_python" integration-evidence/diagnostic_runner.py "$zjj_output"
