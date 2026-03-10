# CONFIGURATION FILE FOR E-BIKE CONTROLLER

import board

# --- HARDWARE I/O ---
I2C_SDA = board.SDA
I2C_SCL = board.SCL

# ADC (Torque Sensor)
ADS1115_ADDRESS = 0x48
TORQUE_SENSOR_CHANNEL = 0  # A0
TORQUE_ZERO_POINT_VOLTAGE = 2.5  # 0 Nm = 2.5V as per graph
TORQUE_SENSITIVITY = 0.010       # 10mV/Nm (calculated from 4.5V-0.5V over 400Nm range)

# DAC (Motor Controller)
MCP4725_ADDRESS = 0x62
MOTOR_IDLE_OUTPUT_V = 1.0     # 1.0V = Idle/Zero-assist baseline without triggering motor fault
MOTOR_MIN_ASSIST_V = 1.5      # 1.5V = Physical kick-in voltage (Minimum throttle)
MOTOR_MAX_OUTPUT_V = 3.3      # 3.3V = Maximum throttle (maxed out based on 3.3v rail)

# GPIO (Cadence Sensor)
# Using RPi.GPIO numbers (BCM mode)
GPIO_CADENCE_A = 20  # Labeled D20 on the Qwiic PiHat
GPIO_CADENCE_B = 21  # Labeled D21 on the Qwiic PiHat
CADENCE_PULSES_PER_REV = 8  # 16-magnet bottom brackets output 8 full High/Low cycles (8 rising edges) per revolution.

# GPIO (Brakes)
# Mechanical brake cutoff switches (normally open, close to ground when pulled)
GPIO_BRAKE_L = 16  # Labeled D16 on the Qwiic PiHat
GPIO_BRAKE_R = 12  # Labeled D12 on the Qwiic PiHat

# Serial (Cycle Analyst)
# On Pi Zero 2 W, the primary UART is typically /dev/serial0
SERIAL_PORT = '/dev/serial0'
SERIAL_BAUD = 9600

# --- CONTROL PARAMETERS ---
# Smoothing Factors (0.0 to 1.0)
SMOOTH_RISE_SPEED = 0.2     # Fast response to pedal push
SMOOTH_FALL_SPEED = 0.01    # Slow decay to bridge pedal gaps

# Safety Thresholds
MIN_TORQUE_NM = 5.0         # Minimum torque to engage motor
MIN_CADENCE_RPM = 10.0      # Minimum cadence to engage motor
MAX_SPEED_KPH = 25.0        # Legal speed limit for assist

# Assist Logic
ASSIST_LEVEL_FACTOR = 1.0   # Multiplier for assist strength (Tune as needed)
MAX_TORQUE_INPUT_NM = 60.0  # Cap input torque for calculations
