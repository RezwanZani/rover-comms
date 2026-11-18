# Base Station Subsystem

The Base Station subsystem manages all operator inputs, teleoperation packaging, base RTK GPS survey-in corrections, and telemetry diagnostics.

---

## Architecture Summary

```
[ Gamepad Teleop ] ──► UDP 9001 ──┐
                                   ▼
[ Base GPS RTCM  ] ──► UDP 9002 ──► [ BASE MASTER HUB ] ═══► XBee 900MHz RF (Priority Serial)
                                    (base_master.py)    ─ ─ ─► Wi-Fi UDP :8888 (Dual Redundant)
                                           │
                                           ▼ UDP 9003
                                    [ GUI Backend ] ◄─── Wi-Fi UDP :9003 (Rover Telemetry)
                                           │ WebSocket :8765
                                           ▼
                                    [ React Frontend ]
```

---

## Directory Layout

```
base_station/
├── comms_config.py            ← Single Source of Truth for Base Station ports & settings
├── base_master.py             ← Central Base Radio Owner & Dual-Redundant Uplink Router
├── launch_base_station.py     ← Multi-process supervisor launcher
├── run_base_station.bat       ← Windows one-click startup batch script
├── run_base_master.bat        ← Dedicated Base Master launcher (Windows)
├── run_base_master.sh         ← Dedicated Base Master launcher (Linux)
├── xbee_teleop_windows.py     ← Gamepad Teleoperation GUI (Pygame/Tkinter)
├── base_station_windows.py    ← Stationary LC29H(BS) RTK GPS Survey-In Script
├── rover-gui/                 ← React + FastAPI Web Diagnostics Dashboard
│   ├── backend/main.py        ← Telemetry aggregator & WebSocket bridge (:8765)
│   └── frontend/              ← React 18 + TailwindCSS + Lucide Icons
```

---

## Component Roles

### 1. `base_master.py` (Central Communications Hub)
- **Role**: Sole owner of the physical Base Station XBee serial radio (`TELEOP_XBEE_PORT`).
- **UDP Inputs**:
  - `UDP 9001`: Listens for 16-byte `'M'` motion packets from joystick scripts.
  - `UDP 9002`: Listens for raw `0xD3` RTCM3 frames from the base GPS module.
- **Dual-Redundant Transmit**:
  - Every `'M'` packet and RTCM frame is simultaneously transmitted across the physical XBee serial port **and** fired over Wi-Fi UDP to `ROVER_IP:ROVER_UDP_LISTEN_PORT` (e.g. `127.0.0.1:8888`).
- **Priority Queuing**:
  - Teleoperation packets strictly preempt RTCM packets.
  - RTCM frames are sliced into chunks $\le 256$ bytes (`RTCM_CHUNK_MAX = 256`) to prevent serial line blocking.
- **Downlink Forwarder**:
  - Receives incoming frames from XBee (`'T'` telemetry, `'A'` ACKs) and forwards them to `UDP 9003`.

### 2. `launch_base_station.py` (Supervisor Launcher)
- Python supervisor that launches all base station components in the correct sequence with proper delays:
  1. `base_master.py` (Router Hub)
  2. `rover-gui/backend/main.py` (FastAPI / WebSocket server on port 8765)
  3. `rover-gui/frontend` (`pnpm dev` on port 5173)
  4. `xbee_teleop_windows.py` (Gamepad teleop GUI)
  5. `base_station_windows.py` (Optional RTK GPS survey-in)
- Features unified process management, Ctrl+C group cleanup, and independent log routing.

### 3. `rover-gui` (Dashboard Frontend & Backend)
- Displays live telemetry and communications health:
  - **Transport Channel**: Shows active link mode (`DUAL_ACTIVE`, `XBEE`, `UDP`, or `OFFLINE`).
  - **XBee Link**: Connection state, baud rate, and packet rates.
  - **LC29H GPS**: RTK Fix status (`RTK FIXED`, `RTK FLOAT`, `3D FIX`, `NO FIX`), coordinates, and satellites.
  - **RTCM3 Corrections**: Live injection status and freshness counter.

---

## How to Configure

All parameters are configured in [`comms_config.py`](file:///home/rezwan/Desktop/rover_com/base_station/comms_config.py):
- For multi-PC operation over Wi-Fi, change:
  ```python
  MASTER_IP = '127.0.0.1'   # Set to this PC's LAN IP if running distributed scripts
  ROVER_IP  = '127.0.0.1'   # Set to the Rover's LAN IP for Wi-Fi UDP dual uplink
  ```

---

## How to Run

### Option 1: Complete Automated Launch (Recommended)
From repository root:
```bash
./run_base_station.sh
# OR on Windows:
base_station\run_base_station.bat
```

### Option 2: Step-by-Step Launch
1. Start Base Master Hub:
   ```bash
   python3 base_station/base_master.py
   ```
2. Start GUI Backend:
   ```bash
   cd base_station/rover-gui/backend && python3 main.py
   ```
3. Start GUI Frontend:
   ```bash
   cd base_station/rover-gui/frontend && pnpm dev
   ```
4. Start Teleop Controller:
   ```bash
   python3 base_station/xbee_teleop_windows.py
   ```
