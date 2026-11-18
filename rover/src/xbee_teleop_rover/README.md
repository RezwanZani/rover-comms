# xbee_teleop (ROS 2 Jazzy & Humble)

Rover teleoperation, dual-redundant communications receiver, priority failover engine, and Arduino science mission bridge.

---

## 1. Overview & Nodes

The `xbee_teleop` package contains the core communications and control nodes running on the rover:

1. **`rx_node` (Comms Master)**:
   - Receives dual-redundant teleoperation commands over **both 900MHz XBee RF and Wi-Fi UDP (port 8888)**.
   - Demultiplexes packets into ROS 2 topics:
     - `/cmd_vel` (`geometry_msgs/Twist`): Drive linear and angular velocities.
     - `/arm_vel` (`std_msgs/Float32MultiArray`): Robotic arm joint velocities (`act1`, `act2`, `act3`, `wrist`, `gripper`).
     - `/rover/mode` (`std_msgs/String`): Operational mode toggle (`TELEOP` / `AUTONOMOUS`).
     - `/science/actuator_cmd` (`std_msgs/UInt8MultiArray`): 5 pump states, LED, and servo angle.
     - `/rtcm` (`rtcm_msgs/Message` or `UInt8MultiArray`): Deduplicated RTCM3 differential GPS corrections.
   - **XBee Priority & 0.35s Failover**: Uses XBee RF as primary. If XBee goes silent for $>350$ ms, seamlessly switches to Wi-Fi UDP. Resumes XBee instantly when packets return.
   - **RFC 1982 Stale Rejection**: Circular sequence arithmetic `(seq - last_seq) & 0xFF` rejects out-of-order stale packets and cross-channel duplicates.
   - **0.5s Watchdog**: Zeroes `/cmd_vel` and `/arm_vel` if communication drops on both channels.

2. **`science_node` (Arduino Mega 2560 Serial Bridge)**:
   - Connects to Arduino Mega 2560 on `/dev/ttyACM0` at `9600 baud`.
   - Subscribes to `/science/actuator_cmd`.
   - Sends formatted commands: `S:m1,m2,m3,m4,m5,led,servo\n`.
   - Reads feedback `STATUS:m1=..,m2=..,m3=..,m4=..,m5=..,led=..,servo=..\n` and publishes JSON to `/science/actuator_status`.

3. **`tx_node` & `gui` (Optional / Standalone)**:
   - Pure ROS 2 transmitter and local PyQt5 diagnostic GUI for bench testing without the full base station suite.

---

## 2. Launch Files

### Master Launcher (Runs All Nodes)
```bash
ros2 launch xbee_teleop rover_all.launch.py
```
*(Runs `rx_node`, `science_node`, `rover_telemetry_node`, and `rover_gps_node` concurrently)*

#### Useful Parameters:
```bash
ros2 launch xbee_teleop rover_all.launch.py xbee_port:=/dev/ttyUSB0 arduino_port:=/dev/ttyACM0 base_ip:=192.168.1.50
ros2 launch xbee_teleop rover_all.launch.py enable_gps:=false
```

### Dedicated Receiver Launcher
```bash
ros2 launch xbee_teleop rx.launch.py
```

---

## 3. Radio Configuration (Digi XCTU)
- **Baud Rate**: 115200 (`BD = 7`)
- **API Mode**: API Mode 1 without escapes (`AP = 1`)
- **Network ID / PAN**: `3196` (`0x0C7C`)
- **Transmit Options**: Disable RF ACK (`TO = 0x01`)
