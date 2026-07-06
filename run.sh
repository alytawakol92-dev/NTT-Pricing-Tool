#!/usr/bin/env bash
# ============================================================
#  NTT Pricing Tool - one-click launcher (macOS / Linux)
#  Run:  ./run.sh   (first run sets up ~1-2 min, then opens the tool)
# ============================================================
set -e
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || PY=python
if ! command -v $PY >/dev/null 2>&1; then
  echo
  echo "  Python is not installed."
  echo "  Install Python 3.10+ from https://www.python.org/downloads/ and re-run."
  echo
  exit 1
fi

if [ ! -d .venv ]; then
  echo "Creating environment (first run only, please wait)..."
  $PY -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "Installing / updating components..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt

echo
echo "  Starting the NTT Pricing Tool..."
echo "  A browser window will open at http://127.0.0.1:5000"
echo "  Keep this terminal open while you use the tool. Press Ctrl+C to stop."
echo
python -m ntt_pricing.web
