#!/usr/bin/env python3
"""
create_virtual_pair.py -- Creates a bi-directional virtual serial port pair using socat.

Creates:
  Base Station Port : /tmp/ttyV0
  Rover Port        : /tmp/ttyV1

Usage:
  python3 create_virtual_pair.py
"""

import os
import sys
import shutil
import signal
import subprocess

PORT0 = "/tmp/ttyV0"
PORT1 = "/tmp/ttyV1"


def cleanup():
    for p in (PORT0, PORT1):
        if os.path.exists(p) or os.path.islink(p):
            try:
                os.remove(p)
            except Exception:
                pass


def main():
    if not shutil.which("socat"):
        print("❌ Error: 'socat' is not installed! Install it with: sudo apt install socat")
        sys.exit(1)

    cleanup()

    print("=" * 60)
    print("  Creating Virtual Serial Port Pair with socat...")
    print(f"  Base Station Port : {PORT0}")
    print(f"  Rover Port        : {PORT1}")
    print("=" * 60)
    print("Press Ctrl+C to terminate the virtual serial link.\n")

    cmd = [
        "socat", "-d", "-d",
        f"pty,raw,echo=0,link={PORT0}",
        f"pty,raw,echo=0,link={PORT1}"
    ]

    def _sig_handler(sig, frame):
        cleanup()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    try:
        proc = subprocess.Popen(cmd)
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()


if __name__ == '__main__':
    main()
