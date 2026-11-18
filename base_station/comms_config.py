# =============================================================================
#   BASE STATION COMMUNICATIONS CONFIGURATION
#   Single source of truth for all base station hardware, network, and
#   protocol parameters.
#
#   HOW TO USE:
#     from comms_config import ...
#   at the top of any base station script.
#
#   HOW TO RECONFIGURE:
#     Edit THIS file only. All scripts pick up changes automatically.
#     For multi-PC setups, change MASTER_IP from '127.0.0.1' to the
#     LAN IP of the Master PC (e.g. '192.168.1.50').
# =============================================================================

# -----------------------------------------------------------------------------
# HARDWARE SERIAL PORTS
# Windows: 'COM3', 'COM17', etc.   Linux: '/dev/ttyUSB0', etc.
# -----------------------------------------------------------------------------

# XBee radio connected to this PC for Joystick → Rover teleop commands
TELEOP_XBEE_PORT    = 'COM3'

# XBee radio connected to this PC for forwarding RTCM corrections to Rover
GPS_XBEE_PORT       = 'COM18'

# Quectel LC29H(BS) Base Station GPS module (survey-in source)
BASE_GPS_PORT       = 'COM17'

# XBee port used by the rover-gui backend (may be same as TELEOP_XBEE_PORT
# if only one radio is connected, or a separate dedicated port)
GUI_XBEE_PORT       = 'COM20'

# -----------------------------------------------------------------------------
# BAUD RATES
# -----------------------------------------------------------------------------

# XBee API mode baud rate — must match radio firmware BD parameter (BD=7 → 115200)
XBEE_BAUD_RATE      = 115200

# Supported standard baud rates for selection in GUIs
AVAILABLE_BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

# Base GPS serial baud rate
GPS_BAUD_RATE       = 115200

def scan_available_ports():
    """
    Scans physical, virtual, and symlinked serial ports across Linux and Windows.
    Guarantees virtual pairs (/tmp/ttyV0, /tmp/ttyV1, /tmp/tty*), USB adapters,
    and configured ports appear at the top of the list.
    """
    import glob, os, sys
    ports = []

    def _add(p):
        if p and p not in ports:
            ports.append(p)

    # 1. Virtual ports in /tmp (socat virtual pairs, pty links)
    for pattern in ['/tmp/ttyV*', '/tmp/ttyXBee*', '/tmp/tty*']:
        for vport in sorted(glob.glob(pattern)):
            if os.path.exists(vport):
                _add(vport)

    # Explicit virtual pair fallback
    for vport in ['/tmp/ttyV0', '/tmp/ttyV1']:
        if os.path.exists(vport):
            _add(vport)

    # 2. Linux USB & ACM serial devices + udev symlinks
    if sys.platform != 'win32':
        for pattern in ['/dev/ttyUSB*', '/dev/ttyACM*', '/dev/rover_*', '/dev/serial/by-id/*', '/dev/serial/by-path/*']:
            for dev in sorted(glob.glob(pattern)):
                if os.path.exists(dev):
                    _add(dev)

    # 3. Pyserial standard detection (hardware COM ports & USB-to-UART)
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            dev = p.device
            # Filter out Linux /dev/ttyS0..31 inactive phantom ports
            if sys.platform != 'win32' and dev.startswith('/dev/ttyS'):
                continue
            _add(dev)
    except Exception:
        pass

    # 4. Windows registry extra scan
    if sys.platform == 'win32':
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM")
            for i in range(256):
                try:
                    val = winreg.EnumValue(key, i)
                    _add(str(val[1]))
                except OSError:
                    break
            winreg.CloseKey(key)
        except Exception:
            pass

    return ports

# -----------------------------------------------------------------------------
# XBEE RADIO 64-BIT ADDRESSES
# -----------------------------------------------------------------------------

# 64-bit address of the Rover XBee radio (target for all teleop/RTCM TX)
ROVER_RADIO_ADDR    = '0013A200425E94FF'

# XBee API broadcast address (sent when no specific destination is set)
XBEE_BROADCAST_ADDR = b'\x00\x00\x00\x00\x00\x00\xff\xff'

# Base station transmitter radio address (for reference / ACK source filtering)
BASE_RADIO_ADDR_TX  = '0013A200425DD789'    # TX radio (gamepad / teleop PC)
BASE_RADIO_ADDR_RX  = '0013A200425DD6F0'    # RX radio reference (rover side)

# XBee DigiMesh PAN ID — must be identical on ALL radios in the network
# Decimal 3196 = hex 0x0C7C
XBEE_PAN_ID         = 3196

# -----------------------------------------------------------------------------
# RTK GPS SURVEY-IN SETTINGS  (base_station_windows.py)
# -----------------------------------------------------------------------------

# Minimum stationary observation time before survey-in is accepted (seconds)
SURVEY_TIME_SEC     = 300

# Survey-in position accuracy threshold (meters) — lower = tighter lock required
SURVEY_ACCURACY_M   = 2.0

# -----------------------------------------------------------------------------
# TELEOP CONTROLLER SETTINGS  (xbee_teleop_windows.py)
# -----------------------------------------------------------------------------

JOY_INDEX           = 0        # Gamepad slot index (0 = first connected controller)
JOY_DEADZONE        = 0.05     # Analog stick deadzone (fraction of full travel, 0–1)
SEND_RATE_HZ        = 20.0     # Teleop packet transmit rate (Hz)
CMD_TIMEOUT         = 0.5      # Seconds of silence before zeroing all commands

ENABLE_BUTTON       = 4        # Deadman button index — LB on Xbox pad
REQUIRE_ENABLE      = False    # False = stick alone drives; True = must hold LB

SCALE_LINEAR        = 0.5      # Left-stick Y → vx multiplier (m/s per unit)
SCALE_ANGULAR       = 1.0      # Right-stick X → wz multiplier (rad/s per unit)
DRIVE_MODE          = 'arcade' # 'arcade' (default) or 'tank'

AXIS_LINEAR         = 1        # Arcade: left stick Y → vx
AXIS_ANGULAR        = 2        # Arcade: right stick X → wz
AXIS_LEFT           = 1        # Tank: left stick Y
AXIS_RIGHT          = 3        # Tank: right stick Y

BTN_ACT1            = 0        # A button → Actuator 1 (linear actuator)
BTN_ACT2            = 1        # B button → Actuator 2 (linear actuator)
BTN_ACT3            = 2        # X button → Actuator 3 (linear actuator)
BTN_WRIST           = 3        # Y button → Wrist stepper motor

AXIS_LT             = 4        # Left Trigger axis index (arm contract direction)
AXIS_RT             = 5        # Right Trigger axis index (arm expand direction)
TRIGGER_THRESHOLD   = 0.3      # Trigger press fraction required to register arm action
AXIS_DPAD_Y         = 7        # Synthetic D-Pad Y axis index (gripper control)

# -----------------------------------------------------------------------------
# ROVER-GUI BACKEND  (rover-gui/backend/main.py + struct_packer.py)
# -----------------------------------------------------------------------------

GUI_LOOP_HZ         = 20       # Hardware/serial loop rate (Hz)
GUI_DEADZONE        = 0.20     # Joystick deadzone for GUI backend (fraction 0–1)

WS_HOST             = 'localhost'   # WebSocket server bind host
WS_PORT             = 8765          # WebSocket server port for the React frontend

# -----------------------------------------------------------------------------
# PACKET FORMAT CONSTANTS
# -----------------------------------------------------------------------------

# New unified 16-byte MOTION packet: 'M' seq vx wz act1 act2 act3 wrist gripper
# All i16 values are real_value * 1000 (fixed-point, little-endian)
MOTION_PACKET_FORMAT = '<cBhhhhhhh'   # struct layout
MOTION_PACKET_ID     = b'M'           # packet type byte
MOTION_PACKET_SIZE   = 16             # bytes

# Legacy 6-byte CMD packet (drive-only, backward compat): 'C' seq vx wz
LEGACY_CMD_FORMAT    = '<cBhh'
LEGACY_CMD_ID        = b'C'
LEGACY_CMD_SIZE      = 6

# 5-byte ACK packet (rover → base station): 'A' last_seq lost
ACK_PACKET_FORMAT    = '<cBH'
ACK_PACKET_ID        = b'A'
ACK_PACKET_SIZE      = 5

# rover-gui legacy 10-byte struct: sync(char) linear_x(float) angular_z(float) cmd_flag(int8)
# NOTE: This format is specific to rover-gui/backend and differs from the
#       16-byte MOTION packet used by all other teleop scripts. Both are kept
#       here for reference. Unifying them is a separate future task.
GUI_PAYLOAD_FORMAT   = '<cffb'
GUI_SYNC_CHAR        = b'$'
GUI_PAYLOAD_SIZE     = 10

# -----------------------------------------------------------------------------
# UDP HUB PORTS  (Base Master Script hub-and-spoke architecture)
#
# These ports define the local/LAN UDP communication between independent
# base station scripts and the central Base Master Script.
#
# Same-PC (loopback): latency ~0.02 ms
# Multi-PC (LAN):     latency ~0.2–0.5 ms — change MASTER_IP to the Master PC's IP
# -----------------------------------------------------------------------------

# IP address of the Base Master Script
# '127.0.0.1'   = same computer (loopback, fastest)
# '192.168.1.x' = another PC on the same LAN switch
MASTER_IP           = '127.0.0.1'

# Master script binds to this address to accept both localhost and LAN senders
UDP_LISTEN_IP       = '0.0.0.0'

# Joystick script → Master: sends 16-byte 'M' motion packets at SEND_RATE_HZ
UDP_JOY_PORT        = 9001

# GPS/RTCM script → Master: sends raw 0xD3 RTCM3 frames as they are sliced
UDP_RTCM_PORT       = 9002

# Master → GUI/status script: forwards JSON status (ACKs, ROVER_PING, link stats, rover telemetry)
UDP_STATUS_PORT     = 9003
TELEMETRY_UDP_PORT  = 9003          # Rover Telemetry UDP port received by Base Station

# Maximum chunk size for RTCM frames over XBee (prevents Head-of-Line teleop latency spikes)
RTCM_CHUNK_MAX      = 256

# Internal ROS topics (for reference and rover coordination)
RTCM_TOPIC          = '/rtcm'
TELEMETRY_TX_TOPIC  = 'telemetry_tx'

# -----------------------------------------------------------------------------
# DUAL REDUNDANT UPLINK (Base Master -> Rover Wi-Fi UDP + XBee RF)
# -----------------------------------------------------------------------------
# Target IP of the Rover for Wi-Fi UDP uplink (127.0.0.1 for bench; LAN IP on robot)
ROVER_IP                = '127.0.0.1'

# Port rover listens on for dual-redundant Wi-Fi UDP uplink
ROVER_UDP_LISTEN_PORT   = 8888

# Master switch for dual-redundant broadcast from base station
DUAL_REDUNDANCY_ENABLED = True

# Rover failover timeout: seconds of XBee silence before switching to UDP
XBEE_FAILOVER_TIMEOUT   = 0.35


