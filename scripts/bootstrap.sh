#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

if [ -f ".venv/Scripts/activate" ]; then
  # Windows-style venv layout under Git Bash / MSYS
  # shellcheck disable=SC1091
  source .venv/Scripts/activate
else
  # POSIX-style venv layout
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

python -m pip install --upgrade pip
pip install -r requirements.txt

if [ -f "requirements-dev.txt" ]; then
  pip install -r requirements-dev.txt
fi

mkdir -p data/incoming data/parsed data/output

if [ "${GENERATE_SAMPLE_DATA:-0}" = "1" ] && [ -f "scripts/generate_sample_data.py" ]; then
  python scripts/generate_sample_data.py
fi

echo "Bootstrap complete."