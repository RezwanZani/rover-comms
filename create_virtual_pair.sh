#!/usr/bin/env bash
# create_virtual_pair.sh
# Creates a bi-directional virtual serial port pair at /tmp/ttyV0 and /tmp/ttyV1

PORT0="/tmp/ttyV0"
PORT1="/tmp/ttyV1"

# Clean up any stale symlinks
rm -f "$PORT0" "$PORT1"

echo "=========================================================="
echo "Creating Virtual Serial Port Pair with socat..."
echo "  Base Station Port : $PORT0"
echo "  Rover Port        : $PORT1"
echo "=========================================================="
echo "Press Ctrl+C to terminate the virtual link."
echo ""

exec socat -d -d pty,raw,echo=0,link="$PORT0" pty,raw,echo=0,link="$PORT1"
