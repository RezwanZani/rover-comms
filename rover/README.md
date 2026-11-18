# Rover Onboard Subsystem (ROS 2 Jazzy)

The Rover Onboard subsystem runs on the rover's single-board computer (e.g. Raspberry Pi 5, Jetson Orin Nano, or x86 SBC running Ubuntu 24.04 with ROS 2 Jazzy).

---

## Architecture Summary

```
                      ┌─── 900MHz XBee DigiMesh RF (/dev/rover_900mhz)
                      │    [Primary Authority]
                      ▼
            [ ROVER COMMS MASTER ] (xbee_teleop/rx_node)
            - Dual Receiver (Serial RF + UDP 8888)
            - XBee Priority & 0.35s Failover Engine
            - RFC 1982 Stale & Duplicate Rejection
            - RTCM Frame Deduplication
            - 0.5s Deadman Safety Watchdog
                      │
                      ├──► /cmd_vel  (geometry_msgs/Twist) ──► Motor Controllers
                      ├──► /arm_vel  (std_msgs/Float32MultiArray) ──► Arm Actuators
                      └──► /rtcm     (rtcm_msgs/Message) ──► Quectel LC29H RTK GPS
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
├── src/
│   ├── comms_config.py            ← Single Source of Truth for onboard parameters
│   ├── xbee_teleop_rover/         ← Rover Comms Master package
│   │   └── xbee_teleop/
│   │       ├── rx_node.py         ← Main node: Dual Receiver, Priority Engine, Watchdog
│   │       ├── link.py            ← Non-blocking XBee API Mode 1 framing & unpacking
│   │       ├── tx_node.py         ← (Optional) Transmitter for rover-to-rover teleop
│   │       └── gui.py             ← Local status window
│   ├── rover-gps/                 ← Quectel LC29H RTK GPS driver
│   │   └── src/gps_data/gps_data/
│   │       ├── gps_node.py        ← GPS NMEA parser & /rtcm correction injector
│   │       └── rtk_bridge_node.py ← (Optional) Dedicated RTCM serial bridge
│   └── rover_telemetry/           ← Telemetry aggregator package
│       └── rover_telemetry/
│           └── telemetry_node.py  ← Gathers sensors & broadcasts JSON via XBee + UDP
└── setup_udev.sh                  ← Udev rules script for stable serial symlinks
```

---

## Key Nodes & Responsibilities

### 1. `xbee_teleop/rx_node.py` (Rover Comms Master)
- **Sole Radio Owner**: Binds physical XBee serial port (`/dev/rover_900mhz`).
- **UDP Listener**: Background socket thread listening on `0.0.0.0:8888`.
- **Priority Failover**:
  - Treats XBee RF as primary.
  - If XBee is silent for $>0.35$s, switches seamlessly to UDP.
  - When XBee packets resume, XBee immediately takes back primary control.
- **Latency Protection**: RFC 1982 circular sequence math `(seq - last_seq) & 0xFF` rejects stale out-of-order packets ($\Delta \ge 128$) and duplicate packets ($\Delta == 0$).
- **Demultiplexing**:
  - Drives motors on `/cmd_vel` at 20 Hz.
  - Drives arm actuators on `/arm_vel` at 20 Hz.
  - Injects deduplicated RTCM3 frames to `/rtcm`.
- **Deadman Safety Watchdog**: If no packet arrives on either link for 0.5s, zeroes all drive and arm velocities.

### 2. `gps_data/gps_node.py` (Quectel LC29H RTK Driver)
- Connects to `/dev/rover_rtk` at 115200 baud.
- Subscribes to `/rtcm` and writes binary correction bytes into the LC29H serial stream.
- Reads NMEA sentences (`$GNGGA`, `$GNRMC`) and publishes `sensor_msgs/NavSatFix` on `/gps`.

### 3. `rover_telemetry/telemetry_node.py` (Telemetry Aggregator)
- Collects GPS position, RTK fix quality, battery voltage, IMU data, and telecom link status at 5 Hz.
- Packages data into structured JSON and broadcasts simultaneously over:
  - Wi-Fi UDP port `9003` to Base Station.
  - XBee radio downlink via topic `/telemetry_tx`.

---

## Hardware Udev Symlinks

To ensure USB ports never swap after reboot, run:
```bash
cd rover && sudo ./setup_udev.sh
```
This creates stable symlinks:
- `/dev/rover_900mhz` $\rightarrow$ FTDI USB UART (XBee radio)
- `/dev/rover_rtk` $\rightarrow$ Quectel LC29H RTK GPS module

---

## Build & Run

### 1. Build the ROS 2 Workspace
```bash
source /opt/ros/jazzy/setup.bash
cd /home/rezwan/Desktop/rover_com/rover
colcon build --symlink-install
```

### 2. Launching Onboard Nodes
Source the built workspace:
```bash
source install/setup.bash
```

#### Launch Comms Master:
```bash
ros2 run xbee_teleop rx_node
```

#### Launch RTK GPS Node:
```bash
ros2 run gps_data gps_node
```

#### Launch Telemetry Node:
```bash
ros2 run rover_telemetry telemetry_node
```
