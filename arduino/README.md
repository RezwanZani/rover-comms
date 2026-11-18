# Science Mission Subsystem — Arduino Mega 2560 Setup Guide

This guide provides instructions for the **Science Team** to assemble, wire, flash, bench-test, and integrate the **Arduino Mega 2560** controlling the rover's science laboratory payload.

---

## 1. Subsystem Overview

The Arduino Mega 2560 acts as the dedicated low-level hardware controller for all science actuators:
- **5 Peristaltic Dosing Pumps** (for soil sample acquisition, chemical reagent injection, and chamber flushing).
- **1 High-Power UV / White Illumination LED** (for sample fluorescing and visual inspection).
- **1 PWM Carousel Servo Motor** (0° to 180° rotation for sample vial indexing).

```
┌──────────────────────────────────────────────────────────────┐
│                    BASE STATION OPERATOR                     │
│  - Web Mission Control Cockpit (http://localhost:5173/science) │
│  - Gamepad Teleop GUI (Ctrl+1..6, Ctrl+Arrows, Ctrl+Z)       │
└──────────────────────────────┬───────────────────────────────┘
                               │ Dual Link (900MHz RF + Wi-Fi UDP)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                  ROVER ONBOARD JETSON / SBC                  │
│  - rx_node: Receives 'S' science packet                      │
│  - /science/actuator_cmd (std_msgs/UInt8MultiArray)          │
│  - science_node.py: Serial bridge at 9600 baud               │
│  - /science/actuator_status (std_msgs/String JSON)           │
└──────────────────────────────┬───────────────────────────────┘
                               │ USB Serial (/dev/ttyACM0 @ 9600)
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                      ARDUINO MEGA 2560                       │
│  - Firmware: arduino/science_mega/science_mega.ino          │
│  - 3x L298N Dual H-Bridge Drivers                           │
│  - 5x 12V Pumps  |  1x LED  |  1x PWM Servo                  │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. Hardware Bill of Materials (BOM)

| Item | Specification | Purpose |
|---|---|---|
| **Microcontroller** | Arduino Mega 2560 (ATmega2560) | Actuator logic & serial communication |
| **Motor Drivers** | 3 x L298N Dual H-Bridge Modules | Driving 5 pumps and high-power LED |
| **Pumps** | 5 x 12V DC Peristaltic Dosing Pumps | Liquid handling & sample reagent routing |
| **Illumination LED**| High-Power UV / White LED Module | Illumination and chemical reaction fluorescence |
| **Servo Motor** | High-Torque Standard Servo (e.g. MG996R) | Sample carousel rotary indexing (0°–180°) |
| **Pump Power** | 12V DC Li-Po Battery or Buck Converter (5A+) | Powering the 5 peristaltic pumps |
| **Servo Power** | 5V or 6V DC Buck Converter (3A+) | Powering the servo (**Never from Arduino 5V!**) |
| **USB Cable** | USB-A to USB-B Cable | Serial connection from Jetson to Arduino Mega |

---

## 3. Pinout & Wiring Specifications

### A. Arduino Pin Mapping Table

| Actuator | Driver Board | Arduino Mega Pins | Driver Output / Terminal | Function |
|---|---|---|---|---|
| **Pump 1** (Sample Intake 1) | Driver 1 | `IN1 = 22`, `IN2 = 23` | OUT1, OUT2 | Digital ON / OFF |
| **Pump 2** (Sample Intake 2) | Driver 1 | `IN1 = 24`, `IN2 = 25` | OUT3, OUT4 | Digital ON / OFF |
| **Pump 3** (Reagent A) | Driver 2 | `IN1 = 26`, `IN2 = 27` | OUT1, OUT2 | Digital ON / OFF |
| **Pump 4** (Reagent B) | Driver 2 | `IN1 = 28`, `IN2 = 29` | OUT3, OUT4 | Digital ON / OFF |
| **Pump 5** (Chamber Flush) | Driver 3 | `IN1 = 30`, `IN2 = 31` | OUT1, OUT2 | Digital ON / OFF |
| **Illumination LED** | Driver 3 | `IN3 = 32`, `IN4 = 33` | OUT3, OUT4 | Digital ON / OFF |
| **Carousel Servo** | Direct PWM | `PWM = Pin 34` | Servo Signal Line | 0° to 180° Angle |

---

### B. Critical Wiring Rules & Power Architecture

> [!CAUTION]
> **COMMON GROUND IS MANDATORY**:
> Connect the ground (`GND`) of the **Arduino Mega**, the **12V pump battery**, the **5V/6V servo power supply**, and all **three L298N drivers** together. Failure to share a common ground will result in floating logic signals, erratic pump firing, and servo jitter.

> [!WARNING]
> **NEVER POWER SERVO OR MOTORS FROM ARDUINO 5V PIN**:
> - An MG996R servo can draw up to $2.5\text{A}$ stall current. Connecting it to the Arduino's 5V pin will cause voltage sags, brownout resets, and could damage the Arduino's onboard 5V regulator.
> - Always power the servo from an independent 5V/6V step-down regulator.
> - Connect only the **Signal wire (Yellow/Orange)** to Arduino **Pin 34**.

### C. L298N Jumper Configurations
On each of the three L298N driver boards:
1. **ENA / ENB Jumpers**: Keep the black jumper caps installed on the `ENA` and `ENB` pin headers. This ties motor enables permanently to 5V logic HIGH so digital pins (`IN1..IN4`) control ON/OFF states cleanly.
2. **5V Regulator Jumper**: If your motor supply is 12V, keep the onboard 5V regulator jumper in place on each L298N.

---

## 4. Firmware Flashing Guide

The firmware source is located at:
[`arduino/science_mega/science_mega.ino`](file:///home/rezwan/Desktop/rover_com/arduino/science_mega/science_mega.ino)

### Step 1: Open in Arduino IDE
1. Launch the **Arduino IDE** (version 1.8.x or 2.x).
2. Open [`arduino/science_mega/science_mega.ino`](file:///home/rezwan/Desktop/rover_com/arduino/science_mega/science_mega.ino).

### Step 2: Configure Board & Port
- In the **Tools** menu:
  - **Board**: Select `Arduino Mega or Mega 2560`.
  - **Processor**: Select `ATmega2560 (Mega 2560)`.
  - **Port**:
    - On Linux: `/dev/ttyACM0` (or check `ls /dev/ttyACM*`).
    - On Windows: `COMx` (check Device Manager).

### Step 3: Upload Firmware
- Press the **Upload** button (or `Ctrl + U`).
- Confirm that the status bar displays `Done uploading`.

---

## 5. Standalone Bench Testing (Serial Monitor)

Before connecting the Arduino to the Jetson, verify all actuators using the Arduino Serial Monitor:

1. Open **Tools → Serial Monitor** (`Ctrl + Shift + M`).
2. Set baud rate to **`9600 baud`** in the bottom-right dropdown.
3. Set line ending to **`Newline`** or **`Both NL & CR`**.

### Test 1: Periodic Feedback Verification
Every 1 second, the Arduino will print its current status feedback:
```text
STATUS:m1=0,m2=0,m3=0,m4=0,m5=0,led=0,servo=0
```

### Test 2: Structured String Protocol
Type the following command into the serial input bar and press Enter:
```text
S:1,0,1,0,0,1,90
```
- **Expected Action**: Pump 1 turns ON, Pump 3 turns ON, LED turns ON, and Servo rotates to 90°.
- **Expected Feedback Response**:
  ```text
  STATUS:m1=1,m2=0,m3=1,m4=0,m5=0,led=1,servo=90
  ```

### Test 3: Emergency All-Stop
Type:
```text
S:0,0,0,0,0,0,90
```
or single character `z`:
- **Expected Action**: All motors and LED turn OFF immediately.

### Test 4: Legacy Quick-Key Reference
The firmware supports single-character keyboard debugging commands:
| Key | Action |
|---|---|
| `x` | Turn ON Motor 1 |
| `c` | Turn ON Motors 1 and 2 |
| `v` | Turn ON Motors 1, 2, and 3 |
| `b` | Turn ON Motors 1, 2, 3, and 4 |
| `n` | Turn ON All 5 Motors |
| `z` | **Emergency Stop**: Turn OFF All Motors |
| `1` | Turn ON Illumination LED |
| `2` | Turn OFF Illumination LED |
| `3` | Move Servo to 0° |
| `4` | Move Servo to 180° |

---

## 6. Integration with Rover ROS 2 Stack

Once bench testing passes, plug the Arduino Mega USB cable into one of the Jetson's USB 3.0 ports.

### 1. Identify USB Port
Check that the Arduino is detected by the Linux kernel:
```bash
ls -l /dev/ttyACM*
```
*(Default expectation is `/dev/ttyACM0`).*

### 2. Launch Onboard Stack
Run the master rover launcher on the Jetson:
```bash
python3 run_rover_all.py
```
This automatically starts `xbee_teleop/science_node`, which binds `/dev/ttyACM0` at 9600 baud.

### 3. Verify ROS 2 Topics
Open a second terminal on the Jetson:
```bash
# Check published actuator status:
ros2 topic echo /science/actuator_status

# Manually publish a test command to the actuators:
ros2 topic pub --once /science/actuator_cmd std_msgs/msg/UInt8MultiArray "{data: [1, 0, 1, 0, 0, 1, 90]}"
```

---

## 7. Base Station Operation

### A. Web Mission Control (`/science`)
1. Run `python3 run_base_station.py` on your operator laptop.
2. In the browser, click the **"🔬 SCIENCE"** tab or visit:
   **`http://localhost:5173/science`**
3. The right-hand actuator control panel provides:
   - **5 Individual Pump Buttons**: Toggle `M1` through `M5` with green active indicators.
   - **Emergency Kill Switch**: Click `ALL MOTORS OFF` to shut down all pumps.
   - **LED Toggle**: Click `LED ON` / `LED OFF`.
   - **Servo Slider**: Continuous 0°–180° slider and preset buttons (`0°`, `45°`, `90°`, `135°`, `180°`).

### B. Teleop GUI Hotkeys (`xbee_teleop_windows.py`)
Operators can also control science actuators from the teleop gamepad/keyboard dashboard:
- `Ctrl + 1`: Toggle Pump 1
- `Ctrl + 2`: Toggle Pump 2
- `Ctrl + 3`: Toggle Pump 3
- `Ctrl + 4`: Toggle Pump 4
- `Ctrl + 5`: Toggle Pump 5
- `Ctrl + 6`: Toggle Illumination LED
- `Ctrl + Left Arrow`: Step Carousel Servo -15°
- `Ctrl + Right Arrow`: Step Carousel Servo +15°
- `Ctrl + Z`: Emergency All Motors OFF

> [!NOTE]
> Actuator status displayed in the Base Station UI reflects **strictly confirmed feedback** from the Arduino via telemetry, guaranteeing that the operator only sees verified physical states.

---

## 8. Science Team Troubleshooting

| Symptom | Cause | Solution |
|---|---|---|
| `avrdude: ser_open(): can't open device "/dev/ttyACM0": Permission denied` | User lacks serial dialout privileges | Run `sudo usermod -aG dialout $USER`, log out, and log back in, or run `sudo chmod 666 /dev/ttyACM0`. |
| Motors buzz/vibrate but do not spin | Insufficient voltage or missing L298N jumpers | Ensure 12V battery is charged ($\ge 11.5\text{V}$) and verify black jumper caps are installed on `ENA` and `ENB` headers. |
| Arduino Mega reboots whenever the servo turns | Voltage sag on 5V logic line | Power the servo from an independent 5V/6V step-down buck converter. Ensure common ground is wired. |
| `science_node` fails with `[Errno 2] could not open port /dev/ttyACM0` | Arduino connected to different port | Check `ls /dev/ttyACM*` or `/dev/ttyUSB*` and pass override: `python3 run_rover_all.py arduino_port:=/dev/ttyACM1`. |
| Web UI commands do not trigger pumps | Communication link offline | Check the Topbar diagnostics in the Web UI: verify that either **900MHz RF** or **Wi-Fi UDP** is showing `CONNECTED`. |
