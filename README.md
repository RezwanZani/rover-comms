# Rover Communications & Control System

A failure-proof, dual-redundant telecommunications and control architecture for an autonomous/teleoperated planetary rover and operator base station.

---

## Architecture at a Glance

- **Centralized Master Hubs**: Exactly one process owns the physical XBee serial radio on each side ([`base_master.py`](file:///home/rezwan/Desktop/rover_com/base_station/base_master.py) at Base Station, [`rx_node.py`](file:///home/rezwan/Desktop/rover_com/rover/src/xbee_teleop_rover/xbee_teleop/rx_node.py) on Rover).
- **Dual-Redundant Transmission**: Gamepad commands and RTCM3 differential GPS corrections are transmitted simultaneously across **both 900MHz XBee DigiMesh RF and Wi-Fi UDP**.
- **Priority Failover**: The Rover prioritizes long-range XBee RF as primary. If XBee drops out for $>0.35$s, it seamlessly fails over to Wi-Fi UDP without zeroing motor velocities. When XBee recovers, it instantly preempts UDP.
- **Latency & Stale Packet Protection**: Employs **RFC 1982 circular sequence number arithmetic** to discard delayed or out-of-order packets arriving across high-latency links.
- **Deduplication Engine**: Discards redundant command packets and duplicate RTCM3 GPS correction frames before reaching motor drivers or GPS serial lines.
- **Operator Web Dashboard**: Real-time React 18 + TailwindCSS + WebSocket dashboard displaying active link mode (`DUAL_ACTIVE`, `XBEE`, `UDP`), LC29H RTK fix quality, and connection metrics.

For complete architectural specifications, timing diagrams, state machines, and mathematical formulations, read **[`ARCHITECTURE.md`](file:///home/rezwan/Desktop/rover_com/ARCHITECTURE.md)**.

---

## Repository Layout

```
rover_com/
├── ARCHITECTURE.md            ← Complete architectural specification & protocol manual
├── README.md                  ← This document
├── comms_refactor_plan.md     ← Architectural audit & risk mitigation plan
├── create_virtual_pair.sh     ← Bench testing script for virtual serial ports (/tmp/ttyV0 <-> /tmp/ttyV1)
├── run_base_station.sh        ← Root shortcut to launch all Base Station services
│
├── base_station/              ← Operator Base Station Subsystem (README: base_station/README.md)
│   ├── comms_config.py        ← Single Source of Truth for Base Station configuration
│   ├── base_master.py         ← Central Base Master Hub & Dual-Redundant Uplink Router
│   ├── launch_base_station.py ← Multi-process supervisor launcher
│   ├── xbee_teleop_windows.py ← Gamepad Teleoperation GUI
│   ├── base_station_windows.py← LC29H(BS) RTK GPS Survey-In script
│   └── rover-gui/             ← React 18 + FastAPI Diagnostics Web Dashboard
│
└── rover/                     ← Onboard Rover Subsystem (README: rover/README.md)
    ├── setup_udev.sh          ← Udev rules script for stable /dev/rover_* symlinks
    └── src/
        ├── comms_config.py    ← Single Source of Truth for Rover onboard configuration
        ├── xbee_teleop_rover/ ← Rover Comms Master (rx_node.py, failover & latency engine)
        ├── rover-gps/         ← Quectel LC29H RTK GPS driver (gps_node.py, RTCM injection)
        └── rover_telemetry/   ← Telemetry aggregator & multi-channel broadcaster
```

---

## Quick Start Guide

### 1. Base Station Startup
To launch the complete Base Station environment (Master Hub, Telemetry Backend, React Dashboard, and Teleop GUI):

```bash
# On Linux:
./run_base_station.sh

# On Windows:
base_station\run_base_station.bat
```

Access the Web Dashboard at: `http://localhost:5173`

### 2. Rover Onboard Startup
Build and run on the rover single-board computer:

```bash
# 1. Build ROS 2 workspace
source /opt/ros/jazzy/setup.bash
cd rover && colcon build --symlink-install

# 2. Source workspace
source install/setup.bash

# 3. Launch Rover Comms Master (Dual Receiver & Priority Engine)
ros2 run xbee_teleop rx_node

# 4. Launch RTK GPS Driver (NMEA Parser & RTCM Injector)
ros2 run gps_data gps_node

# 5. Launch Telemetry Broadcaster
ros2 run rover_telemetry telemetry_node
```

---

## Configuration (Single Source of Truth)

All network ports, serial baud rates, radio addresses, and failover timeouts are centralized in two mirror files:
- Base Station: [`base_station/comms_config.py`](file:///home/rezwan/Desktop/rover_com/base_station/comms_config.py)
- Rover Onboard: [`rover/src/comms_config.py`](file:///home/rezwan/Desktop/rover_com/rover/src/comms_config.py)

To adjust Rover IP for field operations over Wi-Fi, change `ROVER_IP` in `base_station/comms_config.py`:
```python
ROVER_IP = '192.168.1.100'   # Rover onboard Wi-Fi IP address
```

---

## Automated Verification Suite

Run automated bench tests verifying dual redundancy, failover, and latency handling using virtual serial loopbacks:

```bash
source /opt/ros/jazzy/setup.bash
source rover/install/setup.bash

# Run Dual Redundancy, Priority Failover & Latency Protection Test
python3 scratch/test_dual_redundancy_and_latency.py

# Run Centralized Master Hub & Watchdog Test
python3 scratch/test_centralized_comms.py
```
