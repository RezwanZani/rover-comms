# Science Mission Subsystem — Arduino Mega 2560 Firmware

This directory contains the firmware for the **Arduino Mega 2560** microcontroller controlling the rover's science payload.

---

## Hardware Configuration

- **Microcontroller**: Arduino Mega 2560
- **Motor Drivers**: 3 x L298N Dual H-Bridge Motor Drivers
- **Actuators**:
  - 5 x 12V Peristaltic Dosing Pumps
  - 1 x High-Power UV / White Illumination LED
  - 1 x PWM Sample Carousel Servo Motor (0° to 180°)
- **Serial Connection**: USB Serial to NVIDIA Jetson / SBC at **`9600 baud`** (`/dev/ttyACM0`)

---

## Pinout Mapping

| Component | Driver | Arduino Pins | Function |
|---|---|---|---|
| **Motor 1** (Sample Pump 1) | Driver 1 | `IN1 = 22`, `IN2 = 23` | Digital Forward / Stop |
| **Motor 2** (Sample Pump 2) | Driver 1 | `IN1 = 24`, `IN2 = 25` | Digital Forward / Stop |
| **Motor 3** (Reagent Pump 1) | Driver 2 | `IN1 = 26`, `IN2 = 27` | Digital Forward / Stop |
| **Motor 4** (Reagent Pump 2) | Driver 2 | `IN1 = 28`, `IN2 = 29` | Digital Forward / Stop |
| **Motor 5** (Flush / Purge Pump) | Driver 3 | `IN1 = 30`, `IN2 = 31` | Digital Forward / Stop |
| **Illumination LED** | Driver 3 | `IN3 = 32`, `IN4 = 33` | Digital ON / OFF |
| **Sample Servo** | Direct / PWM | `PWM = 34` | Servo Position (0°–180°) |

---

## Serial Communication Protocol

### 1. Structured Command (Jetson ROS 2 $\rightarrow$ Arduino)
Sent by `xbee_teleop/science_node` over USB serial at 9600 baud:

```
S:m1,m2,m3,m4,m5,led,servo\n
```

- `m1` to `m5`: `0` (OFF) or `1` (ON)
- `led`: `0` (OFF) or `1` (ON)
- `servo`: `0` to `180` degrees

**Example:**
`S:1,0,1,0,0,1,90\n`
Turns ON Motor 1, Motor 3, and LED, and sets the servo to 90 degrees.

### 2. Feedback Status (Arduino $\rightarrow$ Jetson ROS 2)
Emitted by the Arduino immediately after command execution and periodically every 1 second:

```
STATUS:m1=1,m2=0,m3=1,m4=0,m5=0,led=1,servo=90\n
```

Parsed by `science_node.py` and published to `/science/actuator_status` for GUI display.

### 3. Legacy Single-Character Commands (Manual Debugging)
If testing via the Arduino IDE Serial Monitor at 9600 baud:
- `x`: Motor 1 ON
- `c`: Motors 1, 2 ON
- `v`: Motors 1, 2, 3 ON
- `b`: Motors 1, 2, 3, 4 ON
- `n`: All 5 Motors ON
- `z`: All Motors OFF (Emergency Stop)
- `1`: LED ON
- `2`: LED OFF
- `4`: Servo 180°
- `3`: Servo 0°

---

## Flashing Instructions

1. Open [`science_mega/science_mega.ino`](file:///home/rezwan/Desktop/rover_com/arduino/science_mega/science_mega.ino) in the Arduino IDE.
2. Select Board: **Arduino Mega or Mega 2560**.
3. Select Processor: **ATmega2560 (Mega 2560)**.
4. Select Port: **`/dev/ttyACM0`** (Linux) or **`COMx`** (Windows).
5. Click **Upload** (`Ctrl+U`).
