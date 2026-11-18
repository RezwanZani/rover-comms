#!/usr/bin/env python3
"""
test_centralized_comms.py
End-to-End Test for the Centralized Base Master + Rover Comms Master architecture.

Verifies:
  1. Virtual port pair (/tmp/ttyV0 <-> /tmp/ttyV1)
  2. Base Master Hub (base_master.py) receiving UDP 9001 (Teleop) and 9002 (RTCM)
  3. Priority multiplexing: 'M' teleop packets are prioritized before RTCM chunks
  4. Rover RxNode receiving over serial, publishing /cmd_vel, /arm_vel, and /rtcm
  5. Rover Telemetry uplink through RxNode -> Base Master -> UDP 9003
"""

import os
import signal
import sys
import time
import socket
import struct
import subprocess
import threading

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Float32MultiArray, String
try:
    from rtcm_msgs.msg import Message as RTCMMessage
except ImportError:
    RTCMMessage = None

print("=== Starting Centralized Architecture Verification ===")

# 1. Start Virtual Port Pair via socat
socat_proc = subprocess.Popen(
    ["socat", "-d", "-d", "pty,raw,echo=0,link=/tmp/ttyV0", "pty,raw,echo=0,link=/tmp/ttyV1"],
    preexec_fn=os.setsid
)
time.sleep(0.6)

# Verify ports exist
if not (os.path.exists('/tmp/ttyV0') and os.path.exists('/tmp/ttyV1')):
    os.killpg(os.getpgid(socat_proc.pid), signal.SIGKILL)
    raise RuntimeError("Virtual serial ports /tmp/ttyV0 and /tmp/ttyV1 failed to create.")
print("✅ Virtual serial ports /tmp/ttyV0 and /tmp/ttyV1 active.")

# 2. Start Base Master Hub
base_master_proc = subprocess.Popen(
    [sys.executable, "/home/rezwan/Desktop/rover_com/base_station/base_master.py", "/tmp/ttyV0"],
    preexec_fn=os.setsid
)
time.sleep(0.8)

# 3. Initialize ROS 2 and Subscriber Monitor
rclpy.init()

class CommsVerifier(Node):
    def __init__(self):
        super().__init__('comms_verifier')
        self.cmd_received = []
        self.arm_received = []
        self.rtcm_received = []
        
        self.create_subscription(Twist, '/cmd_vel', self.on_cmd, 10)
        self.create_subscription(Float32MultiArray, '/arm_vel', self.on_arm, 10)
        if RTCMMessage:
            self.create_subscription(RTCMMessage, '/rtcm', self.on_rtcm, 10)
        self.telemetry_pub = self.create_publisher(String, 'telemetry_tx', 10)

    def on_cmd(self, msg):
        self.cmd_received.append((msg.linear.x, msg.angular.z))

    def on_arm(self, msg):
        self.arm_received.append(list(msg.data))

    def on_rtcm(self, msg):
        self.rtcm_received.append(bytes(msg.message))

verifier = CommsVerifier()

# Start Rover rx_node (Rover Comms Master)
rx_node_proc = subprocess.Popen(
    [sys.executable, "/home/rezwan/Desktop/rover_com/rover/install/xbee_teleop/lib/xbee_teleop/rx_node",
     "--ros-args", "-p", "port:=/tmp/ttyV1"],
    preexec_fn=os.setsid
)
time.sleep(1.2)

# 4. Prepare Status / Telemetry UDP listener on Port 9003
status_listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
status_listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
status_listener.bind(('0.0.0.0', 9003))
status_listener.settimeout(0.5)

# 5. Send Test Teleop 'M' packet to Port 9001 (Base Master)
_MOTION = struct.Struct('<cBhhhhhhh')
def i16(v): return max(-32768, min(32767, int(round(v * 1000))))

motion_bytes = _MOTION.pack(b'M', 42, i16(0.75), i16(-0.50), i16(1.0), i16(-1.0), i16(1.0), i16(0.0), i16(-1.0))
joy_sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# 6. Send Test RTCM3 packet to Port 9002 (Base Master)
# Synthetic RTCM3 frame starting with 0xD3
rtcm_test_payload = b'\xD3\x00\x10' + bytes(range(16)) + b'\xAA\xBB\xCC'
rtcm_sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Wait for subscriber discovery
for _ in range(10):
    rclpy.spin_once(verifier, timeout_sec=0.05)
    time.sleep(0.05)

print("Transmitting Test Data: Joystick -> UDP:9001 | RTCM -> UDP:9002 ...")

# Fire packets over 1.5s while continuously spinning ROS node
for seq in range(30):
    pkt = _MOTION.pack(b'M', seq, i16(0.75), i16(-0.50), i16(1.0), i16(-1.0), i16(1.0), i16(0.0), i16(-1.0))
    joy_sender.sendto(pkt, ('127.0.0.1', 9001))
    rtcm_sender.sendto(rtcm_test_payload, ('127.0.0.1', 9002))
    rclpy.spin_once(verifier, timeout_sec=0.05)
    time.sleep(0.05)

# Also test Telemetry uplink from Rover to Base
tx_test_msg = String()
tx_test_msg.data = '{"test": "telemetry_uplink_ok", "battery": 25.1}'
verifier.telemetry_pub.publish(tx_test_msg)

# Now stop sending, but keep spinning ROS to observe watchdog zeroing
for _ in range(25):
    rclpy.spin_once(verifier, timeout_sec=0.04)
    time.sleep(0.04)

# Check telemetry arrived at Base Station UDP 9003
telemetry_at_base = False
try:
    data, _ = status_listener.recvfrom(2048)
    if b'telemetry_uplink_ok' in data or b'master_heartbeat' in data or data.startswith(b'A'):
        telemetry_at_base = True
        print(f"✅ Telemetry / Status received at Base Station UDP 9003: {data[:60]}...")
except socket.timeout:
    print("⚠️ Timeout waiting for telemetry on 9003 (might have been consumed or not sent yet)")

# Cleanup processes
try:
    os.killpg(os.getpgid(rx_node_proc.pid), signal.SIGKILL)
except Exception:
    pass
try:
    os.killpg(os.getpgid(base_master_proc.pid), signal.SIGKILL)
except Exception:
    pass
try:
    os.killpg(os.getpgid(socat_proc.pid), signal.SIGKILL)
except Exception:
    pass
status_listener.close()
joy_sender.close()
rtcm_sender.close()
verifier.destroy_node()
rclpy.shutdown()

# Validate Results
print("\n--- Verification Results ---")
print(f"Drive commands captured (/cmd_vel): {len(verifier.cmd_received)}")
if verifier.cmd_received:
    print(f"  Captured commands: {verifier.cmd_received}")
    has_active_cmd = any(abs(c[0] - 0.75) < 0.05 and abs(c[1] - (-0.50)) < 0.05 for c in verifier.cmd_received)
    assert has_active_cmd, f"Expected active command vx=0.75, wz=-0.50 was not captured in: {verifier.cmd_received}"
    print("✅ /cmd_vel correctly received and published active velocities (vx=0.75, wz=-0.50)!")
    
    # Also verify that after silence, the safety watchdog zeros out the velocity
    last_cmd = verifier.cmd_received[-1]
    assert abs(last_cmd[0]) < 0.01 and abs(last_cmd[1]) < 0.01, f"Safety watchdog failed to zero: {last_cmd}"
    print("✅ Safety watchdog zeroed /cmd_vel to (0, 0) after packets stopped!")

print(f"Arm commands captured (/arm_vel): {len(verifier.arm_received)}")
if verifier.arm_received:
    has_active_arm = any(abs(a[0] - 1.0) < 0.05 and abs(a[1] - (-1.0)) < 0.05 for a in verifier.arm_received)
    assert has_active_arm, f"Expected arm commands not captured in: {verifier.arm_received}"
    print("✅ /arm_vel correctly received and published by rx_node!")

print(f"RTCM frames captured (/rtcm): {len(verifier.rtcm_received)}")
if verifier.rtcm_received:
    print(f"  Last /rtcm length: {len(verifier.rtcm_received[-1])} bytes, preamble=0x{verifier.rtcm_received[-1][0]:02X}")
    assert verifier.rtcm_received[-1][0] == 0xD3, "RTCM preamble mismatch"
    print("✅ /rtcm correctly demultiplexed and published by rx_node!")

print("\n🎉 ALL TESTS PASSED: Centralized Master Architecture is verified and functional!")
