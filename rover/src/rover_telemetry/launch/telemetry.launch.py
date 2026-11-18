from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    base_ip_arg = DeclareLaunchArgument(
        'base_ip',
        default_value='127.0.0.1',
        description='Base station IP address for Network UDP telemetry'
    )
    base_port_arg = DeclareLaunchArgument(
        'base_port',
        default_value='9003',
        description='Base station UDP status/telemetry port'
    )
    rate_hz_arg = DeclareLaunchArgument(
        'rate_hz',
        default_value='5.0',
        description='Telemetry broadcast rate in Hz'
    )
    xbee_port_arg = DeclareLaunchArgument(
        'xbee_port',
        default_value='/dev/rover_900mhz',
        description='XBee serial port device'
    )
    enable_xbee_arg = DeclareLaunchArgument(
        'enable_xbee',
        default_value='false',
        description='Enable or disable direct XBee RF serial broadcast (default false: routed through rx_node)'
    )
    enable_udp_arg = DeclareLaunchArgument(
        'enable_udp',
        default_value='true',
        description='Enable or disable Network UDP broadcast'
    )

    telemetry_node = Node(
        package='rover_telemetry',
        executable='telemetry_node',
        name='rover_telemetry_node',
        output='screen',
        parameters=[{
            'base_ip': LaunchConfiguration('base_ip'),
            'base_port': LaunchConfiguration('base_port'),
            'rate_hz': LaunchConfiguration('rate_hz'),
            'xbee_port': LaunchConfiguration('xbee_port'),
            'enable_xbee': LaunchConfiguration('enable_xbee'),
            'enable_udp': LaunchConfiguration('enable_udp'),
        }]
    )

    return LaunchDescription([
        base_ip_arg,
        base_port_arg,
        rate_hz_arg,
        xbee_port_arg,
        enable_xbee_arg,
        enable_udp_arg,
        telemetry_node,
    ])
