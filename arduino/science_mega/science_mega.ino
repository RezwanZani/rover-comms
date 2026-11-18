#include <Servo.h>

/*
  PROJECT: 5 PERISTALTIC MOTORS + 1 LED + 1 SERVO
  BOARD: Arduino Mega 2560
  MOTOR DRIVERS: 3 x L298N
  SERIAL BAUD RATE: 9600

  PROTOCOL:
    1. Structured Command (Preferred for Jetson ROS 2 bridge):
       "S:m1,m2,m3,m4,m5,led,servo\n"
       Example: "S:1,0,1,0,0,1,90\n"
       - m1..m5: 0 (OFF) or 1 (ON)
       - led: 0 (OFF) or 1 (ON)
       - servo: angle 0 to 180 degrees

    2. Periodic & Command Feedback:
       "STATUS:m1=1,m2=0,m3=1,m4=0,m5=0,led=1,servo=90\n"

    3. Legacy Single-Char Commands (Backward Compatibility):
       x = Motor 1 ON
       c = Motors 1, 2 ON
       v = Motors 1, 2, 3 ON
       b = Motors 1, 2, 3, 4 ON
       n = All 5 Motors ON
       z = All Motors OFF
       1 = LED ON, 2 = LED OFF
       4 = Servo 180°, 3 = Servo 0°
*/

// =====================================
// PIN CONFIGURATION
// =====================================

// Driver 1 - Motor 1
const int M1_IN1 = 22;
const int M1_IN2 = 23;

// Driver 1 - Motor 2
const int M2_IN1 = 24;
const int M2_IN2 = 25;

// Driver 2 - Motor 3
const int M3_IN1 = 26;
const int M3_IN2 = 27;

// Driver 2 - Motor 4
const int M4_IN1 = 28;
const int M4_IN2 = 29;

// Driver 3 - Motor 5
const int M5_IN1 = 30;
const int M5_IN2 = 31;

// Driver 3 - LED
const int LED_IN3 = 32;
const int LED_IN4 = 33;

// Servo Configuration
Servo myServo;
const int SERVO_PIN = 34;
const int SERVO_START_ANGLE = 0;

// Current States
bool motorState[5] = {false, false, false, false, false};
bool ledState = false;
int currentServoAngle = SERVO_START_ANGLE;

// Serial buffer
String inputBuffer = "";
unsigned long lastStatusBroadcast = 0;
const unsigned long STATUS_INTERVAL_MS = 1000; // Periodic feedback every 1 second

// =====================================
// ACTUATOR FUNCTIONS
// =====================================

void setMotor(int motor, bool state) {
  int in1, in2;

  switch (motor) {
    case 0: in1 = M1_IN1; in2 = M1_IN2; break;
    case 1: in1 = M2_IN1; in2 = M2_IN2; break;
    case 2: in1 = M3_IN1; in2 = M3_IN2; break;
    case 3: in1 = M4_IN1; in2 = M4_IN2; break;
    case 4: in1 = M5_IN1; in2 = M5_IN2; break;
    default: return;
  }

  motorState[motor] = state;
  if (state) {
    digitalWrite(in1, HIGH);
    digitalWrite(in2, LOW);
  } else {
    digitalWrite(in1, LOW);
    digitalWrite(in2, LOW);
  }
}

void stopAllMotors() {
  for (int i = 0; i < 5; i++) {
    setMotor(i, false);
  }
}

void setLED(bool state) {
  ledState = state;
  if (state) {
    digitalWrite(LED_IN3, HIGH);
    digitalWrite(LED_IN4, LOW);
  } else {
    digitalWrite(LED_IN3, LOW);
    digitalWrite(LED_IN4, LOW);
  }
}

void moveServo(int targetAngle) {
  targetAngle = constrain(targetAngle, 0, 180);
  myServo.write(targetAngle);
  currentServoAngle = targetAngle;
}

// Print machine-readable status over serial for ROS 2 Jetson bridge
void printStatus() {
  Serial.print("STATUS:m1=");
  Serial.print(motorState[0] ? 1 : 0);
  Serial.print(",m2=");
  Serial.print(motorState[1] ? 1 : 0);
  Serial.print(",m3=");
  Serial.print(motorState[2] ? 1 : 0);
  Serial.print(",m4=");
  Serial.print(motorState[3] ? 1 : 0);
  Serial.print(",m5=");
  Serial.print(motorState[4] ? 1 : 0);
  Serial.print(",led=");
  Serial.print(ledState ? 1 : 0);
  Serial.print(",servo=");
  Serial.println(currentServoAngle);
}

// =====================================
// COMMAND PARSER
// =====================================

void parseStructuredCommand(String cmd) {
  // Format: "S:m1,m2,m3,m4,m5,led,servo"
  // Remove "S:" prefix
  String args = cmd.substring(2);
  args.trim();

  int vals[7] = {0, 0, 0, 0, 0, 0, 0};
  int idx = 0;
  int startIdx = 0;

  for (int i = 0; i <= args.length() && idx < 7; i++) {
    if (i == args.length() || args.charAt(i) == ',') {
      vals[idx] = args.substring(startIdx, i).toInt();
      idx++;
      startIdx = i + 1;
    }
  }

  if (idx >= 6) {
    for (int m = 0; m < 5; m++) {
      setMotor(m, vals[m] != 0);
    }
    setLED(vals[5] != 0);
    if (idx >= 7) {
      moveServo(vals[6]);
    }
    printStatus();
  }
}

void parseLegacyChar(char c) {
  if (c >= 'A' && c <= 'Z') c = c + ('a' - 'A');

  switch (c) {
    case 'x':
      setMotor(0, true);
      break;
    case 'c':
      setMotor(0, true); setMotor(1, true);
      break;
    case 'v':
      setMotor(0, true); setMotor(1, true); setMotor(2, true);
      break;
    case 'b':
      setMotor(0, true); setMotor(1, true); setMotor(2, true); setMotor(3, true);
      break;
    case 'n':
      for (int i = 0; i < 5; i++) setMotor(i, true);
      break;
    case 'z':
      stopAllMotors();
      break;
    case '1':
      setLED(true);
      break;
    case '2':
      setLED(false);
      break;
    case '4':
      moveServo(180);
      break;
    case '3':
      moveServo(0);
      break;
    default:
      return;
  }
  printStatus();
}

// =====================================
// SETUP & LOOP
// =====================================

void setup() {
  Serial.begin(9600);

  // Motor pins
  pinMode(M1_IN1, OUTPUT); pinMode(M1_IN2, OUTPUT);
  pinMode(M2_IN1, OUTPUT); pinMode(M2_IN2, OUTPUT);
  pinMode(M3_IN1, OUTPUT); pinMode(M3_IN2, OUTPUT);
  pinMode(M4_IN1, OUTPUT); pinMode(M4_IN2, OUTPUT);
  pinMode(M5_IN1, OUTPUT); pinMode(M5_IN2, OUTPUT);

  // LED pins
  pinMode(LED_IN3, OUTPUT); pinMode(LED_IN4, OUTPUT);

  // Servo
  myServo.attach(SERVO_PIN);
  myServo.write(SERVO_START_ANGLE);
  currentServoAngle = SERVO_START_ANGLE;

  // Initialize OFF
  stopAllMotors();
  setLED(false);

  inputBuffer.reserve(64);
  Serial.println("SYSTEM READY: SCIENCE MODULE ACTIVE");
  printStatus();
}

void loop() {
  // Read Serial
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      inputBuffer.trim();
      if (inputBuffer.length() > 0) {
        if (inputBuffer.startsWith("S:") || inputBuffer.startsWith("s:")) {
          parseStructuredCommand(inputBuffer);
        } else if (inputBuffer.length() == 1) {
          parseLegacyChar(inputBuffer.charAt(0));
        }
        inputBuffer = "";
      }
    } else {
      if (inputBuffer.length() < 60) {
        inputBuffer += c;
      }
    }
  }

  // Periodic heartbeat / status broadcast
  unsigned long now = millis();
  if (now - lastStatusBroadcast >= STATUS_INTERVAL_MS) {
    lastStatusBroadcast = now;
    printStatus();
  }
}
