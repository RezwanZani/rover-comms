# Base Station Subsystem

The Base Station subsystem manages all operator inputs, teleoperation command packaging, base RTK GPS survey-in corrections, and telemetry diagnostics.

---

## Architecture Summary

```
[ Gamepad Teleop ] ──────────────► UDP 9001: 'M' Motion ─┐
                                                         ▼
[ Web GCS Dashboard ] ───────────► UDP 9001: 'N' Mode & 'S' Science ──► [ BASE MASTER HUB ] ═══► XBee 900MHz RF (Priority)
                                                         ▲              (base_master.py)    ─ ─ ─► Wi-Fi UDP :8888 (Dual Redundant)
[ Base GPS RTCM Survey-In ] ─────► UDP 9002: RTCM3 ─────┘                      │
                                                                               ▼ UDP 9003
                                                                        [ GUI Backend ] ◄─── Wi-Fi UDP :9003 (Rover Telemetry)
                                                                        (main.py)
                                                                               │ WebSocket :8765
                                                                               ▼
                                                                        [ React Frontend ]
                                                                        (Mission Dashboard & /science)
```

---

## Directory Layout

```
base_station/
├── comms_config.py            ← Single Source of Truth for Base Station configuration
├── base_master.py             ← Central Base Radio Owner & Dual-Redundant Uplink Router
├── launch_base_station.py     ← Multi-process supervisor launcher
├── run_base_station.bat       ← Windows one-click startup batch script
├── run_base_master.bat        ← Dedicated Base Master launcher (Windows)
├── run_base_master.sh         ← Dedicated Base Master launcher (Linux)
├── xbee_teleop_windows.py     ← Gamepad Teleoperation GUI (Pygame/Tkinter)
├── base_station_windows.py    ← Stationary LC29H(BS) RTK GPS Survey-In Script
└── rover-gui/                 ← Web Diagnostics & Science Mission Dashboard
    ├── backend/main.py        ← Telemetry aggregator & WebSocket bridge (:8765)
    └── frontend/              ← React 19 + Vite + TailwindCSS 4 Dashboard
        └── src/pages/SciencePage.tsx ← 3-Column Science Mission Page
```

---

## Component Roles

### 1. `base_master.py` (Central Communications Hub)
- **Role**: Sole owner of the physical Base Station XBee serial radio (`TELEOP_XBEE_PORT`).
- **UDP Inputs**:
  - `UDP 9001`: Listens for:
    - 16-byte `'M'` motion packets from joystick scripts.
    - 3-byte `'N'` operational mode packets (`TELEOP` / `AUTONOMOUS`).
    - 9-byte `'S'` science actuator packets (5 pumps, LED, servo).
  - `UDP 9002`: Listens for raw `0xD3` RTCM3 frames from the base GPS module.
- **Dual-Redundant Transmit**:
  - Every `'M'`, `'N'`, `'S'`, and RTCM packet is simultaneously transmitted across the physical XBee serial port **and** fired over Wi-Fi UDP to `ROVER_IP:ROVER_UDP_LISTEN_PORT` (e.g. `127.0.0.1:8888` or `192.168.1.100:8888`).
- **Priority Queuing**:
  - Critical teleop and mission commands strictly preempt RTCM packets.
  - RTCM frames are sliced into chunks $\le 256$ bytes (`RTCM_CHUNK_MAX = 256`) to prevent serial line blocking.
- **Downlink Forwarder**:
  - Receives incoming frames from XBee (`'T'` telemetry, `'A'` ACKs) and forwards them to `UDP 9003`.

### 2. `launch_base_station.py` (Supervisor Launcher)
- Python supervisor that launches all base station components in the correct sequence with proper delays:
  1. `base_master.py` (Router Hub & radio owner)
  2. `rover-gui/backend/main.py` (WebSocket server on port 8765)
  3. `rover-gui/frontend` (`pnpm dev` on port 5173)
  4. `xbee_teleop_windows.py` (Gamepad teleop GUI + Science Actuator panel with Ctrl+1..6, Ctrl+Arrows, and Ctrl+Z)
  5. `base_station_windows.py` (Optional RTK GPS survey-in with `--gps`)
- Features unified process management, graceful Ctrl+C group cleanup, and independent log routing.

### 3. `rover-gui` (Dashboard Frontend & Backend)
- Displays live telemetry and communications health:
  - **Transport Channel**: Shows active link mode (`DUAL_ACTIVE`, `XBEE`, `UDP`, or `OFFLINE`).
  - **Operational Mode**: Mode toggle button in Topbar (`→ AUTO` / `→ TELEOP`).
  - **Science Mission Page (`/science`)**: 3-column view with 5 selectable camera feeds, large video monitor, and 5 peristaltic pump controls + LED + servo controls.
  - **XBee Link**: Connection state, baud rate, and packet rates.
  - **LC29H GPS**: RTK Fix status (`RTK FIXED`, `RTK FLOAT`, `3D FIX`, `NO FIX`), coordinates, and satellites.
  - **RTCM3 Corrections**: Live injection status and freshness counter.

---

## Configuration (`comms_config.py`)

All parameters are configured in [`comms_config.py`](file:///home/rezwan/Desktop/rover_com/base_station/comms_config.py):
```python
# Rover target IP for Wi-Fi UDP dual uplink:
ROVER_IP = '192.168.1.100'

# Base Station Master IP (use LAN IP if running multiple operator laptops):
MASTER_IP = '127.0.0.1'

# Serial port for Base Station XBee radio:
TELEOP_XBEE_PORT = 'COM3'   # On Windows (or /dev/ttyUSB0 on Linux)
XBEE_BAUD_RATE   = 115200
```

---

## How to Run

### Automated Multi-Process Launch (Recommended)
From repository root:
```bash
./run_base_station.sh
```
*(On Windows:)*
```bat
base_station\run_base_station.bat
```

Access the Web GCS at: **`http://localhost:5173`**
Access the Science Mission cockpit at: **`http://localhost:5173/science`**
