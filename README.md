# AAUB ROVER71 — Telecommunications & Robotics Control System

A failure-proof, dual-redundant telecommunications and control architecture for an autonomous and teleoperated planetary rover and ground control station (GCS).

---

## Table of Contents
1. [Architecture Overview](#architecture-overview)
2. [Dual Redundancy & Failover Strategy](#dual-redundancy--failover-strategy)
3. [Network & Radio Configuration (XBee & UDP)](#network--radio-configuration-xbee--udp)
4. [Hardware & Software Prerequisites](#hardware--software-prerequisites)
5. [Build & Installation Guide](#build--installation-guide)
6. [Running the System (Single-Command Launch)](#running-the-system-single-command-launch)
7. [Subsystems & Operational Modes](#subsystems--operational-modes)
   - [Autonomous vs. Teleop Mode Toggle](#autonomous-vs-teleop-mode-toggle)
   - [Science Mission Subsystem (Pumps, LED, Servo)](#science-mission-subsystem-pumps-led-servo)
   - [RTK GPS Subsystem (Quectel LC29H)](#rtk-gps-subsystem-quectel-lc29h)
8. [Automated Verification & Bench Testing](#automated-verification--bench-testing)
9. [Troubleshooting & FAQ](#troubleshooting--faq)

---

## Architecture Overview

```mermaid
flowchart TD
    subgraph BASE["BASE STATION (Operator Laptop / PC)"]
        direction TB
        JOY["Joystick Teleop GUI\n(xbee_teleop_windows.py)"]
        WEB["React Mission Control\n(Dashboard & /science)"]
        BACKEND["FastAPI WebSocket Server\n(backend/main.py :8765)"]
        GPS_BASE["Base RTK GPS Survey-In\n(base_station_windows.py)"]
        MASTER["BASE MASTER HUB\n(base_master.py)\n*Sole Base Radio Owner*"]

        JOY -->|UDP 9001: 'M' Motion| MASTER
        WEB <-->|WebSocket JSON| BACKEND
        BACKEND -->|UDP 9001: 'N' Mode & 'S' Science| MASTER
        GPS_BASE -->|UDP 9002: RTCM3 Frames| MASTER
        MASTER -->|UDP 9003: Telemetry & ACKs| BACKEND
    end

    subgraph CHANNELS["DUAL-REDUNDANT LINKS"]
        direction LR
        RF["PRIMARY AUTHORITY\n900MHz DigiMesh RF (API Mode 1)\nLong Range · High Penetration"]
        WIFI["SECONDARY / BACKUP\nWi-Fi UDP :8888\nLow Latency · High Bandwidth"]
    end

    MASTER ==>|API 0x10 Frames @ 115200| RF
    MASTER -.->|Simultaneous UDP Datagrams| WIFI

    subgraph ROVER["ONBOARD ROVER (NVIDIA Jetson / Linux SBC - ROS 2 Jazzy)"]
        direction TB
        RX["ROVER COMMS MASTER\n(xbee_teleop/rx_node)\n*Sole Rover Radio Owner*"]
        SCI_NODE["Science Serial Bridge\n(xbee_teleop/science_node)"]
        TEL_NODE["Telemetry Broadcaster\n(rover_telemetry/telemetry_node)"]
        GPS_ROV["RTK GPS Driver\n(gps_data/rover_gps_node)"]
        ARDUINO["Arduino Mega 2560\n(5 Pumps, LED, Servo)"]

        RF ==>|Serial 0x90 Packets| RX
        WIFI -.->|UDP Datagrams :8888| RX

        RX -->|/cmd_vel & /arm_vel| DRIVE["Drive Motors & Arm Actuators"]
        RX -->|/rover/mode| AUTONOMY["Autonomy / Nav2 Stack"]
        RX -->|/science/actuator_cmd| SCI_NODE
        RX -->|/rtcm (Deduplicated)| GPS_ROV

        SCI_NODE <-->|Serial 9600 S:.. / STATUS:..| ARDUINO
        SCI_NODE -->|/science/actuator_status| TEL_NODE
        GPS_ROV -->|/gps| TEL_NODE

        TEL_NODE -->|/telemetry_tx| RX
        TEL_NODE -.->|Wi-Fi UDP :9003| BACKEND
    end
```

---

## Dual Redundancy & Failover Strategy

To prevent communication loss in harsh field environments, all operator commands (motion, mode toggle, and science actuators) and GPS RTCM corrections are transmitted **simultaneously across two independent physical channels**:

1. **Primary Link (900MHz DigiMesh RF)**: High-penetration RF link using Digi XBee-PRO SX 900 / XBee 3 modules in non-blocking API Mode 1.
2. **Secondary Link (Wi-Fi UDP Uplink)**: High-bandwidth LAN UDP connection on port `8888`.

### Failover & Latency Engine
- **Priority Authority**: The rover treats XBee RF as primary. When XBee packets are healthy, duplicate UDP packets are ignored to eliminate packet jitter.
- **Failover Threshold (`0.35s`)**: If XBee RF drops out for $>350\text{ ms}$, the rover seamlessly switches to Wi-Fi UDP **without zeroing motor velocities or dropping telemetry**.
- **Preemptive Recovery**: As soon as an XBee packet arrives, the rover instantly switches authority back to XBee.
- **RFC 1982 Stale & Latency Protection**: Uses circular sequence arithmetic $\Delta = (seq - last\_seq) \pmod{256}$:
  - $\Delta == 0$: Discarded as duplicate received across the alternate link.
  - $\Delta \ge 128$: Discarded as stale, out-of-order packet delayed by network latency.
  - $0 < \Delta < 128$: Accepted and executed as strictly newer data.
- **Safety Deadman Watchdog (`0.5s`)**: If both channels go silent for $>500\text{ ms}$, all velocities are automatically set to zero for robot and personnel safety.

---

## Network & Radio Configuration (XBee & UDP)

All configuration parameters are centrally defined in **[`base_station/comms_config.py`](file:///home/rezwan/Desktop/rover_com/base_station/comms_config.py)** (Base Station) and **[`rover/src/comms_config.py`](file:///home/rezwan/Desktop/rover_com/rover/src/comms_config.py)** (Rover).

### 1. XBee Radio Parameters (Digi XCTU Setup)
Both the Base Station and Rover radios must be programmed using Digi XCTU with matching RF network parameters:

| Parameter | Recommended Value | Description |
|---|---|---|
| **Firmware Type** | DigiMesh 900MHz / 2.4GHz | Peer-to-peer mesh protocol |
| **API Enable (`AP`)** | `1` (API Mode without escapes) | Essential for non-blocking binary frame transport |
| **Baud Rate (`BD`)** | `7` (`115200 baud`) | High-speed UART link rate |
| **Network ID / PAN (`ID`)** | `3196` (`0x0C7C`) | Must match across all radios in the fleet |
| **Transmit Options (`TO`)** | `0x01` (Disable RF ACK) | Prevents serial lockups and eliminates 20Hz loop freeze |
| **Base 64-bit Address** | `0013A200425DD789` | Target address in `comms_config.py` |
| **Rover 64-bit Address** | `0013A200425E94FF` | Target address in `comms_config.py` |

### 2. Network IP & UDP Port Allocations

| UDP Port | Direction | Sender $\rightarrow$ Receiver | Description |
|---|---|---|---|
| `9001` | Localhost / LAN | Teleop GUI / Web Backend $\rightarrow$ Base Master | Sends 16B `'M'` motion, 3B `'N'` mode, 9B `'S'` science |
| `9002` | Localhost / LAN | Base GPS Survey-In $\rightarrow$ Base Master | Sends raw `0xD3` RTCM3 differential corrections |
| `9003` | LAN / UDP | Rover Telemetry $\rightarrow$ Base Master / Web Backend | Downlink JSON telemetry stream (GPS, battery, IMU, etc.) |
| `8888` | LAN / UDP | Base Master $\rightarrow$ Rover `rx_node` | Dual-redundant Wi-Fi uplink (simultaneous with XBee RF) |
| `8765` | Localhost | Web Backend $\leftrightarrow$ React Frontend | Bidirectional WebSocket stream |
| `5173` | Localhost | React Frontend Web Server | Browser HTTP dashboard |

#### Configuring IP Addresses for Field Operations:
Edit `base_station/comms_config.py`:
```python
# For field operation, set ROVER_IP to the rover's static Wi-Fi IP:
ROVER_IP = '192.168.1.100'

# If running distributed laptops at the base station, set MASTER_IP to the Master PC:
MASTER_IP = '192.168.1.50'
```

---

## Hardware & Software Prerequisites

### Base Station PC (Ubuntu Linux or Windows 10/11)
- Python 3.10+
- Node.js 18+ and `pnpm` (or `npm`)
- Python packages: `pygame>=2.5.0`, `pyserial>=3.5`, `websockets>=11.0.3`
- USB Gamepad (Logitech F710, Xbox One/360, or generic USB HID controller)

### Rover Onboard Computer (NVIDIA Jetson Orin NX/Nano, Raspberry Pi 5, or x86 SBC)
- Ubuntu 24.04 LTS with **ROS 2 Jazzy Jalisco** (or Ubuntu 22.04 with ROS 2 Humble)
- `colcon`, `setuptools`, and Python 3
- Arduino Mega 2560 connected via USB (`/dev/ttyACM0`)
- Quectel LC29H RTK GPS module connected via USB/UART (`/dev/rover_rtk`)
- Digi XBee 900MHz RF module connected via USB/UART (`/dev/rover_900mhz`)

---

## Build & Installation Guide

### 1. Clone the Repository
```bash
git clone https://github.com/RezwanZani/rover-comms.git
cd rover-comms
```

### 2. Base Station Setup
```bash
# 1. Install Base Station Python dependencies
pip install -r requirements.txt

# 2. Install React Frontend dependencies
cd base_station/rover-gui/frontend
pnpm install
cd ../../..
```

### 3. Rover Workspace Build
```bash
# 1. Source ROS 2 core environment
source /opt/ros/jazzy/setup.bash

# 2. Build all onboard packages
cd rover
colcon build --symlink-install

# 3. Source rover installation
source install/setup.bash
cd ..
```

### 4. Setup Stable Hardware Udev Rules (Rover only)
Avoid USB serial port swapping upon reboot by installing the provided udev rules:
```bash
sudo python3 rover/src/rover-gps/setup_udev.py
```
This maps:
- `/dev/rover_900mhz` $\rightarrow$ XBee 900MHz Radio
- `/dev/rover_rtk` $\rightarrow$ Quectel LC29H RTK GPS
- `/dev/ttyACM0` $\rightarrow$ Arduino Mega 2560

---

## Running the System (Single-Command Launch)

### Step 1: Start the Rover Onboard Stack
Run the master rover launcher on the Jetson/SBC:

```bash
# Automatically sources ROS 2, compiles if needed, and launches all onboard nodes:
python3 run_rover_all.py
```

*(Optional CLI overrides:)*
```bash
# Override ports or base station IP:
python3 run_rover_all.py xbee_port:=/dev/ttyUSB0 arduino_port:=/dev/ttyACM0 base_ip:=192.168.1.50

# Disable GPS if running indoors for bench testing:
python3 run_rover_all.py enable_gps:=false
```

### Step 2: Start the Base Station Environment
Run the master base station orchestrator on the operator laptop:

```bash
# Compiles React production bundle and launches Base Master, Web Backend, Preview Server, & Teleop GUI:
python3 run_base_station.py
```

*(On Windows:)*
```bat
python run_base_station.py
# or: base_station\run_base_station.bat
```

This supervisor automatically:
1. Builds the React web application (`pnpm build -> dist/`)
2. Launches `base_master.py` (Priority XBee owner & dual-redundant UDP router)
3. Launches `rover-gui/backend/main.py` (WebSocket & telemetry server on port 8765)
4. Serves the prebuilt web dashboard via `pnpm preview` on port 5173 and opens browser
5. Launches `xbee_teleop_windows.py` (Gamepad teleop GUI & Science Actuators panel)
4. `xbee_teleop_windows.py` (Pygame gamepad control GUI)

Open your browser to: **`http://localhost:5173`**

---

## Subsystems & Operational Modes

### Autonomous vs. Teleop Mode Toggle
- **Control**: Toggle button located in the top-right corner of the web GUI Topbar.
- **Packet Format (`'N'`, 3 bytes)**: `<cBB` (`'N'`, sequence number, `0x00` = `TELEOP`, `0x01` = `AUTONOMOUS`).
- **ROS 2 Topic**: Rover publishes to **`/rover/mode`** (`std_msgs/String`), allowing Nav2 or autonomy nodes to safely engage/disengage.

### Science Mission Subsystem (Pumps, LED, Servo)
Access via the **"🔬 SCIENCE"** button in the web Topbar or navigate to **`/science`**:
- **Setup & Wiring Guide**: Complete guide for the Science Team available at **[`arduino/README.md`](file:///home/rezwan/Desktop/rover_com/arduino/README.md)**.
- **3-Column Layout**:
  - **Left (20%)**: All 5 Camera streams (thumbnails & channel selector).
  - **Middle (54%)**: Selected camera in high-res full view.
  - **Right (26%)**: Actuator control panel.
- **Actuators Controlled**:
  - **5 Peristaltic Pumps**: Independent `ON` and `OFF` power buttons (L298N drivers, Arduino pins 22–31).
  - **Illumination LED**: `LED ON` / `LED OFF` toggle (pins 32, 33).
  - **Sample Carousel Servo**: 0°–180° range slider with preset buttons (`0°`, `45°`, `90°`, `135°`, `180°`, pin 34).
  - **Emergency Stop**: Dedicated `🛑 ALL MOTORS OFF` safety kill switch.
- **Data Protocol**:
  - Uplink packet: `'S'` (9 bytes: `<cBBBBBBBB`).
  - Serial to Arduino: `S:m1,m2,m3,m4,m5,led,servo\n` (e.g. `S:1,0,1,0,0,1,90\n`).
  - Arduino feedback: `STATUS:m1=1,m2=0,m3=1,m4=0,m5=0,led=1,servo=90\n`.
  - ROS 2 Topics: **`/science/actuator_cmd`** (`UInt8MultiArray`) and **`/science/actuator_status`** (`String` JSON).

### RTK GPS Subsystem (Quectel LC29H)
- **Base Survey-In**: `base_station_windows.py` receives RTK base satellite observations, parses RTCM3 differential frames, and feeds them into `base_master.py` via UDP 9002.
- **Over-the-Air Slicing**: Base Master slices RTCM bursts into chunks $\le 256\text{ bytes}$ to prevent Head-of-Line teleop latency spikes.
- **Onboard Injection**: `rx_node` deduplicates RTCM frames using rolling hash checks and publishes to `/rtcm`, which `gps_node` writes directly into the rover's LC29H receiver.

---

## Automated Verification & Bench Testing

Verify protocol packet packing and ROS 2 topic dispatch:

```bash
# 1. Run protocol and packing unit tests
python3 tests/test_science_and_mode.py

# 2. Run ROS 2 topic dispatch tests
source /opt/ros/jazzy/setup.bash
source rover/install/setup.bash
python3 tests/test_rx_node_science.py
```

Expected output:
```
Testing pack_science / unpack...
✅ Science packing test passed!
Testing pack_mode / unpack...
✅ Mode packing test passed!
Testing motion packet backward compatibility...
✅ Motion packet backward compatibility passed!
🎉 ALL TESTS PASSED SUCCESSFULLY!
```

---

## Troubleshooting & FAQ

### 1. `Permission denied` on `/dev/ttyUSB0` or `/dev/ttyACM0`
Add your Linux user to the `dialout` group:
```bash
sudo usermod -aG dialout $USER
# Log out and log back in, or run:
sudo chmod 666 /dev/ttyUSB* /dev/ttyACM*
```

### 2. Serial Port Discovery & Hardware XBee Selection
All physical USB-to-UART adapters (FTDI, CP210x, CH340), udev symlinks (`/dev/rover_*`), and Windows `COM` ports are automatically scanned. They will appear in the port selector dropdown on both the Web UI and Teleop GUI. Ensure the radio's baud rate is set to **115200** (Digi XCTU parameter `BD=7`).

### 3. Wi-Fi Failover Latency Verification
If the physical XBee radio is disconnected or power cycled during operation, the React GUI diagnostics panel will immediately show `WI-FI (UDP)` within $350\text{ ms}$. When the radio reconnects, it returns to `DUAL (Wi-Fi + RF)`.

---

## License & Attribution
Designed and built for the **AAUB ROVER71** team competing in planetary rover robotics competitions. Released under the Apache 2.0 License.
