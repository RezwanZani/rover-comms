# Rover Onboard Subsystem (ROS 2 Jazzy)

The Rover Onboard subsystem runs on the rover's single-board computer (e.g. NVIDIA Jetson Orin NX/Nano, Raspberry Pi 5, or x86 SBC running Ubuntu with ROS 2 Jazzy or Humble).

---

## Architecture Summary

```
                      ┌─── 900MHz XBee DigiMesh RF (/dev/rover_900mhz)
                      │    [Primary Authority]
                      ▼
            [ ROVER COMMS MASTER ] (xbee_teleop/rx_node)
            - Dual Receiver (Serial RF + Wi-Fi UDP 8888)
            - XBee Priority & 0.35s Failover Engine
            - RFC 1982 Stale & Duplicate Rejection
            - RTCM Frame Deduplication
            - 0.5s Deadman Safety Watchdog
                      │
                      ├──► /cmd_vel  (geometry_msgs/Twist) ────────► Motor Kinematics Driver
                      ├──► /arm_vel  (std_msgs/Float32MultiArray) ─► Robotic Arm Actuators
                      ├──► /rover/mode (std_msgs/String) ──────────► Autonomy / Nav2 Stack
                      ├──► /science/actuator_cmd (UInt8MultiArray) ─► [ science_node ]
                      │                                                     │ Serial S:.. / STATUS:..
                      │                                                     ▼
                      │                                             [ Arduino Mega 2560 ]
                      │                                             (5 Pumps, LED, Servo)
                      └──► /rtcm (rtcm_msgs/Message) ──────────────► [ rover_gps_node ]
                                                                            │
                                                                            ▼ /gps (NavSatFix)
                                                                  [ telemetry_node ]
                                                                            │
                                                 ┌──────────────────────────┴──────────────────────────┐
                                                 ▼                                                     ▼
                                     /telemetry_tx ──► XBee Downlink                        Wi-Fi UDP :9003 Downlink
```

---

## Directory Layout

```
rover/
├── run_rover_all.py               ← Single-command Python launcher for all onboard nodes
└── src/
    ├── comms_config.py            ← Single Source of Truth for onboard parameters
    │
    ├── xbee_teleop_rover/         ← Rover Comms Master package (xbee_teleop)
    │   ├── launch/
    │   │   ├── rover_all.launch.py← MASTER LAUNCHER (Runs all onboard nodes)
    │   │   └── rx.launch.py       ← Dedicated receiver launcher
    │   └── xbee_teleop/
    │       ├── rx_node.py         ← Comms Master: Dual Receiver, Priority & Failover
    │       ├── science_node.py    ← Arduino Mega 2560 Serial Bridge
    │       └── link.py            ← Binary packet codecs ('M', 'N', 'S', 'A')
    │
    ├── rover-gps/                 ← Quectel LC29H RTK GPS driver (gps_data)
    │   └── src/gps_data/
    │       ├── launch/gps.launch.py
    │       └── gps_data/gps_node.py ← GPS NMEA parser & RTCM injection
    │
    └── rover_telemetry/           ← Telemetry broadcaster (rover_telemetry)
        ├── launch/telemetry.launch.py
        └── rover_telemetry/
            └── telemetry_node.py  ← Aggregates sensors & broadcasts over XBee + UDP
```

---

## Key Onboard Nodes

### 1. `xbee_teleop/rx_node` (Comms Master)
- **Sole Radio Owner**: Binds physical XBee serial port (`/dev/rover_900mhz` or `/dev/ttyUSB0`) at `115200 baud`.
- **UDP Listener**: Background socket thread listening on `0.0.0.0:8888`.
- **Priority Failover**:
  - Treats XBee RF as primary.
  - If XBee is silent for $>0.35$s, switches seamlessly to Wi-Fi UDP.
  - When XBee packets resume, XBee immediately takes back primary control.
- **Latency Protection**: RFC 1982 circular sequence math `(seq - last_seq) & 0xFF` rejects stale out-of-order packets ($\Delta \ge 128$) and duplicate packets ($\Delta == 0$).
- **Demultiplexing**:
  - Publishes drive velocities to `/cmd_vel` (`geometry_msgs/Twist`) at 20 Hz.
  - Publishes arm velocities to `/arm_vel` (`std_msgs/Float32MultiArray`) at 20 Hz.
  - Publishes operating mode to `/rover/mode` (`std_msgs/String`).
  - Publishes science commands to `/science/actuator_cmd` (`std_msgs/UInt8MultiArray`).
  - Injects deduplicated RTCM3 frames to `/rtcm`.
- **Deadman Safety Watchdog**: If no packet arrives on either link for 0.5s, zeroes all drive and arm velocities.

### 2. `xbee_teleop/science_node` (Arduino Mega Bridge)
- Connects to Arduino Mega 2560 via USB serial (`/dev/ttyACM0` or `/dev/arduino_science`) at `9600 baud`.
- Subscribes to `/science/actuator_cmd` (`UInt8MultiArray`).
- Sends formatted serial commands: `S:m1,m2,m3,m4,m5,led,servo\n`.
- Parses feedback lines: `STATUS:m1=1,m2=0,m3=1,m4=0,m5=0,led=1,servo=90\n` and publishes JSON to `/science/actuator_status` (`std_msgs/String`).

### 3. `rover_telemetry/telemetry_node` (Telemetry Aggregator)
- Collects GPS position, RTK fix quality, battery voltage, IMU data, motor states, science actuator states, and operational mode at 5 Hz.
- Packages data into structured JSON and broadcasts simultaneously over:
  - Wi-Fi UDP port `9003` to Base Station.
  - XBee radio downlink via topic `/telemetry_tx` (routed through `rx_node`).

### 4. `gps_data/gps_node` (Quectel LC29H RTK Driver)
- Connects to `/dev/rover_rtk` at 115200 baud.
- Subscribes to `/rtcm` and writes binary correction bytes into the LC29H serial stream.
- Reads NMEA sentences (`$GNGGA`, `$GNRMC`) and publishes `sensor_msgs/NavSatFix` on `/gps`.

---

## Hardware Udev Symlinks

To ensure USB ports never swap upon reboot or replug, install the provided udev rules:
```bash
sudo python3 rover/src/rover-gps/setup_udev.py
```
This generates persistent symlinks:
- `/dev/rover_900mhz` $\rightarrow$ FTDI USB UART (XBee radio)
- `/dev/rover_rtk` $\rightarrow$ Quectel LC29H RTK GPS module
- `/dev/ttyACM0` $\rightarrow$ Arduino Mega 2560

---

## Build & Run

### 1. Build the ROS 2 Workspace
```bash
source /opt/ros/jazzy/setup.bash
cd /home/rezwan/Desktop/rover_com/rover
colcon build --symlink-install
source install/setup.bash
```

### 2. Launch All Nodes Simultaneously (Single Command)
From project root (or inside `rover/`):
```bash
python3 run_rover_all.py
```

Or using native ROS 2 launch:
```bash
ros2 launch xbee_teleop rover_all.launch.py
```

#### Supported Arguments:
```bash
# Override ports and Base Station IP:
python3 run_rover_all.py xbee_port:=/dev/ttyUSB0 arduino_port:=/dev/ttyACM0 base_ip:=192.168.1.50

# Disable GPS if running indoors on a test bench:
python3 run_rover_all.py enable_gps:=false
```
