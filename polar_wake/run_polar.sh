#!/usr/bin/env bash
# One-command launcher: starts the dashboard, then the always-on Polar listener.
set -e
cd "$(dirname "$0")"

echo "Starting Polar dashboard on http://localhost:5055 ..."
( cd ../polar_dashboard && python3 -m venv .venv 2>/dev/null || true; \
  source .venv/bin/activate; pip install -q -r requirements.txt; \
  python3 app.py & )

sleep 2
open "http://localhost:5055" 2>/dev/null || true

echo "Starting Polar listener (say 'Polar' or double-clap) ..."
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
pip install -q -r requirements.txt
python3 polar_listen.py
