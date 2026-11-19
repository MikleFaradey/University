#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -m pip install -e . pytest import-linter
"$PYTHON_BIN" -m pytest -q
lint-imports
"$PYTHON_BIN" scripts/run_demo.py
printf '\nAll local checks passed.\n'
