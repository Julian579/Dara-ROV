# ROV
# ROV Control System (Python + Arduino Ethernet)

## Overview

This project implements a real-time **ROV (Remotely Operated Vehicle) control system** using:

* A **Python client** (Pygame + UDP) for joystick input and command transmission
* An **Arduino-based controller** (Ethernet + UDP) for motor actuation

The system supports:

* 4-directional vector/mecanum drive
* Vertical thrusters (UP motors)
* Gripper control
* Failsafe motor shutdown on communication loss

---

## System Architecture

```
[Joystick Controller]
        ↓
   Python Script (Pygame)
        ↓ UDP (WiFi/Ethernet)
   Arduino + Ethernet Shield
        ↓
   Motor Drivers + Thrusters + Gripper
```

---

## Features

### Python Controller

* Joystick input via `pygame`
* Deadzone filtering for noise reduction
* Moving average smoothing
* Adjustable speed modes:

  * Button A (0): Full Power (255)
  * Button B (1): Precision Mode (150)
* Gripper control:

  * Button LB (4): Open
  * Button RB (5): Close
* Vector-based motor mixing
* UDP packet transmission (~20Hz)

### Arduino Controller

* UDP packet reception via Ethernet
* Real-time motor updates
* Direction + PWM motor control
* Digital control for vertical thrusters
* Gripper output control
* **Failsafe system**:

  * Stops all motors if no packet is received within 1000 ms

---

## Packet Structure

The system uses a fixed 12-byte UDP packet:

```
[ PWM values (6 bytes) | Direction values (6 bytes) ]
```

### Breakdown:

| Index | Description                   |
| ----- | ----------------------------- |
| 0–3   | Main motor speeds             |
| 4–5   | UP motors (binary/full speed) |
| 6–9   | Main motor directions         |
| 10    | UP motor direction            |
| 11    | Gripper state                 |

* PWM range: `0–255`
* Direction:

  * `1` = Forward
  * `0` = Reverse

---

## Hardware Requirements

### Controller Side

* PC/Laptop
* USB Game Controller (Xbox/PS compatible)

### ROV Side

* Arduino (Uno or similar)
* Ethernet Shield (W5100/W5500)
* Motor Drivers (H-Bridge)
* 4 Horizontal Thrusters
* 2 Vertical Thrusters
* Gripper mechanism

---

## Pin Configuration (Arduino)

| Motor | IN1 / PWM | IN2 / DIR |
| ----- | --------- | --------- |
| TL    | 2         | 3         |
| TR    | 4         | 5         |
| BR    | 6         | 7         |
| BL    | 8         | 9         |
| UP1   | 12        | 13        |
| UP2   | A5        | A3        |

Gripper:

```
Pin 0 (Digital Output)
```

---

## Setup Instructions

### 1. Arduino Setup

1. Install required libraries:

   * `SPI`
   * `Ethernet`
   * `EthernetUdp`
2. Upload the Arduino code
3. Ensure IP configuration matches:

   ```
   IP Address: 192.168.1.50
   Port: 9090
   ```

---

### 2. Python Setup

#### Install dependencies:

```bash
pip install pygame
```

#### Run the script:

```bash
python controller.py
```

---

## Controls Mapping

| Control        | Function            |
| -------------- | ------------------- |
| Left Stick X/Y | Horizontal movement |
| Right Stick X  | Rotation (Yaw)      |
| Right Stick Y  | Vertical movement   |
| Button A (0)   | Arm (Full Power)    |
| Button B (1)   | Precision Mode      |
| LB (4)         | Open Gripper        |
| RB (5)         | Close Gripper       |

---

## Safety Features

* **Startup Neutralization**

  * Clears invalid joystick readings at launch
* **Deadzone Filtering**

  * Prevents drift from minor stick noise
* **Failsafe Timeout**

  * Stops all motors if connection is lost
* **Manual Arming**

  * Motors remain inactive until user input

---

## Troubleshooting

### No Joystick Detected

* Ensure controller is connected before running script
* Check:

  ```python
  pygame.joystick.get_count()
  ```

### Network Issues

* Verify:

  * Same subnet (e.g., 192.168.1.x)
  * Correct IP and port
* Check Ethernet cable / router

### Motors Not Responding

* Confirm wiring matches pin configuration
* Verify motor driver power supply
* Ensure PWM-compatible pins are used

---

## Future Improvements

* PID stabilization for smoother control
* Depth sensor integration
* Camera streaming over network
* ROS (Robot Operating System) integration
* GUI control interface

---

## License

This project is open-source and free to use for educational and research purposes.

---

## Author

Developed as part of an ROV control system project.
