#!/usr/bin/env python3
"""
run_rover_all.py -- Single Command Master Launcher for the Rover Onboard ROS 2 Stack.

Launches all rover nodes:
  1. rx_node         (Dual-redundant receiver for motion, mode, science & RTCM)
  2. science_node    (Arduino Mega 2560 serial bridge)
  3. telemetry_node  (Sensor telemetry aggregator & broadcaster)
  4. rover_gps_node  (Quectel LC29H RTK GPS driver)

Usage:
  python3 run_rover_all.py
  python3 run_rover_all.py xbee_port:=/dev/ttyUSB0 arduino_port:=/dev/ttyACM0
  python3 run_rover_all.py enable_gps:=false
"""

import os
import sys
import subprocess
import shutil

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROVER_DIR = os.path.join(SCRIPT_DIR, 'rover') if os.path.exists(os.path.join(SCRIPT_DIR, 'rover')) else SCRIPT_DIR


def find_ros2_setup():
    for dist in ('jazzy', 'humble', 'iron'):
        p = f"/opt/ros/{dist}/setup.bash"
        if os.path.isfile(p):
            return p
    return None


def main():
    ros_setup = find_ros2_setup()
    if not ros_setup:
        print("⚠️ Warning: ROS 2 core environment not found under /opt/ros/{jazzy,humble,iron}!")

    install_setup = os.path.join(ROVER_DIR, 'install', 'setup.bash')

    # Build workspace if setup.bash is missing
    if not os.path.isfile(install_setup):
        print(f"⚙️ Rover workspace install/setup.bash not found. Building workspace at {ROVER_DIR}...")
        colcon_cmd = ["colcon", "build", "--symlink-install"]
        if ros_setup:
            full_cmd = f"source {ros_setup} && cd {ROVER_DIR} && colcon build --symlink-install"
            subprocess.run(["bash", "-c", full_cmd], check=True)
        else:
            subprocess.run(colcon_cmd, cwd=ROVER_DIR, check=True)

    print("=" * 60)
    print("  AAUB ROVER71 -- ONBOARD ROS 2 MASTER LAUNCHER")
    print("=" * 60)

    # Forward all arguments to ros2 launch
    args_str = " ".join(f'"{a}"' for a in sys.argv[1:])
    setup_commands = []
    if ros_setup:
        setup_commands.append(f"source {ros_setup}")
    if os.path.isfile(install_setup):
        setup_commands.append(f"source {install_setup}")
    setup_commands.append(f"exec ros2 launch xbee_teleop rover_all.launch.py {args_str}")

    exec_cmd = " && ".join(setup_commands)
    subprocess.run(["bash", "-c", exec_cmd])


if __name__ == '__main__':
    main()
