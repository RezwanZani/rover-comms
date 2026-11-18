#!/usr/bin/env bash
# =============================================================================
# run_base_station.sh -- Master Runner for Base Station Communications & GUI
#
# Launches all base station processes in supervisor mode:
#   1. Base Master Hub (base_master.py)       -- Sole owner of Base XBee radio
#   2. Web GUI Backend (rover-gui/backend)    -- WebSocket server & telemetry handler
#   3. Web GUI Frontend (rover-gui/frontend)  -- Vite React Mission Control Dashboard
#   4. Teleop GUI (run_teleop_base)           -- Gamepad / WASD teleoperation
#
# Usage:
#   ./run_base_station.sh
#   ./run_base_station.sh --port /tmp/ttyV0
#   ./run_base_station.sh --gps
#   ./run_base_station.sh --no-teleop
# =============================================================================

set -e

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT_DIR="$(dirname "$SCRIPT_PATH")"
BASE_DIR="$ROOT_DIR/base_station"

cd "$BASE_DIR"
exec python3 "$BASE_DIR/launch_base_station.py" "$@"
