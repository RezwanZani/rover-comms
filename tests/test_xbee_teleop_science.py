import os
import sys
import struct
import json
import time
import pytest

# Add base_station directory to path
base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'base_station'))
teleop_dir = os.path.join(base_dir, 'run_teleop_base')
sys.path.insert(0, base_dir)
sys.path.insert(0, teleop_dir)

from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QKeyEvent
from PyQt5.QtWidgets import QApplication

import xbee_teleop_windows as xtw


# Create a QApplication instance if one doesn't exist
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)


class MockLink:
    def __init__(self):
        self.connected = True
        self.sent_packets = []

    def send(self, pkt):
        self.sent_packets.append(bytes(pkt))
        return True

    def close(self):
        self.connected = False


def create_key_event(event_type, key, modifiers=Qt.NoModifier, is_auto_repeat=False):
    return QKeyEvent(event_type, key, modifiers, "", is_auto_repeat)


def cleanup_win(win):
    if hasattr(win, 'udp_rx') and win.udp_rx:
        win.udp_rx.stop()
    for t in getattr(win, 'timers', []):
        t.stop()
    win.close()


def test_unpack_science_and_mode_packets():
    # Test packing and unpacking science packet
    pkt_sci = xtw.pack_science(seq=42, m1=1, m2=0, m3=1, m4=0, m5=1, led=1, servo=120)
    assert len(pkt_sci) == xtw._SCIENCE.size
    res = xtw.unpack(pkt_sci)
    assert res is not None
    assert res[0] == 'science'
    assert res[1] == 42
    assert res[2:] == (1, 0, 1, 0, 1, 1, 120)

    # Test packing and unpacking mode packet
    pkt_mode = xtw.pack_mode(seq=15, mode=1)
    res_m = xtw.unpack(pkt_mode)
    assert res_m is not None
    assert res_m == ('mode', 15, 1)


def test_keyboard_shortcuts_and_motor_control():
    win = xtw.MainWindow()
    mock_link = MockLink()
    win.link = mock_link

    # Initially, motor states in confirmed state are 0
    assert win.sci_confirmed['m1'] == 0
    assert win.sci_confirmed['m2'] == 0
    assert win.sci_confirmed['led'] == 0
    assert win.sci_confirmed['servo'] == 0

    # 1. Simulate Ctrl + 1 (Toggle Motor 1)
    ev_ctrl_1 = create_key_event(QEvent.KeyPress, Qt.Key_1, Qt.ControlModifier)
    handled = win.eventFilter(win, ev_ctrl_1)
    assert handled is True
    assert win.sci_cmd['m1'] == 1
    # Check that confirmed status is STILL 0 (strict requirement: status from rover telemetry only!)
    assert win.sci_confirmed['m1'] == 0
    assert len(mock_link.sent_packets) == 1

    # Verify packet content
    tag, seq, m1, m2, m3, m4, m5, led, servo = struct.unpack('<cBBBBBBBB', mock_link.sent_packets[-1])
    assert tag == b'S'
    assert m1 == 1
    assert m2 == 0

    # 2. Simulate Ctrl + 2 (Toggle Motor 2)
    ev_ctrl_2 = create_key_event(QEvent.KeyPress, Qt.Key_2, Qt.ControlModifier)
    assert win.eventFilter(win, ev_ctrl_2) is True
    assert win.sci_cmd['m2'] == 1
    assert win.sci_confirmed['m2'] == 0

    # 3. Simulate Ctrl + 6 (Toggle LED)
    ev_ctrl_6 = create_key_event(QEvent.KeyPress, Qt.Key_6, Qt.ControlModifier)
    assert win.eventFilter(win, ev_ctrl_6) is True
    assert win.sci_cmd['led'] == 1
    assert win.sci_confirmed['led'] == 0

    # 4. Simulate Ctrl + Right Arrow (Servo +15 deg)
    ev_ctrl_right = create_key_event(QEvent.KeyPress, Qt.Key_Right, Qt.ControlModifier)
    assert win.eventFilter(win, ev_ctrl_right) is True
    assert win.sci_cmd['servo'] == 15
    assert win.sci_confirmed['servo'] == 0

    # 5. Simulate Ctrl + Right Arrow twice more (Servo to 45 deg)
    win.eventFilter(win, ev_ctrl_right)
    win.eventFilter(win, ev_ctrl_right)
    assert win.sci_cmd['servo'] == 45

    # 6. Simulate Ctrl + Left Arrow (Servo -15 deg -> 30 deg)
    ev_ctrl_left = create_key_event(QEvent.KeyPress, Qt.Key_Left, Qt.ControlModifier)
    assert win.eventFilter(win, ev_ctrl_left) is True
    assert win.sci_cmd['servo'] == 30

    # 7. Simulate Rover Telemetry Feedback Arriving
    # Telemetry confirms M1=1, M2=1, LED=1, Servo=30
    rover_telemetry = {
        "type": "TELEMETRY",
        "science": {
            "m1": 1, "m2": 1, "m3": 0, "m4": 0, "m5": 0,
            "led": 1, "servo": 30, "connected": True
        }
    }
    tel_bytes = b'T' + json.dumps(rover_telemetry).encode('utf-8')
    win.on_radio(tel_bytes)

    # Now the confirmed state MUST reflect the rover's telemetry!
    assert win.sci_confirmed['m1'] == 1
    assert win.sci_confirmed['m2'] == 1
    assert win.sci_confirmed['m3'] == 0
    assert win.sci_confirmed['led'] == 1
    assert win.sci_confirmed['servo'] == 30
    assert win.sci_confirmed['connected'] is True

    # 8. Update UI display and verify widgets
    win.sci_p.update_display(win.sci_confirmed)
    assert win.sci_p.motor_labels['m1'].text() == 'ON'
    assert win.sci_p.motor_labels['m2'].text() == 'ON'
    assert win.sci_p.motor_labels['m3'].text() == 'OFF'
    assert win.sci_p.lbl_led_status.text() == 'ON'
    assert win.sci_p.lbl_servo_status.text() == '30°'
    assert 'Arduino Mega Ready' in win.sci_p.head.text()

    # 9. Test Emergency Stop All (Ctrl + Z)
    ev_ctrl_z = create_key_event(QEvent.KeyPress, Qt.Key_Z, Qt.ControlModifier)
    assert win.eventFilter(win, ev_ctrl_z) is True
    assert win.sci_cmd['m1'] == 0
    assert win.sci_cmd['m2'] == 0
    # Last packet sent should have all motors 0
    tag, seq, m1, m2, m3, m4, m5, led, servo = struct.unpack('<cBBBBBBBB', mock_link.sent_packets[-1])
    assert (m1, m2, m3, m4, m5) == (0, 0, 0, 0, 0)

    # 10. Verify Ctrl + Left/Right does not trigger keyboard drive when active
    win.keyboard_drive = True
    win.keys.clear()
    # Plain Left Arrow -> steers rover left
    ev_plain_left = create_key_event(QEvent.KeyPress, Qt.Key_Left)
    handled_plain = win.eventFilter(win, ev_plain_left)
    assert handled_plain is True
    assert 'left' in win.keys

    # Release plain Left Arrow
    ev_rel_left = create_key_event(QEvent.KeyRelease, Qt.Key_Left)
    win.eventFilter(win, ev_rel_left)
    assert 'left' not in win.keys

    # Ctrl + Left Arrow -> steps servo, NOT drive keys
    win.eventFilter(win, ev_ctrl_left)
    assert 'left' not in win.keys  # Must NOT be added to drive keys!

    cleanup_win(win)


def test_ui_button_clicks():
    win = xtw.MainWindow()
    mock_link = MockLink()
    win.link = mock_link

    # Click Motor 3 toggle button in the SciencePanel
    win.sci_p.motor_btns['m3'].click()
    assert win.sci_cmd['m3'] == 1

    # Click LED toggle button
    win.sci_p.btn_led.click()
    assert win.sci_cmd['led'] == 1

    # Click Servo +15 button
    win.sci_p.btn_servo_inc.click()
    assert win.sci_cmd['servo'] == 15

    # Click Stop All button
    win.sci_p.btn_stop_all.click()
    assert win.sci_cmd['m3'] == 0

    cleanup_win(win)


if __name__ == '__main__':
    print("Testing unpack science and mode packets...")
    test_unpack_science_and_mode_packets()
    print("Testing keyboard shortcuts and motor control...")
    test_keyboard_shortcuts_and_motor_control()
    print("Testing UI button clicks...")
    test_ui_button_clicks()
    print("\n✅ ALL TESTS PASSED SUCCESSFULLY!")
    sys.exit(0)
