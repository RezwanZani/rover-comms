#!/usr/bin/env python3
"""
rover_all.launch.py -- Master ROS 2 Launch File for Rover Onboard Stack.

Launches all rover packages and nodes simultaneously:
  1. xbee_teleop / rx_node         -- Dual-redundant XBee & UDP motion, mode & science receiver
  2. xbee_teleop / science_node    -- Arduino Mega 2560 serial bridge (5 motors, LED, servo)
  3. rover_telemetry / telemetry_node -- Sensor telemetry aggregator & multi-channel broadcaster
  4. gps_data / rover_gps_node      -- LC29H RTK GPS driver with RTCM injection

Usage:
  ros2 launch xbee_teleop rover_all.launch.py
  ros2 launch xbee_teleop rover_all.launch.py xbee_port:=/dev/ttyUSB0 base_ip:=192.168.1.50
  ros2 launch xbee_teleop rover_all.launch.py enable_gps:=false
"""

import os
import sys
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

# Import shared comms configuration if available
def _find_comms_config():
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(cur, 'comms_config.py')):
            return cur
        if os.path.isfile(os.path.join(cur, 'src', 'comms_config.py')):
            return os.path.join(cur, 'src')
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    ws_fallback = os.path.expanduser('~/Desktop/rover_com/rover/src')
    if os.path.isfile(os.path.join(ws_fallback, 'comms_config.py')):
        return ws_fallback
    return None

_cfg_path = _find_comms_config()
if _cfg_path and _cfg_path not in sys.path:
    sys.path.insert(0, _cfg_path)

try:
    from comms_config import (
        TELEOP_XBEE_PORT,
        XBEE_BAUD_RATE,
        SCIENCE_ARDUINO_PORT,
        SCIENCE_ARDUINO_BAUD,
        ROVER_UDP_LISTEN_PORT,
        BASE_STATION_IP,
        BASE_STATION_TELEMETRY_PORT,
    )
except ImportError:
    TELEOP_XBEE_PORT = '/dev/ttyUSB0'
    XBEE_BAUD_RATE = 115200
    SCIENCE_ARDUINO_PORT = '/dev/ttyACM0'
    SCIENCE_ARDUINO_BAUD = 9600
    ROVER_UDP_LISTEN_PORT = 8888
    BASE_STATION_IP = '127.0.0.1'
    BASE_STATION_TELEMETRY_PORT = 9003


def generate_launch_description():
    # -------------------------------------------------------------
    # Launch Arguments
    # -------------------------------------------------------------
    xbee_port_arg = DeclareLaunchArgument(
        'xbee_port',
        default_value=TELEOP_XBEE_PORT,
        description='Serial port for Rover XBee 900MHz radio'
    )
    xbee_baud_arg = DeclareLaunchArgument(
        'xbee_baud',
        default_value=str(XBEE_BAUD_RATE),
        description='Baud rate for Rover XBee 900MHz radio'
    )
    arduino_port_arg = DeclareLaunchArgument(
        'arduino_port',
        default_value=SCIENCE_ARDUINO_PORT,
        description='Serial port for Science Arduino Mega 2560'
    )
    arduino_baud_arg = DeclareLaunchArgument(
        'arduino_baud',
        default_value=str(SCIENCE_ARDUINO_BAUD),
        description='Baud rate for Science Arduino Mega 2560'
    )
    gps_port_arg = DeclareLaunchArgument(
        'gps_port',
        default_value='/dev/rover_rtk',
        description='Serial port for Quectel LC29H RTK GPS module'
    )
    gps_baud_arg = DeclareLaunchArgument(
        'gps_baud',
        default_value='115200',
        description='Baud rate for Quectel LC29H RTK GPS module'
    )
    base_ip_arg = DeclareLaunchArgument(
        'base_ip',
        default_value=BASE_STATION_IP,
        description='Base station LAN/loopback IP address for telemetry uplink'
    )
    base_port_arg = DeclareLaunchArgument(
        'base_port',
        default_value=str(BASE_STATION_TELEMETRY_PORT),
        description='Base station UDP telemetry receiving port'
    )
    udp_port_arg = DeclareLaunchArgument(
        'udp_port',
        default_value=str(ROVER_UDP_LISTEN_PORT),
        description='UDP port rover listens on for dual-redundant Wi-Fi uplink'
    )

    # Enable / Disable Subsystem Flags
    enable_rx_arg = DeclareLaunchArgument(
        'enable_rx',
        default_value='true',
        description='Launch xbee_teleop rx_node (Dual-redundant receiver)'
    )
    enable_science_arg = DeclareLaunchArgument(
        'enable_science',
        default_value='true',
        description='Launch xbee_teleop science_node (Arduino Mega 2560 bridge)'
    )
    enable_telemetry_arg = DeclareLaunchArgument(
        'enable_telemetry',
        default_value='true',
        description='Launch rover_telemetry node (Sensor aggregator & broadcaster)'
    )
    enable_gps_arg = DeclareLaunchArgument(
        'enable_gps',
        default_value='true',
        description='Launch gps_data rover_gps_node (RTK GPS driver)'
    )

    # -------------------------------------------------------------
    # Nodes
    # -------------------------------------------------------------

    # 1. Receiver Node (Comms Master): Drive, Arm, Science & Mode Demultiplexer
    rx_node = Node(
        package='xbee_teleop',
        executable='rx_node',
        name='rx_node',
        output='screen',
        parameters=[{
            'port': LaunchConfiguration('xbee_port'),
            'baud': LaunchConfiguration('xbee_baud'),
            'udp_port': LaunchConfiguration('udp_port'),
            'cmd_timeout': 0.5,
            'cmd_vel_topic': 'cmd_vel',
            'arm_vel_topic': 'arm_vel',
        }],
        condition=IfCondition(LaunchConfiguration('enable_rx'))
    )

    # 2. Science Node: Arduino Mega 2560 Serial Bridge (5 motors, LED, Servo)
    science_node = Node(
        package='xbee_teleop',
        executable='science_node',
        name='science_node',
        output='screen',
        parameters=[{
            'port': LaunchConfiguration('arduino_port'),
            'baud': LaunchConfiguration('arduino_baud'),
            'cmd_topic': '/science/actuator_cmd',
            'status_topic': '/science/actuator_status',
        }],
        condition=IfCondition(LaunchConfiguration('enable_science'))
    )

    # 3. Rover Telemetry Node: Aggregates all sensor topics & broadcasts to base station
    telemetry_node = Node(
        package='rover_telemetry',
        executable='telemetry_node',
        name='rover_telemetry_node',
        output='screen',
        parameters=[{
            'base_ip': LaunchConfiguration('base_ip'),
            'base_port': LaunchConfiguration('base_port'),
            'xbee_port': LaunchConfiguration('xbee_port'),
            'rate_hz': 5.0,
            'enable_udp': True,
            'enable_xbee': False,  # Downlink is routed through rx_node's telemetry_tx topic
            'enable_sim_fallback': True,
        }],
        condition=IfCondition(LaunchConfiguration('enable_telemetry'))
    )

    # 4. Rover GPS Node: Injects RTCM from /rtcm topic into LC29H GPS module & publishes /gps
    gps_node = Node(
        package='gps_data',
        executable='gps_node',
        name='rover_gps_node',
        output='screen',
        parameters=[{
            'gps_port': LaunchConfiguration('gps_port'),
            'gps_baud': LaunchConfiguration('gps_baud'),
            'frame_id': 'gps_link',
        }],
        condition=IfCondition(LaunchConfiguration('enable_gps'))
    )

    startup_msg = LogInfo(
        msg="\n=======================================================\n"
            "🚀 ROVER ALL PACKAGES & NODES LAUNCHING...\n"
            "   - xbee_teleop/rx_node       (Dual-Redundant Link Master)\n"
            "   - xbee_teleop/science_node  (Arduino Mega 2560 Bridge)\n"
            "   - rover_telemetry           (State Aggregator & UDP)\n"
            "   - gps_data/rover_gps_node   (RTK GPS Driver)\n"
            "=======================================================\n"
    )

    return LaunchDescription([
        # Arguments
        xbee_port_arg,
        xbee_baud_arg,
        arduino_port_arg,
        arduino_baud_arg,
        gps_port_arg,
        gps_baud_arg,
        base_ip_arg,
        base_port_arg,
        udp_port_arg,
        enable_rx_arg,
        enable_science_arg,
        enable_telemetry_arg,
        enable_gps_arg,
        # Startup Banner
        startup_msg,
        # Nodes
        rx_node,
        science_node,
        telemetry_node,
        gps_node,
    ])
