#!/usr/bin/env python3
"""
setup_udev.py -- Sets up persistent Linux udev rules for Rover XBee and LC29H RTK GPS.

Automatically binds:
  XBee 900MHz (FTDI FT232R, Serial B0025NTL) -> /dev/rover_900mhz
  LC29H RTK GPS (CP2102N, Serial ac57edb6...) -> /dev/rover_rtk

Usage:
  sudo python3 setup_udev.py
"""

import os
import sys
import subprocess

RULE_FILE = "/etc/udev/rules.d/99-rover-serial.rules"

RULES_CONTENT = """# =============================================================================
# Rover Static Serial Rules
# Automatically binds XBee 900MHz and LC29H RTK GPS to static symlinks
# =============================================================================

# XBee 900MHz Module (FTDI FT232R) -> /dev/rover_900mhz & /dev/rover_900mh
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", ATTRS{serial}=="B0025NTL", SYMLINK+="rover_900mhz rover_900mh", MODE="0666", GROUP="dialout"

# LC29H RTK GPS Module (Silicon Labs CP2102N) -> /dev/rover_rtk
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", ATTRS{serial}=="ac57edb6726cef119a94a3adc169b110", SYMLINK+="rover_rtk", MODE="0666", GROUP="dialout"
"""


def main():
    if os.geteuid() != 0:
        print("⚠️ Permission denied: Please run this script with sudo:")
        print("   sudo python3 setup_udev.py")
        sys.exit(1)

    print(f"Writing udev rules to {RULE_FILE}...")
    with open(RULE_FILE, "w") as f:
        f.write(RULES_CONTENT)

    print("Reloading udev rules...")
    subprocess.run(["udevadm", "control", "--reload-rules"], check=True)
    subprocess.run(["udevadm", "trigger"], check=True)

    print("\n=== Static Links Configured Successfully ===")
    res = subprocess.run(["ls", "-l", "/dev/rover_900mhz", "/dev/rover_rtk"], stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        print("Please unplug and replug the USB cables to trigger the symlinks.")


if __name__ == '__main__':
    main()
