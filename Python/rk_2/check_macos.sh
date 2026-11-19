#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo '=== Python ==='
python --version
echo '=== Unit & integration tests ==='
python -m pytest -v
if python -c 'import streamlit' >/dev/null 2>&1; then
  echo '=== Streamlit installed ==='
  python -c 'import streamlit; print("Streamlit",streamlit.__version__)'
else
  echo 'ERROR: Streamlit отсутствует — выполните pip install -r requirements.txt'
  exit 1
fi
echo '=== Original 13 CSV datasets ==='
python scripts_check.py --strict --check-reference
echo '=== Success ==='
