#!/usr/bin/env python3
"""
run_base_station.py -- Single Command Master Launcher for the Base Station (Rover alias).
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_SCRIPT = os.path.join(SCRIPT_DIR, '..', 'base_station', 'launch_base_station.py')

if __name__ == '__main__':
    if not os.path.exists(BASE_SCRIPT):
        print(f"❌ Error: Cannot find launch_base_station.py at {BASE_SCRIPT}")
        sys.exit(1)
    os.execv(sys.executable, [sys.executable, os.path.abspath(BASE_SCRIPT)] + sys.argv[1:])
