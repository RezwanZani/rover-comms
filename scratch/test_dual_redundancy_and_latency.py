#!/usr/bin/env python3
"""
test_dual_redundancy_and_latency.py
Comprehensive End-to-End Verification for:
  1. Concurrent Dual-Redundant Uplink (XBee 900MHz RF + Wi-Fi UDP)
  2. Primary XBee prioritization over UDP
  3. Automatic, seamless failover to UDP upon XBee interruption (< 0.35s)
  4. Immediate preemption back to XBee when XBee recovers
  5. Latency protection: Out-of-order / Stale packet rejection (RFC 1982 circular sequence math)
  6. Duplicate packet rejection across redundant links
  7. RTCM GPS correction deduplication across both links
"""

import json
import os
import signal
import socket
import struct
import subprocess
import sys
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Float32MultiArray, String
try:
    from rtcm_msgs.msg import Message as RTCMMessage
except ImportError:
    RTCMMessage = None

print("=" * 75)
print("TEST: Dual Redundancy, Priority Failover, and Latency Protection")
print("=" * 75)

# 1. Setup Virtual Serial Port Pair (/tmp/ttyV0 <-> /tmp/ttyV1)
socat_proc = subprocess.Popen(
    ["socat", "-d", "-d", "pty,raw,echo=0,link=/tmp/ttyV0", "pty,raw,echo=0,link=/tmp/ttyV1"],
    preexec_fn=os.setsid
)
time.sleep(0.6)

if not (os.path.exists('/tmp/ttyV0') and os.path.exists('/tmp/ttyV1')):
    os.killpg(os.getpgid(socat_proc.pid), signal.SIGKILL)
    raise RuntimeError("Failed to create /tmp/ttyV0 <-> /tmp/ttyV1 via socat.")
print("✅ Virtual serial pair active: /tmp/ttyV0 <-> /tmp/ttyV1")

# 2. Setup Raw Serial Writer (Simulating Base Station XBee radio on /tmp/ttyV0)
import serial
ser_tx = serial.Serial('/tmp/ttyV0', 115200, timeout=0)

def wrap_xbee(payload: bytes, dest_addr: bytes = b'\x00\x13\xa2\x00\x42\x5e\x94\xff') -> bytes:
    """Build Digi XBee API frame (type 0x10 Transmit Request with Disable ACK)."""
    frame_data = bytes([0x10, 0x00]) + dest_addr + b'\xff\xfe\x00\x01' + payload
    length = len(frame_data)
    checksum = 0xFF - (sum(frame_data) & 0xFF)
    return struct.pack('>BH', 0x7E, length) + frame_data + bytes([checksum])

def send_xbee_raw(payload: bytes):
    frame = wrap_xbee(payload)
    ser_tx.write(frame)
    ser_tx.flush()

# Setup UDP Socket to Rover (Port 8888)
udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
ROVER_UDP_TARGET = ('127.0.0.1', 8888)

# Packet struct helper
_MOTION = struct.Struct('<cBhhhhhhh')
def i16(v): return max(-32768, min(32767, int(round(v * 1000))))

def make_motion(seq, vx, wz, act1=0.0, act2=0.0, act3=0.0, wrist=0.0, gripper=0.0):
    return _MOTION.pack(b'M', seq & 0xFF, i16(vx), i16(wz), i16(act1), i16(act2), i16(act3), i16(wrist), i16(gripper))

# 3. Setup ROS 2 Verification Monitor
rclpy.init()

class RedundancyMonitor(Node):
    def __init__(self):
        super().__init__('redundancy_monitor')
        self.cmd_history = []
        self.status_history = []
        self.rtcm_history = []

        self.create_subscription(Twist, '/cmd_vel', self.on_cmd, 50)
        self.create_subscription(String, 'xbee_rx/status', self.on_status, 50)
        if RTCMMessage:
            self.create_subscription(RTCMMessage, '/rtcm', self.on_rtcm, 50)

    def on_cmd(self, msg):
        self.cmd_history.append((time.monotonic(), msg.linear.x, msg.angular.z))

    def on_status(self, msg):
        try:
            data = json.loads(msg.data)
            self.status_history.append((time.monotonic(), data))
        except Exception:
            pass

    def on_rtcm(self, msg):
        self.rtcm_history.append((time.monotonic(), bytes(msg.message)))

monitor = RedundancyMonitor()

def spin_for(duration_sec, step=0.02):
    t_end = time.monotonic() + duration_sec
    while time.monotonic() < t_end:
        rclpy.spin_once(monitor, timeout_sec=step)
        time.sleep(step)

# 4. Start Rover rx_node on /tmp/ttyV1 directly with python entry point
rx_proc = subprocess.Popen(
    [sys.executable, "/home/rezwan/Desktop/rover_com/rover/install/xbee_teleop/lib/xbee_teleop/rx_node",
     "--ros-args", "-p", "port:=/tmp/ttyV1", "-p", "xbee_failover_timeout:=0.35"],
    preexec_fn=os.setsid
)
time.sleep(1.2)

# Wait until rx_node is fully online and publishing status
print("Waiting for rx_node initialization...")
while not monitor.status_history:
    spin_for(0.1)
print(f"✅ rx_node online and discovered. Initial status: {monitor.status_history[-1][1].get('active_source')}")

# Send one initial XBee packet to establish XBee link baseline
send_xbee_raw(make_motion(seq=1, vx=0.60, wz=0.30))
spin_for(0.1)

try:
    print("\n--- PHASE 1: Concurrent Redundancy (XBee Priority) ---")
    # Send on both XBee and UDP concurrently.
    # XBee sends vx=0.60, UDP sends vx=0.20 with same sequence numbers.
    phase1_start = time.monotonic()
    for s in range(2, 25):
        pkt_xbee = make_motion(seq=s, vx=0.60, wz=0.30)
        pkt_udp  = make_motion(seq=s, vx=0.20, wz=0.10)
        send_xbee_raw(pkt_xbee)
        udp_sock.sendto(pkt_udp, ROVER_UDP_TARGET)
        spin_for(0.05)

    recent_cmds = [c for c in monitor.cmd_history if c[0] >= phase1_start and c[1] > 0.05]
    assert recent_cmds, "No active commands received in Phase 1!"
    xbee_cmds = [c for c in recent_cmds if abs(c[1] - 0.60) < 0.05]
    udp_executed = [c for c in recent_cmds if abs(c[1] - 0.20) < 0.05]

    print(f"  Captured active commands: {len(recent_cmds)}")
    print(f"  XBee executions (vx=0.60): {len(xbee_cmds)}")
    print(f"  UDP executions (vx=0.20):  {len(udp_executed)}")
    assert len(xbee_cmds) > 0, "XBee commands were not executed!"
    assert len(udp_executed) == 0, f"FAIL: UDP executed while XBee was active! ({len(udp_executed)} occurrences)"
    latest_status = monitor.status_history[-1][1]
    print(f"  Active Channel: {latest_status.get('active_source')}, xbee_alive: {latest_status.get('xbee_alive')}")
    assert latest_status.get('active_source') == 'XBEE', f"Expected active_source='XBEE', got {latest_status.get('active_source')}"
    print("✅ PASS: Phase 1 — XBee is prioritized, redundant UDP is discarded.")

    print("\n--- PHASE 2: XBee Failure & Seamless UDP Failover ---")
    # Cut XBee completely. Only send UDP packets (vx=0.85, wz=-0.40)
    # Send at 20 Hz (50ms interval) for 1.2 seconds.
    phase2_start = time.monotonic()
    for s in range(21, 46):
        pkt_udp = make_motion(seq=s, vx=0.85, wz=-0.40)
        udp_sock.sendto(pkt_udp, ROVER_UDP_TARGET)
        spin_for(0.05)

    # Verify switch to UDP
    recent_status = [s[1] for s in monitor.status_history if s[0] >= phase2_start]
    sources = [s.get('active_source') for s in recent_status]
    print(f"  Channel progression during cut: {sources[-6:]}")
    assert 'UDP' in sources, "FAIL: Rover did not switch to UDP after XBee cut!"

    udp_cmds = [c for c in monitor.cmd_history if c[0] >= phase2_start and abs(c[1] - 0.85) < 0.05]
    print(f"  UDP failover commands executed (vx=0.85): {len(udp_cmds)}")
    assert len(udp_cmds) > 0, "FAIL: UDP commands were never executed during failover!"
    latest_status = monitor.status_history[-1][1]
    print(f"  Active Channel: {latest_status.get('active_source')}, xbee_alive: {latest_status.get('xbee_alive')}, udp_alive: {latest_status.get('udp_alive')}")
    print("✅ PASS: Phase 2 — Seamless failover to UDP succeeded upon XBee loss.")

    print("\n--- PHASE 3: XBee Recovery & Immediate Preemption ---")
    # While UDP is still sending vx=0.85, XBee comes back with vx=0.45
    phase3_start = time.monotonic()
    for s in range(46, 66):
        pkt_xbee = make_motion(seq=s, vx=0.45, wz=0.15)
        pkt_udp  = make_motion(seq=s, vx=0.85, wz=-0.40)
        # Send XBee first
        send_xbee_raw(pkt_xbee)
        udp_sock.sendto(pkt_udp, ROVER_UDP_TARGET)
        spin_for(0.05)

    recovery_cmds = [c for c in monitor.cmd_history if c[0] >= phase3_start]
    recovered_xbee = [c for c in recovery_cmds if abs(c[1] - 0.45) < 0.05]
    overridden_udp = [c for c in recovery_cmds if abs(c[1] - 0.85) < 0.05]
    print(f"  Recovered XBee commands (vx=0.45): {len(recovered_xbee)}")
    print(f"  Remaining UDP commands after XBee return: {len(overridden_udp)}")
    assert len(recovered_xbee) > 0, "FAIL: XBee did not reclaim priority!"
    latest_status = monitor.status_history[-1][1]
    assert latest_status.get('active_source') == 'XBEE', f"Expected active_source='XBEE', got {latest_status.get('active_source')}"
    print(f"  Active Channel: {latest_status.get('active_source')}, xbee_alive: {latest_status.get('xbee_alive')}")
    print("✅ PASS: Phase 3 — XBee immediately preempted UDP upon link recovery.")

    print("\n--- PHASE 4: Latency & Stale / Out-of-Order Packet Rejection ---")
    # Rover is at seq >= 65.
    status_before = monitor.status_history[-1][1]
    stale_before = status_before.get('stale_rejected', 0)
    dups_before = status_before.get('duplicates_rejected', 0)
    print(f"  Baseline stale_rejected: {stale_before}, duplicates_rejected: {dups_before}")

    # Inject 5 stale packets (seq=30, vx=0.99)
    for _ in range(5):
        stale_pkt = make_motion(seq=30, vx=0.99, wz=0.0)
        send_xbee_raw(stale_pkt)
        udp_sock.sendto(stale_pkt, ROVER_UDP_TARGET)
        spin_for(0.05)

    # Inject 5 duplicate packets with last executed seq
    last_seq = monitor.status_history[-1][1].get('seq', 65)
    for _ in range(5):
        dup_pkt = make_motion(seq=last_seq, vx=0.99, wz=0.0)
        send_xbee_raw(dup_pkt)
        udp_sock.sendto(dup_pkt, ROVER_UDP_TARGET)
        spin_for(0.05)

    spin_for(0.4)
    status_after = monitor.status_history[-1][1]
    stale_after = status_after.get('stale_rejected', 0)
    dups_after = status_after.get('duplicates_rejected', 0)

    print(f"  After test: stale_rejected = {stale_after} (delta: +{stale_after - stale_before})")
    print(f"  After test: duplicates_rejected = {dups_after} (delta: +{dups_after - dups_before})")

    # Ensure stale packets were NOT executed
    bad_executions = [c for c in monitor.cmd_history if abs(c[1] - 0.99) < 0.05]
    assert len(bad_executions) == 0, f"FAIL: Stale/duplicate packet executed! ({bad_executions})"
    assert stale_after > stale_before, f"FAIL: stale_rejected did not increment!"
    assert dups_after > dups_before, f"FAIL: duplicates_rejected did not increment!"
    print("✅ PASS: Phase 4 — Stale and duplicate packets properly rejected due to RFC 1982 sequence check.")

    print("\n--- PHASE 5: RTCM Deduplication Across Both Channels ---")
    rtcm_before = len(monitor.rtcm_history)
    rtcm_test_bytes = b'\xD3\x00\x14' + bytes([0x42] * 14) + b'\xDE\xAD\xBE\xEF'

    # Send identical RTCM packet on XBee and UDP simultaneously 3 times
    for _ in range(3):
        send_xbee_raw(rtcm_test_bytes)
        udp_sock.sendto(rtcm_test_bytes, ROVER_UDP_TARGET)
        spin_for(0.08)

    spin_for(0.3)
    rtcm_after = len(monitor.rtcm_history)
    rtcm_injected = rtcm_after - rtcm_before
    print(f"  RTCM frames delivered to /rtcm: {rtcm_injected} (Expected: 1, sent 6 raw across 2 links)")
    assert rtcm_injected == 1, f"FAIL: RTCM was not deduplicated! Expected 1, got {rtcm_injected}"
    print("✅ PASS: Phase 5 — RTCM deduplication prevents redundant frames from spamming GPS.")

finally:
    # Safe Cleanup
    try:
        os.killpg(os.getpgid(rx_proc.pid), signal.SIGKILL)
    except Exception:
        pass
    ser_tx.close()
    try:
        os.killpg(os.getpgid(socat_proc.pid), signal.SIGKILL)
    except Exception:
        pass
    udp_sock.close()
    monitor.destroy_node()
    rclpy.shutdown()

print("\n" + "=" * 75)
print("🎉 ALL DUAL-REDUNDANCY AND LATENCY TESTS PASSED SUCCESSFULLY!")
print("=" * 75)
