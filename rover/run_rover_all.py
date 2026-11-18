#!/usr/bin/env python3
"""
run_rover_all.py -- Single Command Master Launcher for the Rover Onboard ROS 2 Stack.
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_SCRIPT = os.path.join(SCRIPT_DIR, '..', 'run_rover_all.py')

if __name__ == '__main__':
    if not os.path.exists(ROOT_SCRIPT):
        print(f"❌ Error: Cannot find master run_rover_all.py at {ROOT_SCRIPT}")
        sys.exit(1)
    os.execv(sys.executable, [sys.executable, os.path.abspath(ROOT_SCRIPT)] + sys.argv[1:])
