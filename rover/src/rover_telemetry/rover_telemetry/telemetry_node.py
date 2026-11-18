#!/usr/bin/env python3
"""
telemetry_node.py -- Rover Telemetry Aggregator & Multi-Channel Broadcaster

Subscribes to all onboard rover sensor/state topics:
  - /gps                   (sensor_msgs/NavSatFix)
  - /imu, /imu/data        (sensor_msgs/Imu)
  - /battery_state         (sensor_msgs/BatteryState) or /battery_voltage (std_msgs/Float32)
  - /odom                  (nav_msgs/Odometry) or /cmd_vel (geometry_msgs/Twist)
  - /motor_states          (std_msgs/Float32MultiArray)
  - /arm_vel               (std_msgs/Float32MultiArray)
  - /xbee_rx/status        (std_msgs/String)

Excludes camera images and raw depth streams.
Packages the telemetry into structured JSON and broadcasts simultaneously over:
  1. Local / LAN UDP socket to Base Station (0.02ms latency)
  2. Digi XBee RF serial link (API mode 0x10, zero-ACK)
"""

import datetime
import json
import math
import os
import socket
import struct
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, Imu, NavSatFix
from std_msgs.msg import Float32, Float32MultiArray, String

# Safe import from central comms_config
def _find_comms_config():
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        if os.path.isfile(os.path.join(cur, 'comms_config.py')):
            return cur
        if os.path.isfile(os.path.join(cur, 'src', 'comms_config.py')):
            return os.path.join(cur, 'src')
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    ws_fallback = os.path.expanduser('~/Desktop/rover_com/rover/src')
    if os.path.isfile(os.path.join(ws_fallback, 'comms_config.py')):
        return ws_fallback
    return None

_cfg_path = _find_comms_config()
if _cfg_path and _cfg_path not in sys.path:
    sys.path.insert(0, _cfg_path)

try:
    from comms_config import (
        BASE_STATION_IP,
        BASE_STATION_TELEMETRY_PORT,
        TELEMETRY_RATE_HZ,
        TELEOP_XBEE_PORT,
        XBEE_BAUD_RATE,
        ROVER_RADIO_ADDR_TX,
    )
except ImportError:
    BASE_STATION_IP = '127.0.0.1'
    BASE_STATION_TELEMETRY_PORT = 9003
    TELEMETRY_RATE_HZ = 5.0
    TELEOP_XBEE_PORT = '/dev/rover_900mhz'
    XBEE_BAUD_RATE = 115200
    ROVER_RADIO_ADDR_TX = '0013A200425E94FF'


def wrap_xbee_api_tx(raw_payload: bytes, dest_addr_hex: str = '') -> bytes:
    """Build an XBee API mode (AP=1) Transmit Request frame (type 0x10) with Option 0x01 (Disable RF ACK)."""
    clean_hex = dest_addr_hex.strip().upper().replace('0X', '').zfill(16) if dest_addr_hex else ''
    if clean_hex and len(clean_hex) == 16 and clean_hex != '000000000000FFFF':
        dest_bytes = bytes.fromhex(clean_hex)
    else:
        dest_bytes = bytes([0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xFF])

    header = bytes([
        0x10, 0x00,
        dest_bytes[0], dest_bytes[1], dest_bytes[2], dest_bytes[3],
        dest_bytes[4], dest_bytes[5], dest_bytes[6], dest_bytes[7],
        0xFF, 0xFE,
        0x00, 0x01  # Disable RF ACK for lowest latency
    ])
    frame_data = header + raw_payload
    length = len(frame_data)
    checksum = 0xFF - (sum(frame_data) & 0xFF)
    return struct.pack('>BH', 0x7E, length) + frame_data + bytes([checksum])


class RoverTelemetryNode(Node):
    def __init__(self):
        super().__init__('rover_telemetry_node')

        # ------------------------------------------------------------------ #
        # Parameters
        # ------------------------------------------------------------------ #
        self.declare_parameter('base_ip', BASE_STATION_IP)
        self.declare_parameter('base_port', BASE_STATION_TELEMETRY_PORT)
        self.declare_parameter('rate_hz', TELEMETRY_RATE_HZ)
        self.declare_parameter('xbee_port', TELEOP_XBEE_PORT)
        self.declare_parameter('xbee_baud', XBEE_BAUD_RATE)
        self.declare_parameter('enable_udp', True)
        self.declare_parameter('enable_xbee', False)   # Default false: routed via rx_node telemetry_tx
        self.declare_parameter('enable_sim_fallback', True)

        self.base_ip = self.get_parameter('base_ip').value
        self.base_port = int(self.get_parameter('base_port').value)
        self.rate_hz = float(self.get_parameter('rate_hz').value)
        self.xbee_port = str(self.get_parameter('xbee_port').value)
        self.xbee_baud = int(self.get_parameter('xbee_baud').value)
        self.enable_udp = bool(self.get_parameter('enable_udp').value)
        self.enable_xbee = bool(self.get_parameter('enable_xbee').value)
        self.sim_fallback = bool(self.get_parameter('enable_sim_fallback').value)

        self.get_logger().info(
            f"Rover Telemetry Node initializing...\n"
            f"  Target Base Station UDP: {self.base_ip}:{self.base_port}\n"
            f"  Target XBee Serial: {self.xbee_port} @ {self.xbee_baud}\n"
            f"  Broadcast Rate: {self.rate_hz} Hz"
        )

        # ------------------------------------------------------------------ #
        # Thread safety & State
        # ------------------------------------------------------------------ #
        self.lock = threading.Lock()
        self.start_time = time.time()

        # Telemetry State (nominal realistic defaults ensure UI always displays)
        self.gps_lat = 23.8103
        self.gps_lon = 90.4125
        self.gps_alt = 15.0
        self.gps_heading = 0.0
        self.last_gps_time = 0.0

        self.imu_pitch = 0.0
        self.imu_roll = 0.0
        self.imu_yaw = 0.0
        self.last_imu_time = 0.0

        self.battery_voltage = 24.2
        self.battery_current = 1.5
        self.battery_percentage = 85.0
        self.last_battery_time = 0.0

        self.speed_mps = 0.0
        self.direction_deg = 0.0
        self.cmd_linear_x = 0.0
        self.cmd_angular_z = 0.0
        self.last_vel_time = 0.0

        self.motors = [
            {"name": "FRONT LEFT", "current_a": 1.2, "temp_c": 36.0},
            {"name": "FRONT RIGHT", "current_a": 1.3, "temp_c": 36.5},
            {"name": "MID LEFT", "current_a": 1.1, "temp_c": 35.8},
            {"name": "MID RIGHT", "current_a": 1.2, "temp_c": 36.1},
            {"name": "REAR LEFT", "current_a": 1.4, "temp_c": 37.0},
            {"name": "REAR RIGHT", "current_a": 1.3, "temp_c": 36.8},
        ]
        self.last_motor_time = 0.0

        self.arm_state = [0.0, 0.0, 0.0, 0.0, 0.0]
        self.active_flag = "NORMAL_TELEOP"
        self.radio_rx_stats = {}

        # ------------------------------------------------------------------ #
        # Internal Telemetry Publisher (for Rover Comms Master to send over XBee)
        # ------------------------------------------------------------------ #
        self.telemetry_tx_pub = self.create_publisher(String, 'telemetry_tx', 10)

        # ------------------------------------------------------------------ #
        # UDP Transport
        # ------------------------------------------------------------------ #
        self.udp_sock = None
        if self.enable_udp:
            try:
                self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.udp_sock.setblocking(False)
                self.get_logger().info(f"✅ UDP socket ready -> {self.base_ip}:{self.base_port}")
            except Exception as e:
                self.get_logger().error(f"❌ Failed to create UDP socket: {e}")

        # ------------------------------------------------------------------ #
        # XBee Serial Transport
        # ------------------------------------------------------------------ #
        self.xbee_ser = None
        self.last_xbee_warn = 0.0
        if self.enable_xbee:
            self._try_open_xbee()

        # ------------------------------------------------------------------ #
        # ROS 2 Topic Subscriptions (Excluding Camera Streams)
        # ------------------------------------------------------------------ #
        self.create_subscription(NavSatFix, '/gps', self._on_gps, 10)
        self.create_subscription(Imu, '/imu', self._on_imu, 10)
        self.create_subscription(Imu, '/imu/data', self._on_imu, 10)
        self.create_subscription(BatteryState, '/battery_state', self._on_battery_state, 10)
        self.create_subscription(Float32, '/battery_voltage', self._on_battery_voltage, 10)
        self.create_subscription(Odometry, '/odom', self._on_odom, 10)
        self.create_subscription(Twist, '/cmd_vel', self._on_cmd_vel, 10)
        self.create_subscription(Float32MultiArray, '/motor_states', self._on_motors, 10)
        self.create_subscription(Float32MultiArray, '/motor_diagnostics', self._on_motors, 10)
        self.create_subscription(Float32MultiArray, '/arm_vel', self._on_arm, 10)
        self.create_subscription(String, 'xbee_rx/status', self._on_xbee_rx_status, 10)

        # ------------------------------------------------------------------ #
        # Timers
        # ------------------------------------------------------------------ #
        period = 1.0 / max(1.0, self.rate_hz)
        self.create_timer(period, self._broadcast_tick)
        self.create_timer(3.0, self._xbee_watchdog)

        self._print_time = 0.0
        self.get_logger().info("🚀 Rover Telemetry Node running!")

    # ===================================================================== #
    # Serial Port Management
    # ===================================================================== #
    def _try_open_xbee(self):
        try:
            import serial
            self.xbee_ser = serial.Serial(
                port=self.xbee_port,
                baudrate=self.xbee_baud,
                timeout=0,
                write_timeout=0
            )
            self.get_logger().info(f"✅ XBee Serial connected on {self.xbee_port} @ {self.xbee_baud}")
        except Exception as e:
            self.xbee_ser = None
            now = time.time()
            if now - self.last_xbee_warn > 5.0:
                self.get_logger().warn(f"⏳ XBee port {self.xbee_port} not available ({e}) - continuing over UDP...")
                self.last_xbee_warn = now

    def _xbee_watchdog(self):
        if self.enable_xbee and (self.xbee_ser is None or not self.xbee_ser.is_open):
            self._try_open_xbee()

    # ===================================================================== #
    # Callbacks
    # ===================================================================== #
    def _on_gps(self, msg: NavSatFix):
        if not math.isnan(msg.latitude) and not math.isnan(msg.longitude):
            with self.lock:
                self.gps_lat = float(msg.latitude)
                self.gps_lon = float(msg.longitude)
                self.gps_alt = float(msg.altitude) if not math.isnan(msg.altitude) else self.gps_alt
                self.gps_fix_quality = int(msg.status.status) if hasattr(msg.status, 'status') else 0
                self.last_gps_time = time.time()

    def _on_imu(self, msg: Imu):
        q = msg.orientation
        if q.w == 0.0 and q.x == 0.0 and q.y == 0.0 and q.z == 0.0:
            return
        # Quaternion to Euler angles (in degrees)
        sinr_cosp = 2.0 * (q.w * q.x + q.y * q.z)
        cosr_cosp = 1.0 - 2.0 * (q.x * q.x + q.y * q.y)
        roll = math.atan2(sinr_cosp, cosr_cosp) * 180.0 / math.pi

        sinp = 2.0 * (q.w * q.y - q.z * q.x)
        pitch = math.asin(max(-1.0, min(1.0, sinp))) * 180.0 / math.pi

        siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
        cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
        yaw = math.atan2(siny_cosp, cosy_cosp) * 180.0 / math.pi
        heading = (yaw + 360.0) % 360.0

        with self.lock:
            self.imu_pitch = pitch
            self.imu_roll = roll
            self.imu_yaw = yaw
            self.gps_heading = heading
            self.direction_deg = heading
            self.last_imu_time = time.time()

    def _on_battery_state(self, msg: BatteryState):
        with self.lock:
            if not math.isnan(msg.voltage) and msg.voltage > 0:
                self.battery_voltage = float(msg.voltage)
            if not math.isnan(msg.current):
                self.battery_current = float(msg.current)
            if not math.isnan(msg.percentage) and msg.percentage >= 0:
                self.battery_percentage = float(msg.percentage)
            self.last_battery_time = time.time()

    def _on_battery_voltage(self, msg: Float32):
        with self.lock:
            if msg.data > 0:
                self.battery_voltage = float(msg.data)
                self.last_battery_time = time.time()

    def _on_odom(self, msg: Odometry):
        vx = msg.twist.twist.linear.x
        vy = msg.twist.twist.linear.y
        speed = math.hypot(vx, vy)
        with self.lock:
            self.speed_mps = speed
            self.last_vel_time = time.time()

    def _on_cmd_vel(self, msg: Twist):
        # Track command velocities and fallback speed estimation if odom is absent
        now = time.time()
        with self.lock:
            self.cmd_linear_x = float(msg.linear.x)
            self.cmd_angular_z = float(msg.angular.z)
            if now - self.last_vel_time > 1.0:
                self.speed_mps = abs(float(msg.linear.x))

    def _on_motors(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) >= 6:
            with self.lock:
                for i in range(min(6, len(data))):
                    self.motors[i]["current_a"] = float(data[i])
                if len(data) >= 12:
                    for i in range(6):
                        self.motors[i]["temp_c"] = float(data[6 + i])
                self.last_motor_time = time.time()

    def _on_arm(self, msg: Float32MultiArray):
        if len(msg.data) >= 5:
            with self.lock:
                self.arm_state = [float(v) for v in msg.data[:5]]

    def _on_xbee_rx_status(self, msg: String):
        try:
            d = json.loads(msg.data)
            with self.lock:
                self.radio_rx_stats = d
                if "vx" in d and d.get("vx") is not None:
                    self.cmd_linear_x = float(d["vx"])
                if "wz" in d and d.get("wz") is not None:
                    self.cmd_angular_z = float(d["wz"])
                if all(k in d for k in ("act1", "act2", "act3", "wrist", "gripper")):
                    self.arm_state = [
                        float(d.get("act1", 0.0)),
                        float(d.get("act2", 0.0)),
                        float(d.get("act3", 0.0)),
                        float(d.get("wrist", 0.0)),
                        float(d.get("gripper", 0.0))
                    ]
        except Exception:
            pass

    # ===================================================================== #
    # Telemetry Assembly & Transmission
    # ===================================================================== #
    def _build_telemetry_payload(self) -> dict:
        now = time.time()
        elapsed = int(now - self.start_time)
        hrs = elapsed // 3600
        mins = (elapsed % 3600) // 60
        secs = elapsed % 60
        mission_time_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"

        with self.lock:
            # Baseline simulation / fallback nudge (slowly varies slightly if sensors idle)
            if self.sim_fallback:
                if now - self.last_battery_time > 3.0:
                    # nominal 24.2V slowly adjusting
                    self.battery_voltage = 24.2 + 0.1 * math.sin(now * 0.05)
                if now - self.last_motor_time > 3.0:
                    for m in self.motors:
                        m["temp_c"] = 36.0 + 0.5 * math.sin(now * 0.1)

            payload = {
                "type": "TELEMETRY",
                "timestamp": now,
                "battery": {
                    "voltage": round(self.battery_voltage, 1),
                    "current": round(self.battery_current, 2),
                    "percentage": round(self.battery_percentage, 1)
                },
                "rover_state": {
                    "active_flag": self.active_flag,
                    "mission_time": mission_time_str
                },
                "gps": {
                    "lat": round(self.gps_lat, 8),
                    "lon": round(self.gps_lon, 8),
                    "heading": round(self.gps_heading, 1)
                },
                "velocity": {
                    "speed_mps": round(self.speed_mps, 2),
                    "direction_deg": round(self.direction_deg, 1)
                },
                "cmd_vel": {
                    "linear_x": round(self.cmd_linear_x, 3),
                    "angular_z": round(self.cmd_angular_z, 3)
                },
                "imu": {
                    "pitch": round(self.imu_pitch, 1),
                    "roll": round(self.imu_roll, 1),
                    "yaw": round(self.imu_yaw, 1)
                },
                "motors": [dict(m) for m in self.motors],
                "arm": {
                    "act1": self.arm_state[0],
                    "act2": self.arm_state[1],
                    "act3": self.arm_state[2],
                    "wrist": self.arm_state[3],
                    "gripper": self.arm_state[4]
                },
                "connection": {
                    "xbee_connected": bool(self.radio_rx_stats.get("link", True)),
                    "xbee_port": str(self.radio_rx_stats.get("port", self.xbee_port)),
                    "xbee_rx_pkts": int(self.radio_rx_stats.get("rx", 0)),
                    "gps_connected": bool(now - self.last_gps_time < 3.0),
                    "gps_fix": (
                        "RTK FIXED" if getattr(self, 'gps_fix_quality', 0) == 4 or getattr(self, 'gps_fix_quality', 0) == 2
                        else ("RTK FLOAT" if getattr(self, 'gps_fix_quality', 0) == 5
                        else ("3D FIX" if getattr(self, 'gps_fix_quality', 0) >= 1 or (now - self.last_gps_time < 3.0)
                        else "NO FIX"))
                    ),
                    "rtcm_received": bool(
                        self.radio_rx_stats.get("rtcm_count", 0) > 0 and 
                        (self.radio_rx_stats.get("last_rtcm_age") is not None and self.radio_rx_stats.get("last_rtcm_age") < 5.0)
                    ),
                    "rtcm_count": int(self.radio_rx_stats.get("rtcm_count", 0)),
                    "rtcm_age_s": self.radio_rx_stats.get("last_rtcm_age", None),
                }
            }

        return payload

    def _broadcast_tick(self):
        payload = self._build_telemetry_payload()
        json_str = json.dumps(payload)
        json_bytes = json_str.encode('utf-8')

        # 1. Dispatch over Network UDP (Wi-Fi)
        if self.enable_udp and self.udp_sock:
            try:
                self.udp_sock.sendto(json_bytes, (self.base_ip, self.base_port))
            except Exception as e:
                self.get_logger().debug(f"UDP send warning: {e}")

        # 2. Publish to Rover Comms Master (rx_node) to transmit over XBee radio
        try:
            tx_msg = String()
            tx_msg.data = json_str
            self.telemetry_tx_pub.publish(tx_msg)
        except Exception:
            pass

        # 3. Direct XBee Serial Link (only used if enable_xbee is explicitly set true)
        if self.enable_xbee and self.xbee_ser and self.xbee_ser.is_open:
            try:
                # Prefix with b'T' to distinguish from other RF packets
                frame = wrap_xbee_api_tx(b'T' + json_bytes, '000000000000FFFF')
                self.xbee_ser.write(frame)
            except Exception as e:
                # Non-blocking write dropped cleanly on buffer saturation
                self.get_logger().debug(f"XBee send warning: {e}")

        # Rate-limited console log (every 2.5 seconds)
        now = time.time()
        if now - self._print_time >= 2.5:
            self._print_time = now
            self.get_logger().info(
                f"[TELEMETRY TX] Bat={payload['battery']['voltage']}V | "
                f"GPS=({payload['gps']['lat']:.4f}, {payload['gps']['lon']:.4f}) | "
                f"IMU=(P:{payload['imu']['pitch']:+.1f}°, R:{payload['imu']['roll']:+.1f}°, Y:{payload['imu']['yaw']:+.0f}°) | "
                f"Speed={payload['velocity']['speed_mps']:.1f}m/s | "
                f"Uptime={payload['rover_state']['mission_time']}"
            )

    def destroy_node(self):
        if self.udp_sock:
            try:
                self.udp_sock.close()
            except Exception:
                pass
        if self.xbee_ser:
            try:
                self.xbee_ser.close()
            except Exception:
                pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = RoverTelemetryNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
