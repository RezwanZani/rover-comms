#!/usr/bin/env bash
# run_base_master.sh -- Starts the central Base Station communications hub
cd "$(dirname "$0")"
PORT="${1:-}"

if [ -n "$PORT" ]; then
    python3 base_master.py "$PORT"
else
    python3 base_master.py
fi
