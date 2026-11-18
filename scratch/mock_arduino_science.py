#!/usr/bin/env python3
"""
mock_arduino_science.py -- Emulates the Arduino Mega 2560 Science Firmware.

Creates a virtual serial port pair using Python's pty module:
  - Node port:    /tmp/ttyArduino
  - Emulates:     L298N drivers (5 pumps), LED (pins 32,33), and Servo (pin 34)
  - Protocol:     Parses 'S:m1,m2,m3,m4,m5,led,servo\n'
                  Responds with 'STATUS:m1=1,m2=0,m3=0,m4=0,m5=0,led=0,servo=0\n'
                  Emits periodic heartbeat every 1 second
"""

import os
import pty
import select
import sys
import time

PORT_LINK = "/tmp/ttyArduino"

def main():
    master_fd, slave_fd = pty.openpty()
    slave_name = os.ttyname(slave_fd)

    if os.path.exists(PORT_LINK) or os.path.islink(PORT_LINK):
        try:
            os.unlink(PORT_LINK)
        except Exception:
            pass

    try:
        os.symlink(slave_name, PORT_LINK)
    except Exception as e:
        print(f"Error creating symlink {PORT_LINK} -> {slave_name}: {e}")
        return

    print("=" * 60)
    print("  MOCK ARDUINO MEGA 2560 (SCIENCE FIRMWARE SIMULATOR)")
    print(f"  Virtual Port ready at: {PORT_LINK}")
    print("  Emulating 5 Peristaltic Pumps, LED, and Servo.")
    print("=" * 60)

    motors = [0, 0, 0, 0, 0]
    led = 0
    servo = 0

    def format_status():
        return f"STATUS:m1={motors[0]},m2={motors[1]},m3={motors[2]},m4={motors[3]},m5={motors[4]},led={led},servo={servo}\n"

    last_broadcast = time.time()
    buf = ""

    try:
        # Initial system ready line
        os.write(master_fd, b"SYSTEM READY: SCIENCE MODULE ACTIVE\n")
        os.write(master_fd, format_status().encode('ascii'))

        while True:
            r, _, _ = select.select([master_fd], [], [], 0.2)
            if master_fd in r:
                data = os.read(master_fd, 1024)
                if data:
                    buf += data.decode('ascii', errors='ignore')
                    while '\n' in buf:
                        line, buf = buf.split('\n', 1)
                        line = line.strip()
                        if line.startswith("S:") or line.startswith("s:"):
                            args = line[2:].strip().split(',')
                            if len(args) >= 6:
                                for i in range(min(5, len(args))):
                                    motors[i] = 1 if int(args[i]) != 0 else 0
                                led = 1 if int(args[5]) != 0 else 0
                                if len(args) >= 7:
                                    servo = max(0, min(180, int(args[6])))
                                
                                print(f"📥 Received Command: {line} -> M:{motors} LED:{led} SERVO:{servo}°")
                                status_line = format_status()
                                os.write(master_fd, status_line.encode('ascii'))
                                print(f"📤 Sent Feedback:   {status_line.strip()}")

            now = time.time()
            if now - last_broadcast >= 1.0:
                last_broadcast = now
                os.write(master_fd, format_status().encode('ascii'))

    except KeyboardInterrupt:
        print("\nStopping Mock Arduino...")
    finally:
        if os.path.islink(PORT_LINK):
            os.unlink(PORT_LINK)
        os.close(master_fd)
        os.close(slave_fd)

if __name__ == '__main__':
    main()
