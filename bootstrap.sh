#!/bin/sh
# Create the virtualenv and install the dependencies, then run the checks. Safe to re-run.
#   ./bootstrap.sh            set up and test
#   ./bootstrap.sh --no-test  set up only
set -eu
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)'; then
    echo "gcg-toolkit needs Python 3.14 or newer (set PYTHON=/path/to/python3.14)" >&2
    exit 1
fi
[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
if [ "${1:-}" != "--no-test" ]; then
    .venv/bin/python -m pytest -q
    .venv/bin/python -m mypy tools shared
fi
echo "ready: try  .venv/bin/python -m tools.gundam_collection.cli --help"
