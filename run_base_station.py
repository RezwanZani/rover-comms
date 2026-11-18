#!/usr/bin/env python3
"""
run_base_station.py -- Single Command Master Launcher for the Base Station.

Builds the web frontend application and launches all Base Station components in sequence:
  1. Compiles React production bundle (pnpm build -> dist/)
  2. Base Master Hub (XBee Radio & Priority Packet Router on UDP 9001/9002/9003)
  3. Rover GUI Backend (FastAPI / WebSocket Server on port 8765)
  4. Prebuilt Web Frontend Dashboard (Vite Preview on port 5173)
  5. Teleoperation GUI (PyQt5 Gamepad / Keyboard Teleop & Science Panel)

Usage:
  python3 run_base_station.py
  python3 run_base_station.py /tmp/ttyV0
  python3 run_base_station.py --port /dev/ttyUSB0
  python3 run_base_station.py --dev        # Use live dev server instead of prebuilt
  python3 run_base_station.py --no-build   # Skip rebuilding web assets
  python3 run_base_station.py --no-teleop  # Headless mode (no PyQt5 GUI)
"""

import os
import sys

# Locate launch_base_station.py relative to this script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_SCRIPT = os.path.join(SCRIPT_DIR, 'base_station', 'launch_base_station.py')

if not os.path.exists(BASE_SCRIPT):
    # Fallback if run from inside base_station/
    BASE_SCRIPT = os.path.join(SCRIPT_DIR, 'launch_base_station.py')

if not os.path.exists(BASE_SCRIPT):
    # Fallback if run from inside rover/
    BASE_SCRIPT = os.path.join(SCRIPT_DIR, '..', 'base_station', 'launch_base_station.py')

if __name__ == '__main__':
    if not os.path.exists(BASE_SCRIPT):
        print(f"❌ Error: Cannot find launch_base_station.py at {BASE_SCRIPT}")
        sys.exit(1)
    os.execv(sys.executable, [sys.executable, os.path.abspath(BASE_SCRIPT)] + sys.argv[1:])
