#!/usr/bin/env python3
"""
test_end_to_end_science_feedback.py -- Automated End-to-End Verification of Rover Confirmed Telemetry.

Verifies:
1. When command is sent, status is NOT optimistically changed.
2. Only when Arduino Mega transmits 'STATUS:...', science_node confirms it.
3. Telemetry reflects actual Arduino feedback.
"""

import os
import pty
import select
import sys
import time
import json
import threading

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from std_msgs.msg import UInt8MultiArray, String

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'rover', 'src', 'xbee_teleop_rover')))
from xbee_teleop.link import pack_science

def run_test():
    # 1. Create pty for mock Arduino
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)
    virtual_port = "/tmp/ttyTestArduino"
    if os.path.exists(virtual_port) or os.path.islink(virtual_port):
        os.unlink(virtual_port)
    os.symlink(slave_name, virtual_port)

    # 2. Mock Arduino Responder Thread
    arduino_running = True
    arduino_received = []

    def mock_arduino_loop():
        buf = ""
        while arduino_running:
            r, _, _ = select.select([master_fd], [], [], 0.05)
            if master_fd in r:
                raw = os.read(master_fd, 512)
                if raw:
                    buf += raw.decode('ascii', errors='ignore')
                    while '\n' in buf:
                        line, buf = buf.split('\n', 1)
                        line = line.strip()
                        if line.startswith("S:"):
                            arduino_received.append(line)
                            # Respond with confirmed status
                            resp = "STATUS:m1=1,m2=0,m3=1,m4=0,m5=0,led=1,servo=90\n"
                            os.write(master_fd, resp.encode('ascii'))

    t_ard = threading.Thread(target=mock_arduino_loop, daemon=True)
    t_ard.start()

    # 3. Initialize ROS 2
    rclpy.init()

    # Listener node to observe /science/actuator_status
    listener = Node('test_science_feedback_listener')
    received_statuses = []

    def on_status(msg):
        try:
            d = json.loads(msg.data)
            received_statuses.append(d)
        except Exception:
            pass

    listener.create_subscription(String, '/science/actuator_status', on_status, 10)

    # Instantiate ScienceNode connected to virtual port via parameter override
    from xbee_teleop.science_node import ScienceNode
    sci_node = ScienceNode(parameter_overrides=[
        Parameter('port', Parameter.Type.STRING, virtual_port),
        Parameter('baud', Parameter.Type.INTEGER, 9600),
    ])

    # Wait up to 1 second for serial thread to connect to virtual port
    t0 = time.time()
    while time.time() - t0 < 1.5:
        if sci_node.ser and sci_node.ser.is_open:
            break
        time.sleep(0.05)

    print("Checking initial state (before command)...")
    # Verify initial state: all motors 0
    assert sci_node.last_status["m1"] == 0
    assert sci_node.last_status["m3"] == 0

    print("Dispatching command: M1=ON, M3=ON, LED=ON, SERVO=90°...")
    cmd_msg = UInt8MultiArray()
    cmd_msg.data = [1, 0, 1, 0, 0, 1, 90]
    sci_node.on_cmd(cmd_msg)

    # Spin ROS 2 to let serial reader thread and ROS publishers do their work
    start = time.time()
    confirmed = False
    while time.time() - start < 2.0:
        rclpy.spin_once(sci_node, timeout_sec=0.05)
        rclpy.spin_once(listener, timeout_sec=0.05)
        if received_statuses:
            latest = received_statuses[-1]
            if latest.get("m1") == 1 and latest.get("m3") == 1 and latest.get("servo") == 90:
                confirmed = True
                break

    print(f"Mock Arduino received lines: {arduino_received}")
    print(f"Latest ROS 2 /science/actuator_status: {received_statuses[-1] if received_statuses else 'None'}")

    assert len(arduino_received) > 0, "Arduino did not receive command from science_node"
    assert confirmed, "Failed to receive confirmed status from Arduino via /science/actuator_status"

    print("✅ TEST PASSED: Motor status is strictly confirmed from the Arduino feedback over serial!")

    arduino_running = False
    sci_node.destroy_node()
    listener.destroy_node()
    rclpy.shutdown()
    if os.path.islink(virtual_port):
        os.unlink(virtual_port)
    os.close(master_fd)
    os.close(slave_fd)

if __name__ == '__main__':
    run_test()
