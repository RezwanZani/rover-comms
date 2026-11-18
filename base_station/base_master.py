#!/usr/bin/env python3
"""
base_master.py -- Central Base Station Communications Hub & Serial Radio Owner.

Architecture:
  - Sole owner of the Base Station physical XBee serial port.
  - Sockets:
      * UDP Port 9001: Listens for 16-byte 'M' motion packets from Joystick Teleop GUI.
      * UDP Port 9002: Listens for raw 0xD3 RTCM3 frames from Base RTK GPS script.
      * UDP Port 9003: Forwards incoming Telemetry ('T') & ACKs ('A') to GUI backend.
  - Mitigations Implemented:
      * Priority Queuing: Teleop 'M' packets preempt RTCM packets to eliminate HoL latency spikes.
      * RTCM Chunking: Slices large RTCM bursts into <=256 byte fragments.
      * Fault Isolation: Socket errors or bad packets in RTCM never crash or block the teleop loop.
      * Auto-Reconnecting Serial Watchdog: Reconnects seamlessly if USB is dropped.
"""

import os
import sys
import time
import socket
import select
import collections
import struct
import json
import serial
import serial.tools.list_ports

# -----------------------------------------------------------------------------
# Configuration import (Single Source of Truth)
# -----------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))
from comms_config import (
    TELEOP_XBEE_PORT, XBEE_BAUD_RATE, ROVER_RADIO_ADDR,
    UDP_JOY_PORT, UDP_RTCM_PORT, UDP_STATUS_PORT,
    UDP_LISTEN_IP, MASTER_IP,
    MOTION_PACKET_ID, MOTION_PACKET_SIZE,
    ROVER_IP, ROVER_UDP_LISTEN_PORT, DUAL_REDUNDANCY_ENABLED,
    scan_available_ports, AVAILABLE_BAUD_RATES,
)

# Target radio address
DEST_ADDR_HEX = ROVER_RADIO_ADDR
try:
    DEST_ADDR_BYTES = bytes.fromhex(ROVER_RADIO_ADDR.replace(':', '').replace(' ', ''))
except Exception:
    DEST_ADDR_BYTES = b'\x00\x00\x00\x00\x00\x00\xff\xff'

RTCM_CHUNK_MAX = 256   # Prevent HoL blocking by slicing RTCM frames


def wrap_xbee_api_tx(payload: bytes, dest_64: bytes = None) -> bytes:
    """Wrap payload into an XBee API Mode 1 Transmit Request (0x10) frame."""
    dest = dest_64 if dest_64 and len(dest_64) == 8 else DEST_ADDR_BYTES
    # 0x10, FrameID=0x00 (no TX status), 64-bit addr, 16-bit 0xFFFE, radius=0, option=0x01 (No ACK)
    frame_data = bytes([0x10, 0x00]) + dest + b'\xff\xfe\x00\x01' + payload
    length = len(frame_data)
    checksum = 0xFF - (sum(frame_data) & 0xFF)
    return struct.pack('>BH', 0x7E, length) + frame_data + bytes([checksum])


class BaseMasterHub:
    def __init__(self, serial_port=None, baud=XBEE_BAUD_RATE, rover_ip=None):
        self.port = serial_port if serial_port else TELEOP_XBEE_PORT
        self.baud = int(baud)
        self.rover_ip = rover_ip if rover_ip else ROVER_IP
        self.ser = None
        self.running = True

        # Queues for priority multiplexing
        self.joy_queue = collections.deque()
        self.rtcm_queue = collections.deque()

        # Statistics
        self.stats = {
            'joy_pkts': 0,
            'rtcm_chunks': 0,
            'tx_bytes': 0,
            'rx_pkts': 0,
            'udp_uplink_pkts': 0,
            'last_joy_time': 0.0,
            'last_rtcm_time': 0.0,
            'last_rx_time': 0.0,
            'serial_connected': False,
        }

        # Initialize UDP sockets
        self._init_sockets()
        self._connect_serial()

    def _init_sockets(self):
        """Create and bind non-blocking UDP input sockets and status output socket."""
        # 1. Joystick UDP socket (Port 9001)
        self.joy_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.joy_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.joy_sock.bind((UDP_LISTEN_IP, UDP_JOY_PORT))
        self.joy_sock.setblocking(False)

        # 2. RTCM UDP socket (Port 9002)
        self.rtcm_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtcm_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.rtcm_sock.bind((UDP_LISTEN_IP, UDP_RTCM_PORT))
        self.rtcm_sock.setblocking(False)

        # 3. Status forwarding UDP socket (Sends to Port 9003)
        self.status_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.status_target = (MASTER_IP, UDP_STATUS_PORT)

        # 4. Outgoing Dual-Redundant UDP socket to Rover (Port 8888)
        self.rover_udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rover_udp_target = (self.rover_ip, ROVER_UDP_LISTEN_PORT)

        print(f"[BaseMaster] UDP input bound: Joy -> port {UDP_JOY_PORT}, RTCM -> port {UDP_RTCM_PORT}")
        print(f"[BaseMaster] UDP output status target: {self.status_target}")
        print(f"[BaseMaster] Dual-Redundancy Uplink Target: {self.rover_udp_target}")

    def _connect_serial(self):
        """Attempt to open non-blocking serial port with auto-recovery."""
        if self.ser and self.ser.is_open:
            return True
        try:
            self.ser = serial.Serial(
                self.port,
                self.baud,
                timeout=0,
                write_timeout=0
            )
            self.stats['serial_connected'] = True
            print(f"[BaseMaster] Serial radio CONNECTED on {self.port} @ {self.baud} baud")
            return True
        except Exception as e:
            self.stats['serial_connected'] = False
            self.ser = None
            return False

    def reconfigure_serial(self, new_port=None, new_baud=None):
        """Reconfigures and reopens the serial port at runtime upon command."""
        changed = False
        if new_port and new_port != self.port:
            print(f"[BaseMaster] Reconfiguring serial port: {self.port} -> {new_port}")
            self.port = str(new_port).strip()
            changed = True
        if new_baud and int(new_baud) != self.baud:
            print(f"[BaseMaster] Reconfiguring baud rate: {self.baud} -> {new_baud}")
            self.baud = int(new_baud)
            changed = True

        if changed or not (self.ser and self.ser.is_open):
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                except Exception:
                    pass
                self.ser = None
            self._connect_serial()
            self._broadcast_heartbeat()

    def _broadcast_heartbeat(self):
        """Send master heartbeat containing port, baud, and link status to UDP 9003."""
        hb = {
            'type': 'master_heartbeat',
            'port': self.port,
            'baud': self.baud,
            'connected': self.stats['serial_connected'],
            'joy_pkts': self.stats['joy_pkts'],
            'rtcm_chunks': self.stats['rtcm_chunks'],
            'rx_pkts': self.stats['rx_pkts'],
        }
        try:
            hb_data = b'H' + json.dumps(hb).encode('utf-8')
            self.status_sock.sendto(hb_data, self.status_target)
        except Exception:
            pass

    def handle_joy_data(self, data: bytes):
        """Handle incoming Joystick 'M' motion packet: sends via XBee + Dual-Redundant UDP."""
        if not data or len(data) < 1:
            return

        # Check for JSON control / reconfigure command (starts with b'K' or b'{')
        if data[0:1] in (b'K', b'{'):
            try:
                raw_json = data[1:] if data[0:1] == b'K' else data
                cfg = json.loads(raw_json.decode('utf-8'))
                action = cfg.get("action", "")
                if action in ("SET_CONFIG", "SET_PORT", "SET_BAUD"):
                    new_port = cfg.get("port")
                    new_baud = cfg.get("baud")
                    self.reconfigure_serial(new_port=new_port, new_baud=new_baud)
                    return
            except Exception as e:
                print(f"[BaseMaster] Error handling control packet: {e}")
                return

        # Validate that it starts with 'M' or 'C'
        if data[0:1] in (b'M', b'C'):
            self.stats['joy_pkts'] += 1
            self.stats['last_joy_time'] = time.monotonic()
            
            # 1. Primary XBee RF queue (preempts RTCM)
            self.joy_queue.clear()
            self.joy_queue.append(data)

            # 2. Dual-Redundant Wi-Fi UDP transmission (simultaneous)
            if DUAL_REDUNDANCY_ENABLED:
                try:
                    self.rover_udp_sock.sendto(data, self.rover_udp_target)
                    self.stats['udp_uplink_pkts'] += 1
                except Exception:
                    pass

            # 3. Forward teleop packet to local GUI backend (UDP 9003)
            try:
                self.status_sock.sendto(data, self.status_target)
            except Exception:
                pass

    def handle_rtcm_data(self, data: bytes):
        """Handle incoming RTCM3 frame: sends via XBee chunks + Dual-Redundant UDP."""
        if not data:
            return
        self.stats['last_rtcm_time'] = time.monotonic()
        
        # 1. Primary XBee RF queue (sliced to avoid HoL)
        for i in range(0, len(data), RTCM_CHUNK_MAX):
            chunk = data[i:i + RTCM_CHUNK_MAX]
            self.rtcm_queue.append(chunk)
            self.stats['rtcm_chunks'] += 1

        # 2. Dual-Redundant Wi-Fi UDP transmission (simultaneous)
        if DUAL_REDUNDANCY_ENABLED:
            try:
                self.rover_udp_sock.sendto(data, self.rover_udp_target)
            except Exception:
                pass

    def flush_tx(self):
        """Drain outgoing packet queues with strict priority for Teleop over RTCM."""
        if not self.ser or not self.ser.is_open:
            return

        # 1. Teleop Priority Drain: Always send pending joy packet first
        if self.joy_queue:
            payload = self.joy_queue.popleft()
            try:
                frame = wrap_xbee_api_tx(payload)
                self.ser.write(frame)
                self.stats['tx_bytes'] += len(frame)
            except Exception as e:
                pass

        # 2. RTCM Drain: If no joy packet is pending, send next RTCM chunk
        elif self.rtcm_queue:
            chunk = self.rtcm_queue.popleft()
            try:
                frame = wrap_xbee_api_tx(chunk)
                self.ser.write(frame)
                self.stats['tx_bytes'] += len(frame)
            except Exception as e:
                pass

    def read_serial_rx(self, rx_buf: bytearray):
        """Read incoming frames from XBee and forward Telemetry/ACKs to UDP 9003."""
        if not self.ser or not self.ser.is_open:
            return
        try:
            chunk = self.ser.read(512)
            if not chunk:
                return
            rx_buf.extend(chunk)

            # Parse API 0x7E frames
            while len(rx_buf) >= 4:
                try:
                    idx = rx_buf.index(0x7E)
                except ValueError:
                    rx_buf.clear()
                    break
                if idx > 0:
                    del rx_buf[:idx]
                if len(rx_buf) < 4:
                    break

                length = (rx_buf[1] << 8) | rx_buf[2]
                frame_len = length + 4
                if len(rx_buf) < frame_len:
                    break

                frame = bytes(rx_buf[:frame_len])
                del rx_buf[:frame_len]

                chk = sum(frame[3:-1]) & 0xFF
                if (chk + frame[-1]) & 0xFF != 0xFF:
                    continue  # Bad checksum

                frame_type = frame[3]
                # 0x90 Receive Packet or 0x10 Loopback Frame
                payload = b''
                if frame_type == 0x90 and len(frame) >= 16:
                    payload = frame[15:-1]
                elif frame_type == 0x10 and len(frame) >= 18:
                    payload = frame[17:-1]

                if payload:
                    self.stats['rx_pkts'] += 1
                    self.stats['last_rx_time'] = time.monotonic()
                    # Forward Telemetry ('T') or ACK ('A') to UDP 9003
                    try:
                        self.status_sock.sendto(payload, self.status_target)
                    except Exception:
                        pass
        except Exception:
            pass

    def run(self):
        """High-performance zero-latency non-blocking event loop using select."""
        rx_buf = bytearray()
        last_reconnect_time = time.monotonic()
        last_heartbeat_time = time.monotonic()

        print("[BaseMaster] Router running. Press Ctrl+C to stop.")

        while self.running:
            try:
                # 1. Non-blocking select on UDP inputs with 5ms timeout
                rlist, _, _ = select.select([self.joy_sock, self.rtcm_sock], [], [], 0.005)

                for s in rlist:
                    if s is self.joy_sock:
                        try:
                            data, _ = self.joy_sock.recvfrom(2048)
                            self.handle_joy_data(data)
                        except BlockingIOError:
                            pass
                    elif s is self.rtcm_sock:
                        try:
                            data, _ = self.rtcm_sock.recvfrom(4096)
                            self.handle_rtcm_data(data)
                        except BlockingIOError:
                            pass

                # 2. Priority Flush to Serial
                self.flush_tx()

                # 3. Read Incoming Downlink from Radio
                self.read_serial_rx(rx_buf)

                # 4. Auto-Reconnect Watchdog (every 2.0s if disconnected)
                now = time.monotonic()
                if now - last_reconnect_time > 2.0:
                    last_reconnect_time = now
                    if not self.ser or not self.ser.is_open:
                        self._connect_serial()

                # 5. Master Heartbeat Forwarder (every 1.0s)
                if now - last_heartbeat_time > 1.0:
                    last_heartbeat_time = now
                    self._broadcast_heartbeat()

            except KeyboardInterrupt:
                print("\n[BaseMaster] Shutting down.")
                break
            except Exception as e:
                # Top-level isolation: never terminate on socket or device hiccup
                time.sleep(0.01)

        # Cleanup
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except Exception:
                pass


if __name__ == '__main__':
    port_arg = sys.argv[1] if len(sys.argv) > 1 else None
    master = BaseMasterHub(serial_port=port_arg)
    master.run()
