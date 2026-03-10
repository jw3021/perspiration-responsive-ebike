# E-Bike Controller Setup Guide

## 1. Hardware Setup (Double Check!)

**Wiring:**

- **I2C**: SDA/SCL from Pi (GPIO 2/3) to ADS1115 and MCP4725.
- **Power**:
  - 5V to Pi
  - 3.3V to MCP4725/ADS1115 (from Pi 3.3V or specialized regulator if needed, but Pi 3.3V is usually fine for logic).
  - **GND**: Must be common between Battery/Controller, Cycle Analyst, and Pi.
- **Torque Sensor**:
  - White -> 16V (from CA)
  - Black -> GND
  - Grey -> ADS1115 A0
  - Blue -> GPIO 23
  - Brown -> GPIO 24

**Cycle Analyst Serial:**

- CA TX -> Voltage Divider (2k/1k) -> Pi RX (GPIO 15).

## 2. Software Installation on Pi

1. **Enable Interfaces:**
   - Run `sudo raspi-config`
   - Interface Options -> Enable I2C, Serial Port (Login Shell: NO, Hardware: YES), SSH.
   - Reboot.

2. **Install Python Libraries:**
   Transfer `requirements.txt` to the Pi and run:
   ```bash
   sudo apt-get update
   sudo apt-get install python3-pip python3-dev
   pip3 install -r requirements.txt
   ```
   _Note: You might need to use a virtual environment if on newer Pi OS (Bookworm)._
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

## 3. Communication over USB ("Physical Wire")

To code on your PC and run on the Pi Zero 2 W via a single USB cable:

1. **Ethernet Gadget Mode**:
   - Add `dtoverlay=dwc2` to `/boot/config.txt`.
   - Add `modules-load=dwc2,g_ether` to `/boot/cmdline.txt` (after `rootwait`).
   - Connect Pi USB (data port, not power) to PC.
   - It should appear as a network adapter.
   - SSH into `pi@raspberrypi.local`.
   - Use VSCode "Remote - SSH" extension to edit files directly on the Pi.

## 4. Running the Controller

**A. Test Hardware:**
Run the diagnostic script to verify connections:

```bash
python3 test_peripherals.py
```

- Verify I2C addresses (0x48, 0x62).
- Rotate cranks to see GPIO changes.
- Apply pressure to torque sensor to see voltage change.

**B. Start Controller:**

```bash
python3 ebike_controller.py
```

- It will calibrate (keep pedals still).
- Output will show RPM, Speed, Torque, and DAC Voltage.

## 5. Troubleshooting

- **I2C Error?** Check wiring. Run `i2cdetect -y 1`.
- **Serial Permission?** Add user to dialout group: `sudo usermod -a -G dialout pi`.
- **Motor Jitters?** Adjust `SMOOTH_RISE_SPEED` in `config.py`.
