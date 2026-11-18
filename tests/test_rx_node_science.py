#!/usr/bin/env python3
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import UInt8MultiArray, String
from xbee_teleop.link import pack_science, pack_mode

def test_rx_science_integration():
    rclpy.init()
    test_node = Node('test_science_listener')

    received_science = []
    received_mode = []

    def on_sci(msg):
        received_science.append(list(msg.data))

    def on_mode(msg):
        received_mode.append(msg.data)

    test_node.create_subscription(UInt8MultiArray, '/science/actuator_cmd', on_sci, 10)
    test_node.create_subscription(String, '/rover/mode', on_mode, 10)

    # Instantiate RxNode with dummy serial port (it will continue running UDP)
    from xbee_teleop.rx_node import RxNode
    rx = RxNode()

    # Simulate packet received via UDP
    sci_pkt = pack_science(1, 1, 0, 1, 0, 1, 1, 90)
    rx.process_packet(sci_pkt, source='UDP')

    mode_pkt = pack_mode(2, 1) # Autonomous
    rx.process_packet(mode_pkt, source='UDP')

    # Spin briefly to allow ROS 2 intra-process or inter-thread delivery
    start = time.time()
    while time.time() - start < 1.0:
        rclpy.spin_once(test_node, timeout_sec=0.1)
        rclpy.spin_once(rx, timeout_sec=0.1)
        if received_science and received_mode:
            break

    print("Received science commands:", received_science)
    print("Received mode commands:", received_mode)

    assert len(received_science) > 0, "No science command received on topic /science/actuator_cmd"
    assert received_science[-1] == [1, 0, 1, 0, 1, 1, 90], f"Mismatch in science payload: {received_science[-1]}"

    assert len(received_mode) > 0, "No mode command received on topic /rover/mode"
    assert received_mode[-1] == "AUTONOMOUS", f"Mismatch in mode payload: {received_mode[-1]}"

    print("✅ RxNode ROS 2 topic publishing verified successfully!")
    rx.destroy_node()
    test_node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    test_rx_science_integration()
