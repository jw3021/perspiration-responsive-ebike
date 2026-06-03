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
DAC_VDD_V = 4.5               # VIN voltage supplied to the DAC (defines the 4095 max raw value)
MOTOR_IDLE_OUTPUT_V = 1.0     # 1.0V = Idle/Zero-assist baseline without triggering motor fault
MOTOR_MIN_ASSIST_V = 1.5      # 1.5V = Physical kick-in voltage (Minimum throttle)

# --- POWER BANDS (IoT Ready) ---
# Valid options: "LOW", "HIGH"
# LOW  = Normal riding (data collection baseline)
# HIGH = Sweat-triggered maximum assist
CURRENT_POWER_BAND = "LOW"

if CURRENT_POWER_BAND == "LOW":
    MOTOR_MAX_OUTPUT_V = 2.5
else:
    MOTOR_MAX_OUTPUT_V = 4.5

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
SMOOTH_FALL_SPEED = 0.1     # Faster decay so motor cuts quicker when pedaling stops

# Safety Thresholds
MIN_TORQUE_NM = 5.0         # Minimum torque to engage motor
MIN_CADENCE_RPM = 10.0      # Minimum cadence to engage motor
MAX_SPEED_KPH = 25.0        # Legal speed limit for assist

# Assist Logic
ASSIST_LEVEL_FACTOR = 1.0   # Multiplier for assist strength (Tune as needed)
MAX_TORQUE_INPUT_NM = 60.0  # Cap input torque for calculations

# --- ML ACTUATION PARAMETERS ---
ML_MODEL_PATH = "machine_learning/sweat_onset_model/sweat_onset_model.pkl"

# Sweat onset trigger: model must predict sweat continuously for this many
# seconds before actuation fires, preventing single-spike false positives.
SWEAT_ONSET_SUSTAINED_SECONDS = 30

# When sweat reduction mode activates, ramp the voltage ceiling up gradually
# rather than jumping instantly. Units: Volts per second.
# At 0.1 V/s the ceiling takes ~10 s to rise from 2.5V to 3.5V.
SWEAT_REDUCTION_RAMP_RATE_V_PER_S = 0.1

# Probability threshold above which a single reading counts as a sweat prediction
SWEAT_ONSET_PROBABILITY_THRESHOLD = 0.20

# Sweat reduction mode voltage profile (speed-dependent ceiling)
COLD_START_CUTOFF_KPH  = 12.5  # Speed at which cold-start taper ends (midpoint of 0–25 km/h range)
SWEAT_REDUCTION_MAX_V  = 4.5   # Ceiling at standstill (full cold-start assist)
SWEAT_REDUCTION_CRUISE_V = 3.5 # Ceiling above COLD_START_CUTOFF_KPH (sustained elevated assist)
SWEAT_REDUCTION_LAUNCH_KPH = 2.0  # Min speed before cold-start ceiling (>3.5V) is permitted; at standstill there is no back-EMF so the motor draws stall current and trips the CA

# --- IOT CLOUD CONFIGURATION ---
try:
    from credentials import SUPABASE_URL, SUPABASE_KEY
except ImportError:
    raise RuntimeError("secrets.py not found. Copy secrets.example.py to secrets.py and fill in your credentials.")
