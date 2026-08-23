/*
 * ============================================================================
 * Conveyor Sorting System - Arduino Firmware
 * ============================================================================
 * 
 * Hardware Target: Arduino Uno / Uno R4 / Compatible AVR or ARM Microcontroller
 * 
 * Description:
 * This sketch controls the conveyor belt motor and handles serial commands
 * sent from the Python OpenCV vision host application.
 * 
 * NOTE: The physical sorting actuator (servo) is temporarily removed.
 * Sorting commands (sort_white, sort_grey) are acknowledged over serial 
 * for telemetry and software synchronization without requiring Servo.h.
 * 
 * Supported Serial Commands (terminated with '\n'):
 *  - "start_conveyor" : Activates the conveyor belt motor
 *  - "stop_conveyor"  : Deactivates the conveyor belt motor
 *  - "sort_white"     : Acknowledges white cube sorting trigger
 *  - "sort_grey"      : Acknowledges grey cube sorting trigger
 *  - "reset_counters" : Resets internal Arduino counters
 *  - "status"         : Returns current hardware operating status
 * ============================================================================
 */

// Hardware Pin Configuration
#define MOTOR_ENABLE_PIN   5   // PWM / Digital Pin to control conveyor motor speed/enable
#define MOTOR_DIR_PIN      6   // Optional direction pin (H-bridge / motor driver)
#define LED_STATUS_PIN     13  // On-board LED indicator

// Serial Communication Baud Rate
#define SERIAL_BAUD_RATE   115200

// Internal System State
bool conveyorRunning = false;
unsigned long whiteSortCount = 0;
unsigned long greySortCount = 0;
unsigned long lastHeartbeatTime = 0;

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

  // Initialize serial communication
  Serial.begin(SERIAL_BAUD_RATE);
  inputBuffer.reserve(64);

  // Send startup banner
  Serial.println(F("========================================"));
  Serial.println(F("SYSTEM_READY: Conveyor Sorting Controller"));
  Serial.println(F("STATUS: Awaiting host vision commands..."));
  Serial.println(F("========================================"));
}

void loop() {
  // Read incoming serial commands from Python host
  while (Serial.available() > 0) {
    char inChar = (char)Serial.read();
    
    // Check for newline delimiter indicating end of command
    if (inChar == '\n' || inChar == '\r') {
      if (inputBuffer.length() > 0) {
        inputBuffer.trim();
        handleCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      // Append character to buffer if within capacity
      if (inputBuffer.length() < 60) {
        inputBuffer += inChar;
      }
    }
  }

  // Visual status heartbeat (blinks rapidly when conveyor is running)
  unsigned long currentTime = millis();
  if (conveyorRunning) {
    if (currentTime - lastHeartbeatTime >= 250) {
      lastHeartbeatTime = currentTime;
      digitalWrite(LED_STATUS_PIN, !digitalRead(LED_STATUS_PIN));
    }
  } else {
    // Solid OFF when conveyor is stopped
    digitalWrite(LED_STATUS_PIN, LOW);
  }
}

/**
 * Parses and executes received serial commands.
 * @param command String containing the command keyword.
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
    // Physical sorting actuator pending - send telemetry confirmation
    Serial.print(F("ACK: SORT_WHITE_EXECUTED (Total White: "));
    Serial.print(whiteSortCount);
    Serial.println(F(")"));
  }
  else if (command == "sort_grey") {
    greySortCount++;
    // Physical sorting actuator pending - send telemetry confirmation
    Serial.print(F("ACK: SORT_GREY_EXECUTED (Total Grey: "));
    Serial.print(greySortCount);
    Serial.println(F(")"));
  }
  else if (command == "reset_counters") {
    whiteSortCount = 0;
    greySortCount = 0;
    Serial.println(F("ACK: COUNTERS_RESET"));
  }
  else if (command == "status") {
    Serial.print(F("STATUS: CONVEYOR="));
    Serial.print(conveyorRunning ? F("RUNNING") : F("STOPPED"));
    Serial.print(F(", WHITE="));
    Serial.print(whiteSortCount);
    Serial.print(F(", GREY="));
    Serial.println(greySortCount);
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
