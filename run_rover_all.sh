#!/usr/bin/env bash
# =============================================================================
# run_rover_all.sh -- Master Runner for Rover Onboard ROS 2 Stack
#
# Launches all rover nodes:
#   1. rx_node         (Dual-redundant receiver for motion, mode, science & RTCM)
#   2. science_node    (Arduino Mega 2560 serial bridge)
#   3. telemetry_node  (Sensor telemetry aggregator & broadcaster)
#   4. rover_gps_node  (Quectel LC29H RTK GPS driver)
#
# Usage:
#   ./run_rover_all.sh
#   ./run_rover_all.sh xbee_port:=/dev/ttyUSB0 arduino_port:=/dev/ttyACM0 base_ip:=192.168.1.50
#   ./run_rover_all.sh enable_gps:=false
# =============================================================================

set -e

SCRIPT_DIR="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
ROVER_DIR="$SCRIPT_DIR/rover"

# Source ROS 2 core environment
if [ -f "/opt/ros/jazzy/setup.bash" ]; then
    source /opt/ros/jazzy/setup.bash
elif [ -f "/opt/ros/humble/setup.bash" ]; then
    source /opt/ros/humble/setup.bash
elif [ -f "/opt/ros/iron/setup.bash" ]; then
    source /opt/ros/iron/setup.bash
else
    echo "⚠️ ROS 2 installation not found in /opt/ros! Please source your ROS 2 environment first."
fi

# Source workspace install
if [ -f "$ROVER_DIR/install/setup.bash" ]; then
    source "$ROVER_DIR/install/setup.bash"
else
    echo "⚙️ Rover workspace install/setup.bash not found. Building workspace..."
    cd "$ROVER_DIR"
    colcon build --symlink-install
    source "$ROVER_DIR/install/setup.bash"
    cd "$SCRIPT_DIR"
fi

echo "=========================================================="
echo "  AAUB ROVER71 -- ONBOARD ROS 2 MASTER LAUNCHER"
echo "=========================================================="

exec ros2 launch xbee_teleop rover_all.launch.py "$@"
