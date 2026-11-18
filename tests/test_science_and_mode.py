#!/usr/bin/env python3
"""
test_science_and_mode.py -- Unit and integration tests for Science Mission and Mode Toggle
"""
import struct
import sys
import os

# Add paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'rover', 'src', 'xbee_teleop_rover')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'base_station')))

from xbee_teleop.link import pack_science, pack_mode, unpack, pack_motion
from comms_config import (
    SCIENCE_PACKET_FORMAT, SCIENCE_PACKET_ID, SCIENCE_PACKET_SIZE,
    MODE_PACKET_FORMAT, MODE_PACKET_ID, MODE_PACKET_SIZE
)

def test_science_packing():
    print("Testing pack_science / unpack...")
    seq = 42
    m1, m2, m3, m4, m5 = 1, 0, 1, 1, 0
    led = 1
    servo = 135

    pkt = pack_science(seq, m1, m2, m3, m4, m5, led, servo)
    assert len(pkt) == SCIENCE_PACKET_SIZE, f"Expected size {SCIENCE_PACKET_SIZE}, got {len(pkt)}"
    assert pkt[0:1] == SCIENCE_PACKET_ID, f"Expected ID {SCIENCE_PACKET_ID}, got {pkt[0:1]}"

    res = unpack(pkt)
    assert res is not None, "Unpack returned None"
    kind, r_seq, r_m1, r_m2, r_m3, r_m4, r_m5, r_led, r_servo = res
    assert kind == 'science'
    assert r_seq == seq
    assert (r_m1, r_m2, r_m3, r_m4, r_m5) == (1, 0, 1, 1, 0)
    assert r_led == 1
    assert r_servo == 135
    print("✅ Science packing test passed!")

def test_mode_packing():
    print("Testing pack_mode / unpack...")
    seq = 99
    # Autonomous
    pkt_auto = pack_mode(seq, 1)
    assert len(pkt_auto) == MODE_PACKET_SIZE
    assert pkt_auto[0:1] == MODE_PACKET_ID
    res = unpack(pkt_auto)
    assert res == ('mode', 99, 1)

    # Teleop
    pkt_teleop = pack_mode(100, 0)
    assert unpack(pkt_teleop) == ('mode', 100, 0)
    print("✅ Mode packing test passed!")

def test_motion_backward_compat():
    print("Testing motion packet backward compatibility...")
    pkt = pack_motion(12, 0.5, -0.2, 1.0, 0.0, -1.0, 0.0, 1.0)
    res = unpack(pkt)
    assert res is not None and res[0] == 'motion'
    assert res[1] == 12
    assert abs(res[2] - 0.5) < 0.001
    assert abs(res[3] - (-0.2)) < 0.001
    print("✅ Motion packet backward compatibility passed!")

if __name__ == '__main__':
    test_science_packing()
    test_mode_packing()
    test_motion_backward_compat()
    print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
