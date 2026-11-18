#!/usr/bin/env python3
"""
=============================================================================
   PRODUCTION RTK BASE STATION & XBEE TELEMETRY ENGINE (API MODE 1)
   WITH LIVE TWO-WAY ROVER RECEPTION AUDIT & FEEDBACK
=============================================================================
High-performance, auto-recovering Windows Ground Station controller for 
Quectel LC29H(BS) RTK GPS and Digi XBee Telemetry Radios.

Features:
- Dual-Port Hot-Plug Watchdog: Continuously scans & auto-reconnects USB on drop
- Rover Reception Telemetry: Live feedback confirming other end is receiving RTCM
- Zero-Flicker Live Dashboard: Smooth ANSI terminal refresh with live diagnostics
- High-Speed Stream Processor: Optimized zero-latency NMEA and RTCM3 extraction
- XBee API Mode 1 Engine: Frame Type 0x10 Transmit + Frame 0x8B/0x90 Audit
=============================================================================
"""

# =====================================================================
#                      USER CONFIGURATION SETTINGS
#        (Adjust your COM ports and survey settings right here)
# =====================================================================
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..'))
from comms_config import (
    BASE_GPS_PORT       as GPS_PORT,        # COM port for LC29H(BS) GPS module
    GPS_XBEE_PORT       as XBEE_PORT,       # COM port for Base XBee Transmitter
    GPS_BAUD_RATE       as BAUD_RATE,       # Baud rate for both GPS and XBee
    SURVEY_TIME_SEC,                        # Minimum observation time in seconds
    SURVEY_ACCURACY_M,                      # Target survey-in accuracy threshold in meters
    XBEE_BROADCAST_ADDR as DEST_64_ADDR,   # 64-bit API Broadcast address
    UDP_RTCM_PORT,
    MASTER_IP,
)
# =====================================================================

import socket
import serial
import serial.tools.list_ports
import time
import json
import os
import sys
import collections
import argparse

# Enable Virtual Terminal Processing (ANSI escape sequences) & UTF-8 output on Windows
os.system('')
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class DiagnosticLogger:
    """Thread-safe circular log buffer for live terminal display"""
    def __init__(self, max_entries=5):
        self.logs = collections.deque(maxlen=max_entries)
        self.add_log("INFO", "System initialized in XBee API Mode 1.")

    def add_log(self, level, message):
        ts = time.strftime("%H:%M:%S")
        self.logs.append((ts, level, message))

    def get_logs(self):
        return list(self.logs)


class RTKBaseStationEngine:
    def __init__(self, gps_port=GPS_PORT, xbee_port=XBEE_PORT, baud=BAUD_RATE, 
                 survey_time=SURVEY_TIME_SEC, survey_acc=SURVEY_ACCURACY_M):
        self.gps_port = gps_port
        self.xbee_port = xbee_port
        self.baud = baud
        self.survey_time = survey_time
        self.survey_acc = survey_acc

        self.gps_ser = None
        self.xbee_ser = None

        # Connection States
        self.gps_online = False
        self.xbee_online = False
        self.last_gps_reconnect_try = 0
        self.last_xbee_reconnect_try = 0

        # Performance & Throughput Metrics
        self.gps_bytes_sec = 0
        self.gps_bytes_window = 0
        self.last_rate_calc = time.time()
        self.xbee_tx_bytes = 0
        self.xbee_tx_pkts = 0
        self.xbee_ack_count = 0
        self.xbee_fail_count = 0
        self.last_tx_time = 0
        self.last_delivery_status = "\033[1;33m● Waiting for transmission...\033[0m"

        # Base GPS Navigation Telemetry
        self.num_sats = 0
        self.lat = 0.0
        self.lon = 0.0
        self.alt = 0.0
        self.hdop = 99.9
        self.fix_quality = 0
        self.svin_valid = False
        self.svin_elapsed = 0
        self.svin_acc = 999.0

        # Rover (Other End) Live Telemetry State
        self.rover_last_ping_time = None
        self.rover_fix = "NO LINK"
        self.rover_qual = 0
        self.rover_rtcm_in_rover = 0
        self.rover_lat = None
        self.rover_lon = None
        self.rover_gps_connected = False
        self.ROVER_TIMEOUT_SEC = 5.0
        self.rover_feedback_raw = ""

        # Memory-Efficient Buffers
        self.gps_buf = bytearray()
        self.xbee_buf = bytearray()
        self.frame_id_counter = 1
        self.logger = DiagnosticLogger(max_entries=5)

        # Base Master Hub UDP Socket (zero-latency forwarding)
        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_target = (MASTER_IP, UDP_RTCM_PORT)
        self.rtcm_udp_count = 0

        # First Screen Render Flag
        self.screen_initialized = False

    # -------------------------------------------------------------------------
    # HARDWARE CONNECTION & AUTO-RECOVERY WATCHDOG
    # -------------------------------------------------------------------------
    def handle_gps_disconnect(self):
        if self.gps_online:
            self.gps_online = False
            self.logger.add_log("ERROR", f"GPS USB removed from {self.gps_port}! Auto-watchdog scanning...")
        if self.gps_ser:
            try: self.gps_ser.close()
            except Exception: pass
            self.gps_ser = None

    def handle_xbee_disconnect(self):
        if self.xbee_online:
            self.xbee_online = False
            self.logger.add_log("ERROR", f"XBee USB removed from {self.xbee_port}! Auto-watchdog scanning...")
        if self.xbee_ser:
            try: self.xbee_ser.close()
            except Exception: pass
            self.xbee_ser = None

    def scan_and_reconnect(self):
        """Non-blocking watchdog that detects disconnects, scans ports, and auto-reconnects"""
        now = time.time()

        # Check GPS Connection
        if not self.gps_online and (now - self.last_gps_reconnect_try > 1.5):
            self.last_gps_reconnect_try = now
            self.try_connect_gps()

        # Check XBee Connection
        if not self.xbee_online and (now - self.last_xbee_reconnect_try > 1.5):
            self.last_xbee_reconnect_try = now
            self.try_connect_xbee()

    def try_connect_gps(self):
        try:
            ports = serial.tools.list_ports.comports()
            port_names = [p.device for p in ports]

            # If current port is not plugged in, check if device moved to another port
            target_port = self.gps_port
            if target_port not in port_names:
                for p in ports:
                    desc = p.description.lower()
                    if ("cp210" in desc or "silicon labs" in desc or "ch34" in desc) and p.device != self.xbee_port:
                        target_port = p.device
                        self.gps_port = target_port
                        break

            if target_port not in port_names:
                return

            if self.gps_ser:
                try: self.gps_ser.close()
                except Exception: pass
                self.gps_ser = None

            s = None
            for test_baud in [self.baud, 9600, 460800]:
                try:
                    candidate = serial.Serial(target_port, test_baud, timeout=0.2)
                    time.sleep(0.15)
                    data = candidate.read(candidate.in_waiting or 32)
                    if len(data) > 0 or test_baud == self.baud:
                        s = candidate
                        if test_baud != self.baud:
                            self.send_cmd_raw(s, f"PAIR050,0,{self.baud}")
                            time.sleep(0.15)
                            s.close()
                            s = serial.Serial(target_port, self.baud, timeout=0.05)
                        break
                except Exception:
                    continue

            if s and s.is_open:
                self.gps_ser = s
                self.gps_online = True
                self.configure_bs_module()
                self.logger.add_log("OK", f"GPS reconnected on {target_port} @ {self.baud} baud.")
        except Exception:
            self.handle_gps_disconnect()

    def try_connect_xbee(self):
        try:
            ports = serial.tools.list_ports.comports()
            port_names = [p.device for p in ports]

            target_port = self.xbee_port
            if target_port not in port_names:
                for p in ports:
                    desc = p.description.lower()
                    if ("xbee" in desc or "ftdi" in desc or "usb serial" in desc) and p.device != self.gps_port:
                        target_port = p.device
                        self.xbee_port = target_port
                        break

            if target_port not in port_names:
                return

            if self.xbee_ser:
                try: self.xbee_ser.close()
                except Exception: pass
                self.xbee_ser = None

            s = serial.Serial(target_port, self.baud, timeout=0.05)
            if s and s.is_open:
                self.xbee_ser = s
                self.xbee_online = True
                self.logger.add_log("OK", f"XBee reconnected on {target_port} (API Mode 1).")
        except Exception:
            self.handle_xbee_disconnect()

    def send_cmd_raw(self, ser_handle, cmd_body):
        xor = 0
        for b in cmd_body.encode('ascii'):
            xor ^= b
        full_cmd = f"${cmd_body}*{xor:02X}\r\n"
        try:
            ser_handle.write(full_cmd.encode('ascii'))
            time.sleep(0.04)
        except Exception:
            pass

    def configure_bs_module(self):
        if not self.gps_ser or not self.gps_ser.is_open:
            return

        # Force NMEA ON ($PAIR062,-1,1)
        self.send_cmd_raw(self.gps_ser, "PAIR062,-1,1")
        self.send_cmd_raw(self.gps_ser, "PAIR062,0,1")  # GGA
        self.send_cmd_raw(self.gps_ser, "PAIR062,3,1")  # GSV
        self.send_cmd_raw(self.gps_ser, "PAIR062,4,1")  # RMC

        # Output update rate = 1Hz
        self.send_cmd_raw(self.gps_ser, "PAIR050,1000")

        # Configure Survey-In
        self.send_cmd_raw(self.gps_ser, f"PQTMCFGSVIN,W,1,{self.survey_time},{int(self.survey_acc)},0,0,0")
        self.send_cmd_raw(self.gps_ser, "PQTMCFGMSGRATE,W,PQTMSVINSTATUS,1,1")

        # Enable RTCM3 Messages
        for msg in [1005, 1077, 1087, 1097, 1127]:
            self.send_cmd_raw(self.gps_ser, f"PQTMCFGRTCM,W,1,{msg},1")

        # Save to Flash
        self.send_cmd_raw(self.gps_ser, "PQTMSAVEPAR")
        self.logger.add_log("INFO", "LC29H(BS) configured: NMEA + Survey-In + RTCM3 active.")

    # -------------------------------------------------------------------------
    # XBEE API MODE 1 FRAME BUILDER & PARSER
    # -------------------------------------------------------------------------
    def build_xbee_api_frame(self, rtcm_payload):
        """Encapsulates RTCM3 into Digi API Frame Type 0x10 (Transmit Request)"""
        frame_type = b'\x10'
        frame_id = bytes([self.frame_id_counter])
        self.frame_id_counter = (self.frame_id_counter % 254) + 1

        dest_64 = DEST_64_ADDR
        dest_16 = b'\xff\xfe'
        broadcast_radius = b'\x00'
        options = b'\x00'

        frame_data = frame_type + frame_id + dest_64 + dest_16 + broadcast_radius + options + rtcm_payload
        length = len(frame_data)
        len_bytes = length.to_bytes(2, byteorder='big')
        checksum = 0xFF - (sum(frame_data) & 0xFF)

        return b'\x7e' + len_bytes + frame_data + bytes([checksum])

    def parse_rover_telemetry(self, payload):
        """Decodes the JSON heartbeat ping or colon-separated text sent by Rover"""
        self.process_rover_payload(payload)

    def process_rover_payload(self, payload):
        """Decodes the JSON heartbeat ping sent by the Rover over XBee."""
        try:
            if isinstance(payload, bytes) or isinstance(payload, bytearray):
                text = payload.decode('utf-8', errors='ignore').strip()
            else:
                text = str(payload).strip()
            self.rover_feedback_raw = text

            if "ROVER_PING" in text:
                data = json.loads(text)
                was_offline = (self.rover_last_ping_time is None) or ((time.time() - self.rover_last_ping_time) > self.ROVER_TIMEOUT_SEC)
                self.rover_last_ping_time = time.time()
                self.rover_fix            = data.get("fix", "UNKNOWN")
                self.rover_qual           = data.get("qual", 0)
                self.rover_rtcm_in_rover  = data.get("rtcm", 0)
                self.rover_lat            = data.get("lat")
                self.rover_lon            = data.get("lon")
                self.rover_gps_connected  = data.get("gps_connected", False)
                if was_offline:
                    self.logger.add_log("OK", f"ROVER CONNECTED! Fix: {self.rover_fix} | RTCM: {self.rover_rtcm_in_rover}")
            elif text.startswith("ROVER:"):
                parts = text.split(':')
                if len(parts) >= 5:
                    was_offline = (self.rover_last_ping_time is None) or ((time.time() - self.rover_last_ping_time) > self.ROVER_TIMEOUT_SEC)
                    self.rover_last_ping_time = time.time()
                    self.rover_rtcm_in_rover  = int(parts[1]) if parts[1].isdigit() else self.rover_rtcm_in_rover
                    self.rover_qual           = int(parts[2]) if parts[2].isdigit() else self.rover_qual
                    self.rover_lat            = float(parts[3]) if parts[3] else self.rover_lat
                    self.rover_lon            = float(parts[4]) if parts[4] else self.rover_lon
                    self.rover_gps_connected  = True
                    fix_names = {0: "NO FIX", 1: "3D FIX", 2: "DGPS", 4: "RTK FIXED", 5: "RTK FLOAT"}
                    self.rover_fix            = fix_names.get(self.rover_qual, f"Q{self.rover_qual}")
                    if was_offline:
                        self.logger.add_log("OK", f"ROVER CONNECTED! Fix: {self.rover_fix} | RTCM: {self.rover_rtcm_in_rover}")
        except Exception:
            pass

    def process_xbee_frames(self):
        """Parses incoming XBee API frames (0x8B Transmit Status, 0x90/0x91/0x80/0x81 RX Packet, or Transparent JSON)"""
        while len(self.xbee_buf) >= 3:
            if self.xbee_buf[0] != 0x7E:
                # Case A: Transparent JSON (starts with '{')
                if self.xbee_buf[0] == ord('{'):
                    idx = self.xbee_buf.find(b'\n')
                    if idx != -1:
                        payload = self.xbee_buf[:idx]
                        del self.xbee_buf[:idx+1]
                        self.parse_rover_telemetry(payload)
                        continue
                    else:
                        break
                # Case B: Transparent colon format (starts with 'ROVER:')
                elif self.xbee_buf.startswith(b'ROVER:'):
                    idx = self.xbee_buf.find(b'\n')
                    if idx != -1:
                        payload = self.xbee_buf[:idx]
                        del self.xbee_buf[:idx+1]
                        self.parse_rover_telemetry(payload)
                        continue
                    else:
                        break
                del self.xbee_buf[0]
                continue

            frame_len = (self.xbee_buf[1] << 8) | self.xbee_buf[2]
            total_api_len = 3 + frame_len + 1
            if len(self.xbee_buf) >= total_api_len:
                frame_data = self.xbee_buf[3:3+frame_len]
                del self.xbee_buf[:total_api_len]

                frame_type = frame_data[0]

                # 0x8B: Transmit Status Frame (Delivery Confirmation)
                if frame_type == 0x8B and len(frame_data) >= 6:
                    delivery_status = frame_data[5]
                    if delivery_status == 0x00:
                        self.last_delivery_status = "\033[1;32m● DELIVERED (ACK Received)\033[0m"
                        self.xbee_ack_count += 1
                    elif delivery_status == 0x24:
                        self.last_delivery_status = "\033[1;31m● ADDRESS NOT FOUND (Check Rover radio/PAN)\033[0m"
                        self.xbee_fail_count += 1
                    elif delivery_status == 0x21:
                        self.last_delivery_status = "\033[1;31m● NO ACK (No Response from Rover radio)\033[0m"
                        self.xbee_fail_count += 1
                    else:
                        self.last_delivery_status = f"\033[1;31m● ERROR (Code 0x{delivery_status:02X})\033[0m"
                        self.xbee_fail_count += 1

                # RX Frames from Rover (0x90, 0x91, 0x80, 0x81)
                elif frame_type == 0x90 and len(frame_data) > 12:
                    self.parse_rover_telemetry(frame_data[12:])
                elif frame_type == 0x91 and len(frame_data) > 18:
                    self.parse_rover_telemetry(frame_data[18:])
                elif frame_type == 0x80 and len(frame_data) > 11:
                    self.parse_rover_telemetry(frame_data[11:])
                elif frame_type == 0x81 and len(frame_data) > 5:
                    self.parse_rover_telemetry(frame_data[5:])
            else:
                break

    # -------------------------------------------------------------------------
    # HIGH-SPEED STREAM PROCESSOR (NMEA & RTCM3)
    # -------------------------------------------------------------------------
    def parse_coordinate(self, val_str, hemi):
        if not val_str: return 0.0
        dot = val_str.find('.')
        if dot < 2: return 0.0
        deg = float(val_str[:dot-2]) + float(val_str[dot-2:]) / 60.0
        return -deg if hemi in ['S', 'W'] else deg

    def process_nmea(self, line):
        if line.startswith(("$GNGGA", "$GPGGA")):
            parts = line.split(',')
            if len(parts) >= 10:
                self.fix_quality = int(parts[6]) if parts[6] else 0
                self.num_sats = int(parts[7]) if parts[7] else 0
                self.hdop = float(parts[8]) if parts[8] else 99.9
                self.lat = self.parse_coordinate(parts[2], parts[3])
                self.lon = self.parse_coordinate(parts[4], parts[5])
                self.alt = float(parts[9]) if parts[9] else 0.0

        elif "$PQTMSVINSTATUS" in line:
            parts = line.split('*')[0].split(',')
            if len(parts) >= 4:
                status_val = '0'
                time_val = '0'
                if len(parts) >= 5 and parts[2] in ['0', '1', '2'] and parts[3].isdigit():
                    status_val = parts[2]
                    time_val = parts[3]
                elif parts[1] in ['0', '1', '2'] and parts[2].isdigit():
                    status_val = parts[1]
                    time_val = parts[2]
                elif len(parts) >= 5 and parts[3] in ['0', '1', '2'] and parts[4].isdigit():
                    status_val = parts[3]
                    time_val = parts[4]

                prev_valid = self.svin_valid
                self.svin_valid = (status_val == '2')
                if time_val.isdigit():
                    self.svin_elapsed = int(time_val)
                try:
                    self.svin_acc = float(parts[-1].strip())
                except Exception:
                    pass

                if self.svin_valid and not prev_valid:
                    self.logger.add_log("OK", "SURVEY COMPLETE! Position locked and broadcasting.")

    def run_stream_cycle(self):
        """Zero-latency stream reader and forwarder"""
        # 1. Read GPS Data
        if self.gps_online and self.gps_ser:
            try:
                avail = self.gps_ser.in_waiting
                if avail > 0:
                    chunk = self.gps_ser.read(avail)
                    self.gps_buf.extend(chunk)
                    self.gps_bytes_window += len(chunk)

                # Process buffer
                while len(self.gps_buf) > 0:
                    # NMEA line
                    if self.gps_buf[0] == ord('$'):
                        idx = self.gps_buf.find(b'\n')
                        if idx != -1:
                            line = self.gps_buf[:idx].decode('ascii', errors='ignore').strip()
                            del self.gps_buf[:idx+1]
                            self.process_nmea(line)
                        else:
                            break
                    # RTCM3 frame
                    elif self.gps_buf[0] == 0xD3:
                        if len(self.gps_buf) >= 3:
                            pkt_len = ((self.gps_buf[1] & 0x03) << 8) | self.gps_buf[2]
                            total = 3 + pkt_len + 3
                            if len(self.gps_buf) >= total:
                                rtcm_frame = self.gps_buf[:total]
                                del self.gps_buf[:total]

                                # Encapsulate and transmit over XBee API
                                if self.xbee_online and self.xbee_ser:
                                    try:
                                        api_pkt = self.build_xbee_api_frame(rtcm_frame)
                                        self.xbee_ser.write(api_pkt)
                                        self.xbee_tx_pkts += 1
                                        self.xbee_tx_bytes += len(api_pkt)
                                        self.last_tx_time = time.time()
                                    except (serial.SerialException, OSError):
                                        self.handle_xbee_disconnect()

                                # Forward raw RTCM frame to Base Master Hub via UDP
                                try:
                                    self.udp_sock.sendto(rtcm_frame, self.udp_target)
                                    self.rtcm_udp_count += 1
                                except Exception:
                                    pass
                            else:
                                break
                        else:
                            break
                    else:
                        del self.gps_buf[0]

            except (serial.SerialException, OSError):
                self.handle_gps_disconnect()

        # 2. Read XBee Status & ACKs / Rover Return Packets
        if self.xbee_online and self.xbee_ser:
            try:
                avail = self.xbee_ser.in_waiting
                if avail > 0:
                    self.xbee_buf.extend(self.xbee_ser.read(avail))
                    self.process_xbee_frames()
            except (serial.SerialException, OSError):
                self.handle_xbee_disconnect()

        # Prevent buffer overflow
        if len(self.gps_buf) > 4096:
            del self.gps_buf[:2048]
        if len(self.xbee_buf) > 4096:
            del self.xbee_buf[:2048]

    # -------------------------------------------------------------------------
    # FLICKER-FREE LIVE TERMINAL DASHBOARD
    # -------------------------------------------------------------------------
    def render_dashboard(self):
        now = time.time()
        # Compute GPS data rate
        dt = now - self.last_rate_calc
        if dt >= 1.0:
            self.gps_bytes_sec = self.gps_bytes_window / dt
            self.gps_bytes_window = 0
            self.last_rate_calc = now

        # Progress bar
        progress = min(100, int((self.svin_elapsed / self.survey_time) * 100))
        bar = "█" * int(20 * progress / 100) + "░" * (20 - int(20 * progress / 100))

        # Hardware connection badges
        gps_status = "\033[1;32m● ONLINE\033[0m" if self.gps_online else "\033[1;31m● DISCONNECTED (Scanning...)\033[0m"
        xbee_status = "\033[1;32m● ONLINE\033[0m" if self.xbee_online else "\033[1;31m● DISCONNECTED (Scanning...)\033[0m"

        # Satellite tracking badge
        if self.num_sats >= 10:
            sats_str = f"\033[1;32m● {self.num_sats} in use (Optimal)\033[0m"
        elif self.num_sats >= 4:
            sats_str = f"\033[1;33m● {self.num_sats} in use (Moderate)\033[0m"
        elif self.num_sats > 0:
            sats_str = f"\033[1;31m● {self.num_sats} in use (Low)\033[0m"
        else:
            sats_str = "\033[1;31m● 0 in use (No Signal - Antenna Indoors)\033[0m"

        # Solution state badge
        if self.num_sats == 0:
            fix_str = "\033[1;31m● SEARCHING (Antenna needs open sky view)\033[0m"
        elif self.fix_quality == 0:
            fix_str = "\033[1;33m● NO FIX (Acquiring Satellites...)\033[0m"
        else:
            fix_str = f"\033[1;32m● 3D FIX (HDOP: {self.hdop:.2f})\033[0m"

        # Survey-In badge
        if self.svin_valid:
            svin_str = f"[\033[1;32m{bar}\033[0m] \033[1;32m● 100% (SURVEY LOCKED - BASE STATION ACTIVE)\033[0m"
        elif self.num_sats >= 4 and self.fix_quality > 0:
            svin_str = f"[\033[1;33m{bar}\033[0m] \033[1;33m● {progress}% ({self.svin_elapsed}s / {self.survey_time}s - Surveying...)\033[0m"
        else:
            svin_str = f"[\033[1;31m{bar}\033[0m] \033[1;31m● PAUSED (Waiting for GPS 3D Fix)\033[0m"

        # Transmission state badge
        tx_active = (now - self.last_tx_time) < 2.0 if self.last_tx_time > 0 else False
        if not self.xbee_online:
            tx_str = "\033[1;31m● OFFLINE\033[0m"
        elif tx_active:
            tx_str = "\033[1;32m● TRANSMITTING\033[0m"
        else:
            tx_str = "\033[1;33m● IDLE\033[0m"

        # Radio delivery success rate
        total_eval = self.xbee_ack_count + self.xbee_fail_count
        ack_pct = (self.xbee_ack_count / total_eval * 100) if total_eval > 0 else 100.0
        if total_eval == 0:
            ack_str = "\033[1;33m● 100.0%\033[0m (0 ACK / 0 Fail)"
        elif ack_pct >= 90.0:
            ack_str = f"\033[1;32m● {ack_pct:.1f}%\033[0m (\033[1;32m{self.xbee_ack_count} ACK\033[0m / {self.xbee_fail_count} Fail)"
        elif ack_pct >= 70.0:
            ack_str = f"\033[1;33m● {ack_pct:.1f}%\033[0m (\033[1;33m{self.xbee_ack_count} ACK\033[0m / \033[1;33m{self.xbee_fail_count} Fail\033[0m)"
        else:
            ack_str = f"\033[1;31m● {ack_pct:.1f}%\033[0m ({self.xbee_ack_count} ACK / \033[1;31m{self.xbee_fail_count} Fail\033[0m)"

        # Rover (Other End) Reception Status Evaluation
        rover_connected = False
        if self.rover_last_ping_time is None:
            rover_link = "\033[1;33m● WAITING FOR ROVER PING...\033[0m"
            rover_gps_str = "--"
            rover_fix_str = "--"
            rover_rtcm_str = "--"
            rover_coord_str = "--"
        elif (now - self.rover_last_ping_time) > self.ROVER_TIMEOUT_SEC:
            silent_sec = int(now - self.rover_last_ping_time)
            rover_link = f"\033[1;31m● OFFLINE / DISCONNECTED (Silent for {silent_sec}s)\033[0m"
            rover_gps_str = "\033[1;31m● DISCONNECTED\033[0m"
            rover_fix_str = f"{self.rover_fix} (Last Known)"
            rover_rtcm_str = f"{self.rover_rtcm_in_rover} pkts"
            rover_coord_str = f"{self.rover_lat:.8f}, {self.rover_lon:.8f}" if self.rover_lat else "--"
        else:
            rover_connected = True
            ping_age = int(now - self.rover_last_ping_time)
            rover_link = f"\033[1;32m● CONNECTED & TRANSMITTING\033[0m (Ping: {ping_age}s ago)"
            rover_gps_str = "\033[1;32m● CONNECTED\033[0m" if self.rover_gps_connected else "\033[1;31m● DISCONNECTED\033[0m"

            fix_upper = str(self.rover_fix).upper()
            if "FIXED" in fix_upper:
                rover_fix_str = f"\033[1;32m● {self.rover_fix} (1-2 cm Accuracy)\033[0m"
            elif "FLOAT" in fix_upper:
                rover_fix_str = f"\033[1;33m● {self.rover_fix} (10-40 cm Accuracy)\033[0m"
            elif "3D" in fix_upper:
                rover_fix_str = f"\033[1;36m● {self.rover_fix}\033[0m"
            else:
                rover_fix_str = f"\033[1;31m● {self.rover_fix}\033[0m"

            rover_rtcm_str = f"\033[1;32m● {self.rover_rtcm_in_rover}\033[0m pkts received"
            rover_coord_str = f"{self.rover_lat:.8f}, {self.rover_lon:.8f}" if self.rover_lat else "Searching satellites..."

        # Dynamic Status Banner
        if not self.gps_online or not self.xbee_online:
            banner = "\033[1;41;37m  ● HARDWARE WARNING: USB DISCONNECTED -> WATCHDOG AUTO-SCANNING   \033[0m"
        elif self.num_sats == 0:
            banner = "\033[1;41;37m  ● ATTENTION: 0 SATELLITES TRACKED -> PLACE ANTENNA OUTDOORS      \033[0m"
        elif not rover_connected:
            if self.svin_valid:
                banner = "\033[1;43;30m  ● SURVEY COMPLETE | WAITING FOR ROVER XBEE TELEMETRY             \033[0m"
            else:
                banner = "\033[1;43;30m  ● SURVEYING BASE POSITION | ROVER XBEE NOT DETECTED              \033[0m"
        elif self.svin_valid and "FIXED" in str(self.rover_fix).upper():
            banner = "\033[1;42;37m  ● RTK SYSTEM FULLY LOCKED | ROVER RTK FIXED (1-2 CM ACCURACY)    \033[0m"
        elif self.svin_valid:
            banner = f"\033[1;42;37m  ● SURVEY COMPLETE | ROVER LINK ACTIVE ({self.rover_fix})          \033[0m"
        else:
            banner = f"\033[1;42;37m  ● ROVER LINK ACTIVE ({self.rover_fix}) | SURVEYING BASE POSITION  \033[0m"

        if not self.screen_initialized:
            os.system('cls')
            self.screen_initialized = True
        
        output = []
        output.append("\033[H")  # Move cursor to top-left
        output.append("==================================================================")
        output.append("     RTK BASE STATION & XBEE TELEMETRY ENGINE (API MODE 1)        ")
        output.append("==================================================================")
        output.append(" \033[1;36m[ HARDWARE & WATCHDOG ]\033[0m")
        output.append(f"    - GPS Receiver [{self.gps_port:<5}] : {gps_status} ({self.gps_bytes_sec/1024:.1f} KB/s)")
        output.append(f"    - XBee Radio   [{self.xbee_port:<5}] : {xbee_status} (Baud: {self.baud})")
        output.append("------------------------------------------------------------------")
        output.append(" \033[1;36m[ BASE SATELLITE & POSITION ]\033[0m")
        output.append(f"    - Satellites Tracked: {sats_str}")
        output.append(f"    - Solution State    : {fix_str}")
        output.append(f"    - Base Coordinates  : {self.lat:.7f} deg, {self.lon:.7f} deg (Alt: {self.alt:.2f} m)")
        output.append("------------------------------------------------------------------")
        output.append(" \033[1;36m[ BASE SURVEY-IN ]\033[0m")
        output.append(f"    - Survey Progress   : {svin_str}")
        output.append("------------------------------------------------------------------")
        output.append(" \033[1;36m[ XBEE RF TELEMETRY (API MODE 1) ]\033[0m")
        output.append(f"    - Destination Target: 000000000000FFFF (Broadcast)")
        output.append(f"    - Transmit Stream   : {tx_str} -> {self.xbee_tx_pkts} frames ({self.xbee_tx_bytes/1024:.1f} KB)")
        output.append(f"    - Radio Delivery    : {self.last_delivery_status}")
        output.append(f"    - Success Rate      : {ack_str}")
        output.append("------------------------------------------------------------------")
        output.append(" \033[1;36m[ ROVER RF LINK & TELEMETRY (PING FEEDBACK) ]\033[0m")
        output.append(f"    - Rover RF Link     : {rover_link}")
        output.append(f"    - Rover GPS Module  : {rover_gps_str}")
        output.append(f"    - Rover Fix Mode    : {rover_fix_str}")
        output.append(f"    - Rover RTCM Ingest : {rover_rtcm_str}")
        output.append(f"    - Rover Coordinates : {rover_coord_str}")
        output.append("------------------------------------------------------------------")
        output.append(" \033[1;36m[ SYSTEM LOG (Auto-Scroll) ]\033[0m")
        for ts, lvl, msg in self.logger.get_logs():
            color = "\033[1;32m" if lvl == "OK" else ("\033[1;31m" if lvl == "ERROR" else ("\033[1;33m" if lvl == "WARN" else "\033[1;36m"))
            bullet = "\033[1;32m●\033[0m" if lvl == "OK" else ("\033[1;31m●\033[0m" if lvl == "ERROR" else ("\033[1;33m●\033[0m" if lvl == "WARN" else "\033[1;36m●\033[0m"))
            output.append(f"    {bullet} [{ts}] {color}[{lvl:<5}]\033[0m {msg}")
        output.append("==================================================================")
        output.append(banner)
        output.append("==================================================================")
        output.append(" Press Ctrl+C to terminate.")

        sys.stdout.write("\n".join(output) + "\n")
        sys.stdout.flush()

    # -------------------------------------------------------------------------
    # MAIN EVENT LOOP
    # -------------------------------------------------------------------------
    def start(self):
        print("\n========================================================")
        print("   Initializing Optimized Base Station Controller...    ")
        print("========================================================")
        self.try_connect_gps()
        self.try_connect_xbee()

        last_display = 0
        last_watchdog = 0

        while True:
            try:
                now = time.time()

                # 1. High-frequency zero-latency serial streaming
                self.run_stream_cycle()

                # 2. Background USB hot-plug watchdog (every 1.5 seconds)
                if now - last_watchdog >= 1.5:
                    self.scan_and_reconnect()
                    last_watchdog = now

                # 3. Smooth terminal rendering (every 1.0 second)
                if now - last_display >= 1.0:
                    self.render_dashboard()
                    last_display = now

                time.sleep(0.005)

            except KeyboardInterrupt:
                print("\n\n[!] Safely closing serial ports and stopping Base Station...")
                break
            except Exception as e:
                self.logger.add_log("ERROR", f"Runtime exception: {e}")

        if self.gps_ser:
            try: self.gps_ser.close()
            except: pass
        if self.xbee_ser:
            try: self.xbee_ser.close()
            except: pass
        print("[+] Base Station terminated cleanly.\n")


def list_ports():
    ports = serial.tools.list_ports.comports()
    print("\n--- Detected Connected COM Ports ---")
    if not ports:
        print("  (No COM ports detected)")
    for p in ports:
        print(f"  • {p.device}: {p.description}")
    print("------------------------------------\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Optimized Windows RTK Base Station Controller")
    parser.add_argument('--gps', type=str, default=GPS_PORT, help=f'COM port for LC29H(BS) (default: {GPS_PORT})')
    parser.add_argument('--xbee', type=str, default=XBEE_PORT, help=f'COM port for Base XBee (default: {XBEE_PORT})')
    parser.add_argument('--baud', type=int, default=BAUD_RATE, help=f'Baud rate (default: {BAUD_RATE})')
    parser.add_argument('--list', action='store_true', help='List available COM ports')

    args = parser.parse_args()

    if args.list:
        list_ports()
        sys.exit(0)

    engine = RTKBaseStationEngine(gps_port=args.gps, xbee_port=args.xbee, baud=args.baud)
    engine.start()
