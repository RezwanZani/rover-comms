# =============================================================================
#   ROVER COMMUNICATIONS CONFIGURATION
#   Single source of truth for all onboard rover hardware, ROS 2, and
#   network parameters.
#
#   HOW TO USE:
#     from comms_config import ...
#   at the top of any rover Python script.
#
#   HOW TO RECONFIGURE:
#     Edit THIS file only.
#     ROS 2 YAML files (params.yaml, gps.launch.py) cannot import Python
#     directly — keep their values manually in sync with this file.
#     Each YAML value is annotated with the matching variable name here.
# =============================================================================

# -----------------------------------------------------------------------------
# HARDWARE SERIAL PORTS  (Linux udev static symlinks)
# The udev rules bind each module's USB chip serial number to a fixed symlink,
# so ports never swap on reboot or reconnect.
# -----------------------------------------------------------------------------

# XBee radio for Teleop (receives 'M' motion packets from Base Station)
# Full by-id path is the most stable; udev symlink is the convenient alias.
TELEOP_XBEE_PORT        = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_B0025NTL-if00-port0'
TELEOP_XBEE_PORT_ALT    = '/dev/rover_900mhz'   # udev symlink (same physical device)
TELEOP_XBEE_PORT_DEFAULT = '/dev/ttyUSB0'        # Last-resort fallback if udev not set up

# XBee radio for RTK RTCM corrections (receives RTCM3 stream from Base Station)
# On single-radio builds this may be the SAME port as TELEOP_XBEE_PORT.
# On dual-radio builds, set this to the second XBee's port.
RTK_XBEE_PORT           = '/dev/rover_900mhz'

# Quectel LC29H RTK GPS module (receives NMEA + RTCM injection)
GPS_PORT                = '/dev/rover_rtk'

# -----------------------------------------------------------------------------
# BAUD RATES
# -----------------------------------------------------------------------------

# XBee API mode baud rate — must match radio firmware BD parameter (BD=7 → 115200)
XBEE_BAUD_RATE          = 115200

# Supported standard baud rates for selection in GUIs
AVAILABLE_BAUD_RATES    = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

# LC29H GPS serial baud rate
GPS_BAUD_RATE           = 115200

def scan_available_ports():
    """
    Scans physical hardware serial ports and USB adapters across Linux and Windows.
    Discovers hardware USB-to-UART converters, udev symlinks, and active COM ports.
    """
    import glob, os, sys
    ports = []

    def _add(p):
        if p and p not in ports:
            ports.append(p)

    # 1. Linux USB & ACM serial devices + udev symlinks
    if sys.platform != 'win32':
        for pattern in ['/dev/ttyUSB*', '/dev/ttyACM*', '/dev/rover_*', '/dev/serial/by-id/*', '/dev/serial/by-path/*']:
            for dev in sorted(glob.glob(pattern)):
                if os.path.exists(dev):
                    _add(dev)

    # 2. Pyserial standard detection (hardware COM ports & USB-to-UART)
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

    # 3. Windows registry extra scan
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

# 64-bit address of the Base Station transmitter radio (the gamepad PC's XBee)
# Used by rx_node as remote_addr filter; ACKs are sent back to this address.
BASE_RADIO_ADDR         = '0013A200425DD6F0'

# Rover XBee radio addresses (for reference and ACK filtering)
ROVER_RADIO_ADDR_RX     = '0013A200425E9501'    # Rover XBee receiver (teleop)
ROVER_RADIO_ADDR_TX     = '0013A200425E94FF'    # Rover XBee (also used by base GPS)

# XBee DigiMesh PAN ID — must be identical on ALL radios in the network
# Decimal 3196 = hex 0x0C7C
XBEE_PAN_ID             = 3196

# -----------------------------------------------------------------------------
# UDEV DEVICE SERIAL NUMBERS  (for setup_udev.sh reference)
# These chip serial numbers are what the udev rules use to create stable symlinks.
# If hardware is replaced, update these AND re-run setup_udev.sh.
# -----------------------------------------------------------------------------

UDEV_XBEE_SERIAL        = 'B0025NTL'
UDEV_GPS_SERIAL         = 'ac57edb6726cef119a94a3adc169b110'

# -----------------------------------------------------------------------------
# TELEOP SETTINGS  (rx_node.py, tx_node.py, params.yaml)
# Changes here must also be manually mirrored in params.yaml.
# -----------------------------------------------------------------------------

SEND_RATE_HZ            = 20.0     # TX node publish rate (Hz)
CMD_TIMEOUT             = 0.5      # Seconds without a packet → publish zeros

AXIS_LINEAR             = 1        # Joy axis → linear X (vx)
AXIS_ANGULAR            = 0        # Joy axis → angular Z (wz)
ENABLE_BUTTON           = 4        # Deadman button index (LB)
REQUIRE_ENABLE          = False    # True = must hold LB; False = stick alone drives
SCALE_LINEAR            = 0.5      # vx scale factor (m/s per unit)
SCALE_ANGULAR           = 1.0      # wz scale factor (rad/s per unit)

JOY_DEADZONE            = 0.05     # joy_node analog stick deadzone (fraction 0–1)
JOY_AUTOREPEAT_RATE     = 20.0     # joy_node autorepeat rate (Hz)

# -----------------------------------------------------------------------------
# ROS 2 TOPIC NAMES  (rx_node.py, tx_node.py, gui.py)
# -----------------------------------------------------------------------------

CMD_VEL_TOPIC           = 'cmd_vel'          # Drive command (geometry_msgs/Twist)
ARM_VEL_TOPIC           = 'arm_vel'          # Arm command  (std_msgs/Float32MultiArray)
#                                            # data = [act1, act2, act3, wrist, gripper]
#                                            # values: -1.0 contract | 0.0 still | +1.0 expand
STATUS_TOPIC_RX         = 'xbee_rx/status'   # Diagnostic JSON string — rx_node
STATUS_TOPIC_TX         = 'xbee_tx/status'   # Diagnostic JSON string — tx_node

# -----------------------------------------------------------------------------
# GPS / RTK SETTINGS  (rtk_bridge_node.py, gps_node.py, gps.launch.py)
# Changes here must also be manually mirrored in gps.launch.py default_values.
# -----------------------------------------------------------------------------

GPS_FRAME_ID            = 'gps_link'  # TF frame_id for sensor_msgs/NavSatFix messages
GPS_TOPIC               = '/gps'       # Published NavSatFix topic
USE_RTK_BRIDGE          = False        # False = gps_node (ROS /rtcm); True = legacy rtk_bridge_node
ENABLE_DRIFT_PLOT       = False        # True = also launch map_acc drift visualizer

# -----------------------------------------------------------------------------
# PACKET FORMAT CONSTANTS
# (Must mirror base_station/comms_config.py — keep both files in sync)
# -----------------------------------------------------------------------------

# New unified 16-byte MOTION packet: 'M' seq vx wz act1 act2 act3 wrist gripper
# All i16 values are real_value * 1000 (fixed-point, little-endian)
MOTION_PACKET_FORMAT    = '<cBhhhhhhh'   # struct layout
MOTION_PACKET_ID        = b'M'           # packet type byte
MOTION_PACKET_SIZE      = 16             # bytes

# Legacy 6-byte CMD packet (drive-only, backward compat): 'C' seq vx wz
LEGACY_CMD_FORMAT       = '<cBhh'
LEGACY_CMD_ID           = b'C'
LEGACY_CMD_SIZE         = 6

# 5-byte ACK packet (rover → base station): 'A' last_seq lost
ACK_PACKET_FORMAT       = '<cBH'
ACK_PACKET_ID           = b'A'
ACK_PACKET_SIZE         = 5

# -----------------------------------------------------------------------------
# UDP CONFIGURATION  (future Wi-Fi UDP receiver node)
#
# Reserved for the upcoming Base Master → Rover Wi-Fi UDP link.
# The port and IP can be changed here or overridden at runtime via a parameter
# or the GUI without touching any node logic.
# -----------------------------------------------------------------------------

# IP address this rover UDP listener will bind to
# '0.0.0.0' = accept from any interface (Wi-Fi, Ethernet, loopback)
ROVER_UDP_LISTEN_IP     = '0.0.0.0'

# UDP port the rover listens on for commands from the Base Master Script
# Change this here, via a ROS 2 parameter, or via the GUI control panel.
ROVER_UDP_LISTEN_PORT   = 8888

# Master switch for dual-redundancy broadcast from base station
DUAL_REDUNDANCY_ENABLED = True

# Rover failover timeout: seconds of XBee radio silence before switching to UDP
XBEE_FAILOVER_TIMEOUT   = 0.35


# Destination IP & UDP port for transmitting Rover Telemetry back to Base Station
# For single-PC / simulation test, use '127.0.0.1'. For multi-PC Wi-Fi, set to Base Station IP.
BASE_STATION_IP               = '127.0.0.1'
BASE_STATION_TELEMETRY_PORT   = 9003          # Matches UDP_STATUS_PORT on Base Station
TELEMETRY_RATE_HZ             = 5.0           # Telemetry broadcast rate (Hz)

# Internal ROS topics for Rover Comms Master routing
RTCM_TOPIC                    = '/rtcm'
TELEMETRY_TX_TOPIC            = 'telemetry_tx'
RTCM_CHUNK_MAX                = 256           # Max fragment size for RTCM frames over radio

# -----------------------------------------------------------------------------
# SCIENCE / ARDUINO SERIAL BRIDGE
# -----------------------------------------------------------------------------
SCIENCE_ARDUINO_PORT          = '/dev/ttyACM0'
SCIENCE_ARDUINO_BAUD          = 9600
SCIENCE_CMD_TOPIC             = '/science/actuator_cmd'
SCIENCE_STATUS_TOPIC          = '/science/actuator_status'
ROVER_MODE_TOPIC              = '/rover/mode'

# -----------------------------------------------------------------------------
# SCIENCE PACKET 'S' (Base -> Rover, dual redundant)
# Format: '<cBBBBBBBB' = 9 bytes
# -----------------------------------------------------------------------------
SCIENCE_PACKET_FORMAT         = '<cBBBBBBBB'
SCIENCE_PACKET_ID             = b'S'
SCIENCE_PACKET_SIZE           = 9

# -----------------------------------------------------------------------------
# MODE PACKET 'N' (Base -> Rover, dual redundant)
# Format: '<cBB' = 3 bytes
# -----------------------------------------------------------------------------
MODE_PACKET_FORMAT            = '<cBB'
MODE_PACKET_ID                = b'N'
MODE_PACKET_SIZE              = 3
MODE_TELEOP                   = 0x00
MODE_AUTONOMOUS               = 0x01


