/*
 * ============================================================================
 * Conveyor Sorting System - Arduino Firmware (Single-Servo Diverter)
 * ============================================================================
 * 
 * Hardware Target: Arduino UNO Q Microcontroller
 * 
 * Operational Behavior:
 *  - Black Box: Allowed to pass straight through without actuation (Servo at 0°).
 *  - White Box: Sorter servo lever swings to 90° to divert White box into side bin,
 *               then automatically resets back to 0°.
 * 
 * Supported Serial Commands (terminated with '\n'):
 *  - "start_conveyor" : Activates the conveyor belt motor
 *  - "stop_conveyor"  : Deactivates the conveyor belt motor
 *  - "sort_white"     : Actuates single servo diverter lever (0° -> 90° -> 0°)
 *  - "sort_black"     : Allows black box to pass through (Servo stays at 0°)
 *  - "sort_grey"      : Same as sort_black
 *  - "reset_counters" : Resets internal Arduino counters
 *  - "status"         : Returns current hardware operating status
 * ============================================================================
 */

#include <Servo.h>

// Hardware Pin Configuration
#define MOTOR_ENABLE_PIN   5   // PWM Pin to control conveyor motor speed/enable (L298N ENA)
#define MOTOR_DIR_PIN      6   // Direction pin (L298N IN1)
#define SERVO_PIN          9   // Single Diverter Sorter Servo Signal (PWM Pin 9)
#define LED_STATUS_PIN     13  // On-board LED indicator

// Servo Angles
#define SERVO_PASS_POS     0   // Neutral angle: Allows Black Box to pass straight through
#define SERVO_SORT_POS     90  // Active angle: Swings lever to divert White Box

// Serial Communication Baud Rate
#define SERIAL_BAUD_RATE   115200

// Servo Actuator Object
Servo sorterServo;

// Internal System State
bool conveyorRunning = false;
unsigned long whiteSortCount = 0;
unsigned long blackSortCount = 0;
unsigned long lastHeartbeatTime = 0;

// Non-blocking servo reset timer
bool isServoActive = false;
unsigned long servoActivatedTime = 0;
const unsigned long SERVO_HOLD_DURATION_MS = 750; // Lever hold time before resetting

// Input buffer for non-blocking serial reading
String inputBuffer = "";

void setup() {
  // Initialize digital output pins
  pinMode(MOTOR_ENABLE_PIN, OUTPUT);
  pinMode(MOTOR_DIR_PIN, OUTPUT);
  pinMode(LED_STATUS_PIN, OUTPUT);

  // Set initial safe states (Motor OFF)
  digitalWrite(MOTOR_ENABLE_PIN, LOW);
  digitalWrite(MOTOR_DIR_PIN, HIGH); // Forward direction
  digitalWrite(LED_STATUS_PIN, LOW);

  // Attach and initialize single diverter servo to neutral pass-through position
  sorterServo.attach(SERVO_PIN);
  sorterServo.write(SERVO_PASS_POS);

  // Initialize serial communication
  Serial.begin(SERIAL_BAUD_RATE);
  inputBuffer.reserve(64);

  // Send startup banner
  Serial.println(F("========================================"));
  Serial.println(F("SYSTEM_READY: Arduino UNO Q Sorter Rig"));
  Serial.println(F("BEHAVIOR: Black=Pass Straight | White=Divert"));
  Serial.println(F("========================================"));
}

void loop() {
  // 1. Read incoming serial commands from Python OpenCV host
  while (Serial.available() > 0) {
    char inChar = (char)Serial.read();
    
    if (inChar == '\n' || inChar == '\r') {
      if (inputBuffer.length() > 0) {
        inputBuffer.trim();
        handleCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      if (inputBuffer.length() < 60) {
        inputBuffer += inChar;
      }
    }
  }

  // 2. Non-blocking servo lever auto-reset (returns to 0° after sorting)
  if (isServoActive && (millis() - servoActivatedTime >= SERVO_HOLD_DURATION_MS)) {
    sorterServo.write(SERVO_PASS_POS);
    isServoActive = false;
  }

  // 3. Heartbeat LED status
  unsigned long currentTime = millis();
  if (conveyorRunning) {
    if (currentTime - lastHeartbeatTime >= 250) {
      lastHeartbeatTime = currentTime;
      digitalWrite(LED_STATUS_PIN, !digitalRead(LED_STATUS_PIN));
    }
  } else {
    digitalWrite(LED_STATUS_PIN, LOW);
  }
}

/**
 * Parses and executes received serial commands.
 */
void handleCommand(String command) {
  command.toLowerCase();

  if (command == "start_conveyor") {
    conveyorRunning = true;
    digitalWrite(MOTOR_DIR_PIN, HIGH);
    digitalWrite(MOTOR_ENABLE_PIN, HIGH);
    Serial.println(F("ACK: CONVEYOR_STARTED"));
  }
  else if (command == "stop_conveyor") {
    conveyorRunning = false;
    digitalWrite(MOTOR_ENABLE_PIN, LOW);
    Serial.println(F("ACK: CONVEYOR_STOPPED"));
  }
  else if (command == "sort_white") {
    whiteSortCount++;
    // Actuate single servo lever to divert White Cube
    sorterServo.write(SERVO_SORT_POS);
    isServoActive = true;
    servoActivatedTime = millis();
    
    Serial.print(F("ACK: SORT_WHITE_ACTUATED (Lever 90 deg | Total White: "));
    Serial.print(whiteSortCount);
    Serial.println(F(")"));
  }
  else if (command == "sort_black" || command == "sort_grey") {
    blackSortCount++;
    // Keep lever at 0 deg to allow Black Cube to pass straight through
    sorterServo.write(SERVO_PASS_POS);
    
    Serial.print(F("ACK: SORT_BLACK_PASS_THROUGH (Lever 0 deg | Total Black: "));
    Serial.print(blackSortCount);
    Serial.println(F(")"));
  }
  else if (command == "reset_counters") {
    whiteSortCount = 0;
    blackSortCount = 0;
    sorterServo.write(SERVO_PASS_POS);
    Serial.println(F("ACK: COUNTERS_RESET"));
  }
  else if (command == "status") {
    Serial.print(F("STATUS: CONVEYOR="));
    Serial.print(conveyorRunning ? F("RUNNING") : F("STOPPED"));
    Serial.print(F(", WHITE="));
    Serial.print(whiteSortCount);
    Serial.print(F(", BLACK="));
    Serial.println(blackSortCount);
  }
  else if (command == "ping") {
    Serial.println(F("ACK: PONG"));
  }
  else {
    Serial.print(F("ERR: UNKNOWN_COMMAND ["));
    Serial.print(command);
    Serial.println(F("]"));
  }
}
