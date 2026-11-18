#!/usr/bin/env python3
"""
launch_base_station.py -- Master Base Station Orchestrator & Supervisor.

Starts all base station processes in the exact, safe dependency order:
  1. Base Master Hub (base_master.py)       -> Sole owner of Base XBee radio
  2. Web GUI Backend (backend/main.py)      -> WebSocket & Telemetry aggregator
  3. Web GUI Frontend (pnpm dev)            -> React Mission Dashboard
  4. Base RTK GPS (base_station_windows.py) -> Optional RTCM Survey-In (with --gps)
  5. Teleop GUI (xbee_teleop_windows.py)    -> Gamepad/Keyboard Teleoperation

Features:
  - Clean lifecycle: Ctrl+C or closing Teleop GUI shuts down all child processes cleanly.
  - Automatic venv detection for backend.
  - CLI flags:
      --port <PORT>   : Override XBee serial port (e.g. /tmp/ttyV0, /dev/ttyUSB0, COM3)
      --gps           : Also launch Base RTK GPS survey-in station
      --no-web        : Skip React Web GUI and backend (run Teleop only)
      --no-teleop     : Skip Teleop GUI (run Base Master + Web GUI only)
"""

import os
import sys
import time
import signal
import argparse
import subprocess
import shutil

# Ensure base_station root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from comms_config import TELEOP_XBEE_PORT, UDP_JOY_PORT, UDP_RTCM_PORT, UDP_STATUS_PORT


class BaseStationSupervisor:
    def __init__(self, port=None, enable_gps=False, enable_web=True, enable_teleop=True):
        self.port = port if port else TELEOP_XBEE_PORT
        self.enable_gps = enable_gps
        self.enable_web = enable_web
        self.enable_teleop = enable_teleop
        self.processes = []
        self.shutting_down = False

    def _get_python_executable(self, venv_dir):
        """Find Python inside a virtualenv across Linux and Windows."""
        if sys.platform.startswith('win'):
            cand = os.path.join(venv_dir, 'Scripts', 'python.exe')
        else:
            cand = os.path.join(venv_dir, 'bin', 'python')
        if os.path.exists(cand):
            return cand
        return sys.executable

    def log(self, tag, message):
        print(f"\033[1;36m[{tag}]\033[0m {message}")

    def error(self, tag, message):
        print(f"\033[1;31m[{tag} ERROR]\033[0m {message}")

    def spawn(self, name, cmd, cwd=BASE_DIR, env=None):
        """Spawn a managed child process."""
        self.log("START", f"Launching {name}...")
        proc_env = os.environ.copy()
        if env:
            proc_env.update(env)
        try:
            p = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=proc_env,
                stdout=None,
                stderr=None,
            )
            self.processes.append((name, p))
            return p
        except Exception as e:
            self.error(name, f"Failed to start: {e}")
            return None

    def start_all(self):
        print("=" * 65)
        print("  ROVER BASE STATION MASTER LAUNCHER")
        print(f"  Target Radio Port : {self.port}")
        print(f"  Web GUI Enabled   : {self.enable_web}")
        print(f"  RTK GPS Enabled   : {self.enable_gps}")
        print(f"  Teleop GUI Enabled: {self.enable_teleop}")
        print("=" * 65)

        # -------------------------------------------------------------
        # STEP 1: Base Master Hub (Sole XBee Radio Owner)
        # -------------------------------------------------------------
        bm_cmd = [sys.executable, os.path.join(BASE_DIR, 'base_master.py')]
        if self.port:
            bm_cmd.append(self.port)
        bm_proc = self.spawn("BaseMaster", bm_cmd, cwd=BASE_DIR)
        if not bm_proc:
            self.error("BaseMaster", "Could not start master communications hub. Aborting.")
            self.shutdown()
            return
        time.sleep(0.8)   # Give sockets time to bind and check serial

        # -------------------------------------------------------------
        # STEP 2: Web GUI Backend (WebSocket Server & Telemetry Engine)
        # -------------------------------------------------------------
        if self.enable_web:
            backend_dir = os.path.join(BASE_DIR, 'rover-gui', 'backend')
            backend_venv = os.path.join(backend_dir, '.venv')
            backend_py = self._get_python_executable(backend_venv)
            
            be_cmd = [backend_py, os.path.join(backend_dir, 'main.py')]
            self.spawn("WebBackend", be_cmd, cwd=backend_dir)
            time.sleep(0.5)

            # ---------------------------------------------------------
            # STEP 3: Web GUI Frontend (Vite / React Dashboard)
            # ---------------------------------------------------------
            frontend_dir = os.path.join(BASE_DIR, 'rover-gui', 'frontend')
            pkg_mgr = 'pnpm' if shutil.which('pnpm') else ('npm' if shutil.which('npm') else None)
            if pkg_mgr and os.path.exists(frontend_dir):
                fe_cmd = [pkg_mgr, 'dev']
                self.spawn("WebFrontend", fe_cmd, cwd=frontend_dir)
                time.sleep(0.5)
            else:
                self.log("WebFrontend", "Node/pnpm not found or frontend missing. Skipping Web Frontend.")

        # -------------------------------------------------------------
        # STEP 4: Base RTK GPS Survey-In (Optional)
        # -------------------------------------------------------------
        if self.enable_gps:
            gps_dir = os.path.join(BASE_DIR, 'gps')
            gps_script = os.path.join(gps_dir, 'base_station_windows.py')
            if os.path.exists(gps_script):
                self.spawn("BaseGPS", [sys.executable, gps_script], cwd=gps_dir)
                time.sleep(0.5)

        # -------------------------------------------------------------
        # STEP 5: Teleop GUI (Gamepad / Keyboard)
        # -------------------------------------------------------------
        teleop_proc = None
        if self.enable_teleop:
            teleop_dir = os.path.join(BASE_DIR, 'run_teleop_base')
            teleop_script = os.path.join(teleop_dir, 'xbee_teleop_windows.py')
            if os.path.exists(teleop_script):
                teleop_proc = self.spawn("TeleopGUI", [sys.executable, teleop_script], cwd=teleop_dir)

        print("\n\033[1;32m✅ All requested base station services are ACTIVE.\033[0m")
        print("  - Press Ctrl+C in this terminal (or close Teleop GUI) to stop all services.\n")

        # -------------------------------------------------------------
        # SUPERVISION LOOP
        # -------------------------------------------------------------
        try:
            while not self.shutting_down:
                # If teleop GUI was launched and closed by the user, initiate clean shutdown
                if teleop_proc and teleop_proc.poll() is not None:
                    self.log("SUPERVISOR", "Teleop GUI closed by user. Shutting down all services...")
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\n")
            self.log("SUPERVISOR", "Keyboard interrupt received. Stopping all services...")
        finally:
            self.shutdown()

    def shutdown(self):
        """Gracefully terminate all spawned child processes in reverse order."""
        if self.shutting_down:
            return
        self.shutting_down = True
        print("\n" + "=" * 65)
        self.log("SHUTDOWN", "Terminating base station processes...")

        for name, proc in reversed(self.processes):
            if proc and proc.poll() is None:
                self.log("STOP", f"Terminating {name} (PID {proc.pid})...")
                try:
                    proc.terminate()
                except Exception:
                    pass

        # Allow grace period for clean termination
        time.sleep(0.8)

        # Force kill any lingering processes
        for name, proc in reversed(self.processes):
            if proc and proc.poll() is None:
                self.log("KILL", f"Force killing {name} (PID {proc.pid})...")
                try:
                    proc.kill()
                except Exception:
                    pass

        self.log("SHUTDOWN", "All base station processes stopped cleanly.")
        print("=" * 65)


def main():
    parser = argparse.ArgumentParser(description="Rover Base Station Orchestrator")
    parser.add_argument('port', nargs='?', default=None, help="Serial port for Base XBee radio (e.g. /tmp/ttyV0, COM3)")
    parser.add_argument('--port', dest='port_flag', default=None, help="Explicit port flag")
    parser.add_argument('--gps', action='store_true', help="Start Base RTK GPS survey-in station")
    parser.add_argument('--no-web', action='store_true', help="Do not start React frontend and backend")
    parser.add_argument('--no-teleop', action='store_true', help="Do not start PyQt5 Joystick Teleop GUI")
    args = parser.parse_args()

    selected_port = args.port_flag if args.port_flag else args.port

    supervisor = BaseStationSupervisor(
        port=selected_port,
        enable_gps=args.gps,
        enable_web=not args.no_web,
        enable_teleop=not args.no_teleop,
    )

    # Register OS signal handlers
    def handle_signal(sig, frame):
        supervisor.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    supervisor.start_all()


if __name__ == '__main__':
    main()
