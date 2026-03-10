#!/usr/bin/env python3
import time
import busio
import board
import serial
import RPi.GPIO as GPIO
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import adafruit_mcp4725

# Import configuration
try:
    import config
except ImportError:
    print("Error: config.py not found. Please ensure it exists in the same directory.")
    exit(1)

import threading

# --- GLOBAL STATE ---
current_speed_kph = 0.0
last_cadence_time = 0
cadence_pulse_count = 0
current_cadence_rpm = 0.0

# --- CLASSES ---

class TorqueSensor:
    def __init__(self, i2c):
        self.ads = ADS.ADS1115(i2c)
        # Detailed configuration for ADS1115
        # The prompt says 0.5-4.5V range.
        # ADS1115 default gain is 2/3 (+/- 6.144V), which covers 0-5V nicely.
        pin = getattr(ADS, f"P{config.TORQUE_SENSOR_CHANNEL}", config.TORQUE_SENSOR_CHANNEL)
        self.chan = AnalogIn(self.ads, pin)
        self.zero_offset_v = config.TORQUE_ZERO_POINT_VOLTAGE
        self.smoothed_torque = 0.0

    def calibrate(self):
        print("Calibrating Torque Sensor (Keep pedals still)...")
        readings = []
        start_time = time.time()
        # Average 50 readings over ~1 second
        count = 0
        while count < 50 and (time.time() - start_time) < 1.5:
             readings.append(self.chan.voltage)
             time.sleep(0.02)
             count += 1
        
        if readings:
            self.zero_offset_v = sum(readings) / len(readings)
            print(f"Torque Calibration Complete. Zero Point: {self.zero_offset_v:.3f} V")
        else:
            print("Torque Calibration Failed (No readings). Using default.")

    def get_torque_nm(self):
        # Read raw voltage
        raw_v = self.chan.voltage
        
        # Calculate offset from zero point and use absolute difference
        delta_v = abs(raw_v - self.zero_offset_v)
        
        # Hardware noise deadband filtering
        # The sensor voltage natively fluctuates by ~0.03V randomly. 
        # This prevents it from thinking there is 5Nm of torque when resting.
        if delta_v < 0.05:
            delta_v = 0.0
            
        # Convert to Nm
        torque_nm = delta_v / config.TORQUE_SENSITIVITY
        return torque_nm

class MotorController:
    def __init__(self, i2c):
        try:
            self.dac = adafruit_mcp4725.MCP4725(i2c, address=config.MCP4725_ADDRESS)
            self.connected = True
        except Exception as e:
            print(f"Warning: MCP4725 DAC not found: {e}")
            self.connected = False

    def set_output(self, voltage):
        if not self.connected:
            return

        # Clamp voltage to safe limits (0 to 3.3V)
        # Note: MCP4725 output is relative to its VDD (3.3V)
        # 12-bit DAC: 0-4095
        # Value = (Voltage / 3.3) * 4096
        
        voltage = max(0.0, min(3.3, voltage))
        raw_value = int((voltage / 3.3) * 4095)
        
        # Set the DAC
        try:
            self.dac.raw_value = raw_value
        except OSError:
            pass # Handle I2C errors silently to avoid crashing loop

class CycleAnalystReader(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.running = True
        self.speed = 0.0
        
    def run(self):
        try:
            ser = serial.Serial(config.SERIAL_PORT, config.SERIAL_BAUD, timeout=1)
            print(f"Listening to Cycle Analyst on {config.SERIAL_PORT}...")
            
            while self.running:
                if ser.in_waiting:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    self.parse_line(line)
                else:
                    time.sleep(0.1)
        except serial.SerialException as e:
            print(f"Serial Error: {e}")
        except Exception as e:
            print(f"Error in Cycle Analyst thread: {e}")

    def parse_line(self, line):
        # CA V3 Format: [Ah V A Speed Distance Temp RPM HW Nm ThI ThO AuxA AuxD Flags]
        # Tab separated
        parts = line.split('\t')
        if len(parts) > 3:
            try:
                # Speed is index 3
                self.speed = float(parts[3])
                
                # Update global speed
                global current_speed_kph
                current_speed_kph = self.speed
            except ValueError:
                pass


# --- GPIO INTERRUPTS FOR CADENCE ---
cadence_pulse_count = 0
direction_forward = True
polling_active = True

def cadence_pulse_callback(channel):
    global last_cadence_time, cadence_pulse_count, direction_forward, current_cadence_rpm
    
    current_time = time.time()
    dt = current_time - last_cadence_time
    
    # Hardware debounce (ignore pulses faster than ~150 RPM -> < 0.015s)
    if dt < 0.015: 
        return
        
    # Calculate Instantaneous RPM
    if last_cadence_time > 0 and dt < 2.0:
        current_cadence_rpm = (1.0 / config.CADENCE_PULSES_PER_REV) * (60.0 / dt)
    
    last_cadence_time = current_time
    
    # Direction Detection Logic (Standard Quadrature)
    # Trigger is RISING edge of Channel A.
    # If Channel B is LOW, we are moving Forward (assuming standard layout).
    # If Channel B is HIGH, we are moving Backward.
    # Note: Actual Low/High dependency varies by sensor wiring.
    # Assuming Forward = B is LOW (Common).
    
    level_b = GPIO.input(config.GPIO_CADENCE_B)
    
    if level_b == GPIO.HIGH:
        direction_forward = True
        cadence_pulse_count += 1
    else:
        direction_forward = False
        # Do not count backward pulses for assist RPM
        # Or count them as negative if we wanted net movement.
        # User requested "absolute value for forward-only".
        # If absolute value is forward only, we ignore backward?
        # Let's assume we only assist on Forward.
        pass

def cadence_polling_loop():
    global polling_active
    last_state_a = GPIO.input(config.GPIO_CADENCE_A)
    while polling_active:
        current_state_a = GPIO.input(config.GPIO_CADENCE_A)
        # Trigger exactly on the rising edge
        if current_state_a == GPIO.HIGH and last_state_a == GPIO.LOW:
            cadence_pulse_callback(config.GPIO_CADENCE_A)
        last_state_a = current_state_a
        time.sleep(0.002) # 2ms high-speed polling

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    
    # Cadence sensors
    GPIO.setup(config.GPIO_CADENCE_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(config.GPIO_CADENCE_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    # Brake cutoff switches (Normally high via pull-up, Low when pulled)
    GPIO.setup(config.GPIO_BRAKE_L, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(config.GPIO_BRAKE_R, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    try:
        # Add interrupt on rising edge of Channel A
        GPIO.add_event_detect(config.GPIO_CADENCE_A, GPIO.RISING, callback=cadence_pulse_callback)
        print("GPIO Interrupts enabled.")
        return False # Not in polling mode
    except RuntimeError as e:
        print(f"Hardware interrupt failed ({e}). Falling back to High-Speed Polling Thread.")
        try:
            t = threading.Thread(target=cadence_polling_loop, daemon=True)
            t.start()
        except Exception as e2:
            print(f"Failed to start high-speed thread: {e2}")
        return True # In polling mode


# --- MAIN CONTROL LOOP ---

def main():
    print("Starting E-Bike Motor Controller...")
    
    # Initialize I2C
    try:
        i2c = board.I2C() 
        # On Pi, this usually detects hardware I2C
    except Exception as e:
        print(f"I2C Init Failed (board.I2C): {e}")
        try:
             import busio
             i2c = busio.I2C(board.SCL, board.SDA)
             print("Initialized I2C using busio.")
        except Exception as e2:
             print(f"Critical: Cannot initialize I2C: {e2}")
             return

    # Initialize Devices
    try:
        torque_sensor = TorqueSensor(i2c)
        motor = MotorController(i2c)
    except ValueError as e:
        print(f"Device Init Error: {e}")
        return
    
    # Initialize Serial Thread
    ca_reader = CycleAnalystReader()
    ca_reader.start()
    
    # Initialize GPIO and get polling mode state
    polling_mode = setup_gpio()
    
    # Auto-Calibrate Torque
    torque_sensor.calibrate()
    
    print("System Ready. Entering Control Loop.")
    
    # State for smoothing
    smoothed_torque = 0.0
    
    # Loop Logic
    loop_interval = 0.05 # 50ms loop
    rpm_calc_interval = 0.25 # 250ms for RPM
    last_rpm_calc_time = time.time()
    
    global cadence_pulse_count, current_cadence_rpm
    
    try:
        while True:
            cycle_start = time.time()
            
            # 1. READ SENSORS
            raw_torque = torque_sensor.get_torque_nm()
            
            # Dynamic cadence timeout: calculate expected time between pulses based on current RPM.
            if current_cadence_rpm > 0.1:
                # time per pulse at current RPM
                expected_pulse_interval = (60.0 / current_cadence_rpm) / config.CADENCE_PULSES_PER_REV
                # allow 60% margin for natural pedaling speed variations (1.6x multiplier)
                # cap between 0.25s (fastest reliable cutoff) and 1.5s (absolute max)
                timeout_threshold = expected_pulse_interval * 1.6
                timeout_threshold = max(0.25, min(1.5, timeout_threshold))
            else:
                timeout_threshold = 1.5
                
            # If no pulses for > timeout_threshold, force 0 RPM immediately
            if (time.time() - last_cadence_time) > timeout_threshold:
                current_cadence_rpm = 0.0

            # 2. APPLY SMOOTHING (Asymmetric)
            if raw_torque > smoothed_torque:
                smoothed_torque += (raw_torque - smoothed_torque) * config.SMOOTH_RISE_SPEED
            else:
                smoothed_torque += (raw_torque - smoothed_torque) * config.SMOOTH_FALL_SPEED
            
            # Ensure torque doesn't drift negative
            smoothed_torque = max(0.0, smoothed_torque)

            # 3. CONTROL LOGIC
            target_voltage = config.MOTOR_IDLE_OUTPUT_V # Default to Idle/Off
            
            # Conditions
            # A. Torque > Threshold (5 Nm)
            # B. Cadence > Threshold (10 RPM)
            # C. Speed < Limit (25 km/h)
            # D. Forward pedaling direction
            # E. Brakes are NOT applied (High = ok, Low = Pulled)
            
            is_pedaling = current_cadence_rpm > config.MIN_CADENCE_RPM
            is_torque_active = smoothed_torque > config.MIN_TORQUE_NM
            is_speed_safe = current_speed_kph < config.MAX_SPEED_KPH
            
            brakes_applied = (GPIO.input(config.GPIO_BRAKE_L) == GPIO.LOW) or (GPIO.input(config.GPIO_BRAKE_R) == GPIO.LOW)
            
            if is_pedaling and is_torque_active and is_speed_safe and direction_forward and not brakes_applied:
                # Calculate Assist Level (0.0 to 1.0)
                
                # Map Smoothed Torque (5 - 60 Nm)
                torque_floor = config.MIN_TORQUE_NM
                torque_ceiling = config.MAX_TORQUE_INPUT_NM
                
                # Normalize to an assist factor between 0.0 and 1.0
                assist_factor = (smoothed_torque - torque_floor) / (torque_ceiling - torque_floor)
                assist_factor = max(0.0, min(1.0, assist_factor))
                
                # Apply Global tuning multiplier (if user wants to scale down help)
                assist_factor = assist_factor * config.ASSIST_LEVEL_FACTOR
                assist_factor = max(0.0, min(1.0, assist_factor))
                
                # Apply to Voltage Range
                # Note: We map 0% assist to MOTOR_MIN_ASSIST_V (1.5V) so the motor responds instantly!
                v_out_min = config.MOTOR_MIN_ASSIST_V
                v_out_max = config.MOTOR_MAX_OUTPUT_V
                
                # Final Voltage
                target_voltage = v_out_min + (assist_factor * (v_out_max - v_out_min))
                
            else:
                # Immediate safety cutoff drops below motor kick-in threshold
                target_voltage = config.MOTOR_IDLE_OUTPUT_V
            
            # 4. OUTPUT
            motor.set_output(target_voltage)
            
            # Debug Stats (Every ~1s)
            # Using a counter
            if (getattr(main, "counter", 0)) % 20 == 0:
                print(f"RPM: {current_cadence_rpm:.1f} | Spd: {current_speed_kph:.1f} | Trq: {smoothed_torque:.1f} | V_Out: {target_voltage:.2f}", flush=True)
            setattr(main, "counter", getattr(main, "counter", 0) + 1)

            # Loop Sleep
            elapsed = time.time() - cycle_start
            if elapsed < loop_interval:
                time.sleep(loop_interval - elapsed)

    except KeyboardInterrupt:
        print("\nStopping...")
        global polling_active
        polling_active = False
        motor.set_output(0)
        GPIO.cleanup()
        ca_reader.running = False

if __name__ == "__main__":
    main()
