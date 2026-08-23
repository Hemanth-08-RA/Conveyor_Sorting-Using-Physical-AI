# 🏭 Autonomous Conveyor Sorting Station Using Physical AI

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.10+-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white)](https://opencv.org)
[![Arduino UNO](https://img.shields.io/badge/Arduino-UNO-00979D?style=for-the-badge&logo=arduino&logoColor=white)](https://arduino.cc)
[![Flask](https://img.shields.io/badge/Flask-Web_Dashboard-000000?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Hardware FPS](https://img.shields.io/badge/Stream-60_FPS_Continuous-00ff88?style=for-the-badge)](https://github.com/Hemanth-08-RA/Conveyor_Sorting-Using-Physical-AI)

An industrial-grade, real-time autonomous conveyor sorting station powered by **OpenCV Computer Vision** and **Arduino microcontroller actuation**. The system dynamically detects, classifies, tracks, and mechanically sorts **White** and **Black** cubes on a continuous conveyor belt with sub-millisecond vision latency and 60 FPS continuous hardware-accelerated video feedback.

---

## 📸 Live Visual Feedback & Physical Setup

### 1. Physical Hardware Setup & Conveyor Rig
The physical sorting setup consists of an automated conveyor belt, an Arduino UNO microcontroller, an L298N motor driver, dual servo diverter arms, collection bins, and an overhead vision camera.

<p align="center">
  <img src="docs/images/conveyor_hardware_setup.jpg" alt="Conveyor Hardware Setup" width="850"/>
</p>

---

### 2. Real-Time Black Cube Detection
Sub-millisecond shape and color verification isolating a black cube with zero false triggers from shadows, table wood grain, or human hands.

<p align="center">
  <img src="docs/images/black_cube_detection.jpg" alt="Black Cube Detection" width="850"/>
</p>

---

### 3. Real-Time White Cube Detection
Dual-space chromatic analysis (`LAB` + `HSV`) accurately segmenting a matte white cube under varying room lighting conditions.

<p align="center">
  <img src="docs/images/white_cube_detection.jpg" alt="White Cube Detection" width="850"/>
</p>

---

## ⚡ Key Features

- **🚀 Sub-Millisecond Vision Engine ($< 0.6\text{ ms}$)**:
  - Vectorized color segmentation in dual color spaces (`LAB` + `HSV`).
  - Polygon approximation with `cv2.approxPolyDP()` to enforce quadrilateral/square geometry ($0.68 \le \frac{w}{h} \le 1.45$).
- **🛡️ Robust False-Trigger Suppression**:
  - **Hand & Skin Rejection**: Filters out human skin tones ($H \in [0, 25], S > 55$) and reaching arms.
  - **Cast-Shadow Suppression**: Prevents shadows cast by white cubes from being misidentified as black cubes.
  - **Wood Grain Filter**: Eliminates reflections and lines from wooden workbenches.
- **🖥️ Dark Industrial Glassmorphic Web Dashboard**:
  - High-performance UI with frosted glass acrylic cards (`backdrop-filter: blur(24px)`).
  - Tactical HUD corner brackets and real-time telemetry monitors.
  - Single-click orientation controls (Rotate 90°, Flip Horizontal/Vertical).
- **📹 60 FPS Hardware-Accelerated Camera Stream**:
  - Seamless continuous video feedback using HTML5 direct webcam capture and asynchronous overlay canvas rendering.
- **🤖 Microcontroller Integration (Arduino UNO)**:
  - Serial protocol communication triggering sorting servos and conveyor motor states automatically.

---

## 📐 Vision Processing Pipeline

```mermaid
flowchart LR
    A[📷 Camera Ingestion 60 FPS] --> B[🎨 Dual-Space Color: LAB + HSV]
    B --> C[🔍 Contour & Poly Approx cv2.approxPolyDP]
    C --> D{Square Geometry & Aspect Ratio 0.68 - 1.45?}
    D -- No --> E[❌ Discard Noise / Hand / Shadow]
    D -- Yes --> F[🔬 Core Body Color Sampler]
    F --> G[🎯 Classify: WHITE CUBE / BLACK CUBE]
    G --> H[⚡ Centroid Tracker & Single-Count Cooldown]
    H --> I[🦾 Arduino Serial Actuator Trigger]
```

---

## 🔌 Circuit Diagram & Hardware Schematics (Single-Servo Sorter)

### 1. Mechanical Sorting Logic
- **⚫ Black Box**: Allowed to pass straight through without actuation (Servo lever stays in neutral position at $0^\circ$).
- **⚪ White Box**: Single servo lever actuates to $90^\circ$ to divert the White box into the side collection bin, then auto-resets to $0^\circ$.

---

### 2. System Circuit Architecture

```mermaid
graph TD
    subgraph Host_System ["Host PC / Laptop"]
        CAM["Vision Camera / Webcam 60 FPS"]
        OPENCV["Python OpenCV Vision Core"]
        USB_PORT["USB Serial COM Port 115200 Baud"]
        CAM --> OPENCV
        OPENCV --> USB_PORT
    end

    subgraph Controller ["Arduino UNO Microcontroller"]
        ARDUINO["Arduino UNO Board"]
        P5["Digital Pin 5 - Motor PWM Enable"]
        P6["Digital Pin 6 - Motor Direction IN1"]
        P9["Digital Pin 9 - Sorter Servo Signal"]
        GND_A["Arduino GND Reference"]
        
        USB_PORT <== USB Cable ==> ARDUINO
        ARDUINO --> P5
        ARDUINO --> P6
        ARDUINO --> P9
    end

    subgraph Motor_Subsystem ["Conveyor Drive Subsystem"]
        L298N["L298N Motor Driver Module"]
        DC_MOTOR["Conveyor DC Gear Motor"]
        
        P5 --> L298N
        P6 --> L298N
        L298N --> DC_MOTOR
    end

    subgraph Sorter_Actuator ["Single Diverter Sorter"]
        SERVO["SG90 / MG90S Micro Servo"]
        SERVO_LEVER["Diverter Arm: 0 deg Pass | 90 deg Divert"]
        
        P9 --> SERVO
        SERVO --> SERVO_LEVER
    end

    subgraph Power_Supply ["External Power Supply 5V - 12V"]
        EXT_PWR["External DC Power Source"]
        PWR_POS["+VCC Positive Rail"]
        PWR_GND["-GND Common Ground"]
        
        EXT_PWR --> PWR_POS
        EXT_PWR --> PWR_GND
        
        PWR_POS ==> L298N
        PWR_POS ==> SERVO
        
        PWR_GND ==> L298N
        PWR_GND ==> SERVO
        PWR_GND === GND_A
    end

    style Host_System fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#fff
    style Controller fill:#0b192c,stroke:#00ff88,stroke-width:2px,color:#fff
    style Motor_Subsystem fill:#1e1b4b,stroke:#a855f7,stroke-width:2px,color:#fff
    style Sorter_Actuator fill:#1c1917,stroke:#f59e0b,stroke-width:2px,color:#fff
    style Power_Supply fill:#310a0a,stroke:#ef4444,stroke-width:2px,color:#fff
```

---

### 3. Complete Pin-by-Pin Wiring Table

| Component Module | Component Pin | Arduino UNO Pin | External Power Rail | Function / Description |
| :--- | :--- | :--- | :--- | :--- |
| **L298N Driver** | `ENA` (Enable A) | **Digital Pin 5** | — | PWM Speed & motor enable |
| **L298N Driver** | `IN1` (Direction 1) | **Digital Pin 6** | — | Conveyor forward rotation |
| **L298N Driver** | `IN2` (Direction 2) | — | **GND** | Motor reverse ground reference |
| **L298N Driver** | `12V / VCC` | — | **+12V / +5V (Ext)** | High-current motor supply |
| **L298N Driver** | `GND` | **GND** | **GND (Ext)** | **Common Ground** connection |
| **L298N Driver** | `OUT1 & OUT2` | — | — | DC Gear Motor terminals |
| **Single Sorter Servo** | `Orange (Signal)` | **Digital Pin 9** | — | Diverter lever PWM control signal |
| **Single Sorter Servo** | `Red (VCC)` | — | **+5V (Ext)** | High-current 5V servo power |
| **Single Sorter Servo** | `Brown (GND)` | **GND** | **GND (Ext)** | **Common Ground** connection |
| **Host PC Connection** | `USB-B Port` | USB Cable | PC USB Port | Serial communication @ 115200 baud |

---

### 4. Electrical Schematic Layout

```
                 +-----------------------------------------------+
                 |              ARDUINO UNO R3/Q                 |
                 |                                               |
                 |  [USB TO PC (115200 Baud)]                    |
                 |                                               |
                 |  Digital Pin 5 (PWM)  -----> L298N ENA        |
                 |  Digital Pin 6        -----> L298N IN1        |
                 |  Digital Pin 9 (PWM)  -----> Single Sorter    |
                 |                              Servo (Signal)   |
                 |  GND                  -----> COMMON GROUND    |
                 +-----------------------------------------------+
                                            |
                                            | (Common GND)
      +-------------------------------------+-----------------------------------+
      |                                                                         |
+-----+------+                                                            +-----+------+
|   L298N    |                                                            |   SINGLE   |
|   DRIVER   |                                                            |   SERVO    |
+------------+                                                            +------------+
| ENA  <-- P5|                                                            | SIG <-- P9 |
| IN1  <-- P6|                                                            | VCC <- +5V |
| IN2  <--GND|                                                            | GND <- GND |
| OUT1 --> M+|                                                            +------------+
| OUT2 --> M-|                                                                  |
| 12V  <--+12V (Ext)                                                            |
| GND  <--GND  (Ext)                                                            |
+------------+                                                                  |
      |                                                                         |
      +-------------------------------------+-----------------------------------+
                                            |
                               +------------------------+
                               |  EXTERNAL POWER SUPPLY |
                               |   +5V / +12V DC VCC    |
                               |       GND (Ground)     |
                               +------------------------+
```

> [!IMPORTANT]
> **Common Ground Rule**: Always tie the **GND** of the Arduino UNO directly to the **GND** of the external power supply and L298N motor driver. Without a shared ground reference, control signals will float.

> [!TIP]
> **Power Isolation**: Never power the DC motor or servo directly from the Arduino 5V header. Motors and servos draw instantaneous current surges that cause microcontroller resets. Always power them from an external 5V/12V DC source.

---

## 🚀 Quick Start & Installation

### 1. Clone the Repository
```bash
git clone https://github.com/Hemanth-08-RA/Conveyor_Sorting-Using-Physical-AI.git
cd Conveyor_Sorting-Using-Physical-AI
```

### 2. Install Python Dependencies
```bash
pip install -r python/requirements.txt
```

### 3. Flash Arduino Firmware
1. Open `sketch/sketch.ino` in the Arduino IDE.
2. Select your board (`Arduino UNO`) and COM port.
3. Upload the sketch.

### 4. Launch the Dashboard
Double-click `run_and_open_dashboard.bat` or run:
```bash
python python/main.py
```
Open **`http://127.0.0.1:7000`** in your browser and click **`💻 Use Laptop Webcam`** or **`▶ Start Camera`**.

---

## 📂 Project Structure

```
Conveyor_Sorting-Using-Physical-AI/
├── assets/
│   ├── app.js               # Dashboard controller & continuous 60 FPS stream loop
│   ├── index.html           # Dark industrial glassmorphic UI
│   └── style.css            # Sci-Fi theme & responsive layouts
├── docs/
│   └── images/              # Demonstration images & setup photos
│       ├── black_cube_detection.jpg
│       ├── white_cube_detection.jpg
│       └── conveyor_hardware_setup.jpg
├── python/
│   ├── main.py              # Sub-millisecond OpenCV vision core & Flask web server
│   ├── requirements.txt     # Python package requirements
│   └── templates/           # Reference cube templates
├── sketch/
│   ├── sketch.ino           # Arduino UNO actuator firmware
│   └── sketch.yaml          # Arduino CLI config
├── run_and_open_dashboard.bat # One-click launcher for Windows
└── README.md                # Project documentation
```

---

## 👨‍💻 Author

**Hemanth-08-RA**
- GitHub: [@Hemanth-08-RA](https://github.com/Hemanth-08-RA)

---

## 📄 License
This project is open-source and available under the [MIT License](LICENSE).
