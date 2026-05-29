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
import web_server
import sweat_sensor_reader
import csv
import os
import json
import collections
from datetime import datetime
import adafruit_ahtx0
import queue
import email_notifier
try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False
    print("[ML] Warning: joblib not installed. Actuation mode will be unavailable.")
# --- GLOBAL STATE ---
current_speed_kph = 0.0
current_battery_voltage_v = 0.0
current_motor_amps_a = 0.0
current_motor_power_w = 0.0
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

        # Clamp voltage to safe limits (0 to DAC VDD)
        # Note: MCP4725 output is relative to its VDD
        # 12-bit DAC: 0-4095
        # Value = (Voltage / VDD) * 4095
        
        voltage = max(0.0, min(config.DAC_VDD_V, voltage))
        raw_value = int((voltage / config.DAC_VDD_V) * 4095)
        
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
                # Index [1] = Volts, Index [2] = Amps, Index [3] = Speed
                volts = float(parts[1])
                amps = float(parts[2])
                # Index [1] = Volts, Index [2] = Amps, Index [3] = Speed
                volts = float(parts[1])
                amps = float(parts[2])
                self.speed = float(parts[3])
                
                # Update global states
                global current_speed_kph, current_battery_voltage_v, current_motor_amps_a, current_motor_power_w
                current_speed_kph = self.speed
                current_battery_voltage_v = volts
                current_motor_amps_a = amps
                current_motor_power_w = volts * amps
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

class HDropManager(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        self.running = True
        self.current_fluid_l = None
        self.current_sweat_rate_l_hr = None
        self.current_skin_temp_c = None
        self.history = []  # List of tuples (timestamp, fluid_l)
        self.consecutive_errors = 0
        self.is_cached = False
        self.frozen_counter = 0
        self.last_frozen_val = None
        
    def run(self):
        print("Initializing HDrop reader (Bluetooth / Android)...")
        if not sweat_sensor_reader.init_hdrop():
            print("Warning: HDrop reader failed to initialize. Values will remain None")
            
        while self.running:
            try:
                metrics = sweat_sensor_reader.read_hdrop()
                val = metrics.get("fluid")
                
                if metrics.get("temp") is not None:
                    self.current_skin_temp_c = metrics.get("temp")
                
                if val is not None:
                    self.is_cached = False
                    self.consecutive_errors = 0
                    self.current_fluid_l = val
                    now = time.time()

                    # Prefer the native sweat rate from the HDrop app if available,
                    # otherwise fall back to the Pi's own mathematical calculation.
                    native_sweat_rate = metrics.get("sweat_rate")
                    if native_sweat_rate is not None:
                        self.current_sweat_rate_l_hr = native_sweat_rate
                    else:
                        # --- DISCRETE MATHEMATICAL SWEAT RATE FALLBACK ---
                        if not hasattr(self, 'last_discrete_val'):
                            self.last_discrete_val = val
                            self.last_discrete_time = now
                            self.current_sweat_rate_l_hr = 0.0
                            email_notifier.fire_alert("🚴 Pi hDrop Online!", f"The Raspberry Pi is successfully reading from the hDrop Android app!\n\nStarting Fluid Loss: {val}L\nSkin Temp: {self.current_skin_temp_c}°C\nSweat Rate: {self.current_sweat_rate_l_hr}L/h")

                        # Only update the Sweat Rate mathematically if the physical Fluid Loss leaps up!
                        if val > self.last_discrete_val:
                            time_diff_hrs = (now - self.last_discrete_time) / 3600.0
                            if time_diff_hrs > 0:
                                self.current_sweat_rate_l_hr = (val - self.last_discrete_val) / time_diff_hrs
                            
                            # Fire an email alert!
                            email_notifier.fire_alert(f"💧 hDrop Update: {val}L", f"Your fluid loss physically leaped up!\n\nNew Fluid: {val}L\nCalculated Sweat Rate: {self.current_sweat_rate_l_hr:.2f}L/h\nSkin Temp: {self.current_skin_temp_c}°C")
                            
                            # Lock the new anchor point for the next leap
                            self.last_discrete_val = val
                            self.last_discrete_time = now
                        
                        # Cooldown detection: If 15 minutes pass with absolutely ZERO sweat, zero out the rate
                        elif (now - self.last_discrete_time) > 900.0:
                            self.current_sweat_rate_l_hr = 0.0

                    # --- FROZEN ANDROID UI DETECTOR ---
                    # If the Android OS Accessibility Service silently crashes, the physical screen will update
                    # but the background XML Engine will hand us the exact same number infinitely without throwing an error!
                    # If we receive the EXACT SAME NUMBER for 20 straight readings (5 minutes of riding),
                    # we mathematically assume the phone's engine froze and violently reboot it!
                    # Skip the check for 0.0 (the "--" placeholder at ride start) to avoid spurious reboots.
                    if val != 0.0:
                        if self.last_frozen_val == val:
                            self.frozen_counter += 1
                        else:
                            self.frozen_counter = 0
                            self.last_frozen_val = val

                        if self.frozen_counter >= 20: # 5 minutes
                            print("\n[HDrop] WARNING: Android Accessibility Service has likely silently frozen!")
                            print("[HDrop] Commencing violent forced reset of Android USB ATX servers...")
                            sweat_sensor_reader.init_hdrop()
                            self.frozen_counter = 0  # Reset so it doesn't instantly crash again

                else:
                    self.consecutive_errors += 1
                    self.is_cached = True
                    # If we miss 4 readings (60 seconds), nullify the data so ML doesn't learn fake zeros
                    if self.consecutive_errors >= 4:
                        self.current_fluid_l = None
                        self.current_sweat_rate_l_hr = None
                        self.current_skin_temp_c = None

                    # If we miss 8 readings (120 seconds), aggressively try to reboot the USB/ADB connection
                    if self.consecutive_errors >= 8:
                        print("[HDrop] Connection lost! Attempting aggressive reboot...")
                        hdrop_reader.init_hdrop()
                        self.consecutive_errors = 0 # Reset so it doesn't span-reboot every 15s
                        
            except Exception as e:
                self.consecutive_errors += 1
                self.is_cached = True
                
            time.sleep(15) # Poll every 15 seconds

class CloudSyncManager(threading.Thread):
    def __init__(self, upload_queue):
        threading.Thread.__init__(self)
        self.daemon = True
        self.running = True
        self.queue = upload_queue
        self.supabase = None
        try:
            from supabase import create_client
            if hasattr(config, 'SUPABASE_URL') and hasattr(config, 'SUPABASE_KEY'):
                self.supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
                print("[CloudSync] Connected to Supabase API!")
        except Exception as e:
            print(f"[CloudSync] Init Warning: Supabase missing or misconfigured: {e}")
            
    def run(self):
        while self.running:
            try:
                # Each queue item is a (table_name, row_dict) tuple
                table_name, item = self.queue.get(timeout=3.0)
                batch = [item]

                # Drain any additional rows for the same table for bulk efficiency
                while not self.queue.empty() and len(batch) < 10:
                    next_table, next_item = self.queue.get_nowait()
                    if next_table == table_name:
                        batch.append(next_item)
                    else:
                        # Different table — upload current batch first, then re-queue
                        if self.supabase is not None:
                            self.supabase.table(table_name).insert(batch).execute()
                        batch = [next_item]
                        table_name = next_table

                if self.supabase is not None and len(batch) > 0:
                    self.supabase.table(table_name).insert(batch).execute()

            except queue.Empty:
                pass
            except Exception as e:
                print(f"[Supabase Upload Error] {e} — re-queuing {len(batch)} rows")
                try:
                    for row in batch:
                        self.queue.put((table_name, row))
                    time.sleep(5)
                except Exception:
                    pass

class SweatPredictor:
    """
    Loads the trained Random Forest and model_config.json from machine_learning/.
    Call reset() at ride start, then update() once per second.
    Returns (triggered, probability) — triggered latches True and stays True.
    """
    def __init__(self):
        self.model        = None
        self.feature_cols = []
        self.threshold    = 0.5
        self._load()

        self.torque_buffer       = collections.deque()
        self.exertion_debt_kj    = 0.0
        self.ride_start_time     = None
        self.last_update_time    = None
        self.consecutive_triggers = 0
        self.triggered           = False

    def _load(self):
        if not JOBLIB_AVAILABLE:
            return
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            model_path  = os.path.join(base, config.ML_MODEL_PATH)
            config_path = os.path.join(base, 'machine_learning', 'sweat_onset_model', 'model_config.json')
            self.model = joblib.load(model_path)
            with open(config_path) as f:
                mc = json.load(f)
            self.feature_cols = mc['feature_cols']
            self.threshold    = mc['deployment_threshold']
            print(f"[ML] Model loaded — threshold: {self.threshold}, features: {self.feature_cols}")
        except Exception as e:
            self.model = None
            print(f"[ML] Could not load model: {e}. Actuation mode disabled.")

    def reset(self):
        self.torque_buffer        = collections.deque()
        self.exertion_debt_kj     = 0.0
        self.ride_start_time      = time.time()
        self.last_update_time     = time.time()
        self.consecutive_triggers = 0
        self.triggered            = False

    def update(self, torque_nm, rpm, temp_c, humidity_pct):
        if self.model is None:
            return False, 0.0

        if self.ride_start_time is None:
            self.reset()

        now = time.time()
        dt  = now - self.last_update_time if self.last_update_time else 1.0
        self.last_update_time = now

        # Exertion debt (cumulative kJ since ride start)
        power_w = torque_nm * rpm * 0.10472
        self.exertion_debt_kj += (power_w * dt) / 1000.0

        # Exertion intensity (kJ/min)
        elapsed_min = (now - self.ride_start_time) / 60.0
        intensity = self.exertion_debt_kj / elapsed_min if elapsed_min > 0 else 0.0

        # Rolling 3-minute torque mean
        self.torque_buffer.append((now, torque_nm))
        cutoff = now - 180.0
        while self.torque_buffer and self.torque_buffer[0][0] < cutoff:
            self.torque_buffer.popleft()
        torque_rolling = sum(v for _, v in self.torque_buffer) / len(self.torque_buffer)

        # Build feature vector in the exact order from model_config.json
        feature_map = {
            'exertion_debt_kj':              self.exertion_debt_kj,
            'exertion_intensity_kj_per_min': intensity,
            'humidity_pct':                  humidity_pct,
            'temp_c':                        temp_c,
            'torque_rolling_3min':           torque_rolling,
        }
        features = [[feature_map[col] for col in self.feature_cols]]

        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            prob = self.model.predict_proba(features)[0][1]

        if not self.triggered:
            if prob >= self.threshold:
                self.consecutive_triggers += 1
            else:
                self.consecutive_triggers = 0

            if self.consecutive_triggers >= config.SWEAT_ONSET_SUSTAINED_SECONDS:
                self.triggered = True

        return self.triggered, prob


def sweat_reduction_ceiling(speed_kph):
    """Speed-dependent voltage ceiling for sweat reduction mode.
    4.5V at standstill, linear taper to 3.5V at 12.5 km/h, flat 3.5V thereafter."""
    if speed_kph < config.COLD_START_CUTOFF_KPH:
        t = speed_kph / config.COLD_START_CUTOFF_KPH
        return config.SWEAT_REDUCTION_MAX_V - t * (config.SWEAT_REDUCTION_MAX_V - config.SWEAT_REDUCTION_CRUISE_V)
    return config.SWEAT_REDUCTION_CRUISE_V


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
        
    try:
        aht_sensor = adafruit_ahtx0.AHTx0(i2c)
        print("AHT25 Temp/Humid Sensor initialized.")
    except Exception as e:
        print(f"AHT25 Init Error: {e}. Temp/Humid will log as 0.0")
        aht_sensor = None
    
    current_temp_c = 0.0
    current_humid_pct = 0.0
    last_aht_read_time = 0
    
    # Initialize Serial Thread
    ca_reader = CycleAnalystReader()
    ca_reader.start()
    
    # Start HDrop Polling Thread
    hdrop_manager = HDropManager()
    hdrop_manager.start()

    # Start Cloud Sync Thread
    cloud_queue = queue.Queue()
    cloud_manager = CloudSyncManager(cloud_queue)
    cloud_manager.start()

    # Start Web Server Thread
    def run_flask():
        web_server.app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Initialise ML predictor (loads model + config once at boot)
    sweat_predictor = SweatPredictor()
    predictor_notified = False  # Tracks whether we've fired the web notification this ride

    csv_file = None
    csv_writer = None
    is_logging = False
    current_ride_id = None
    
    # Initialize GPIO and get polling mode state
    polling_mode = setup_gpio()
    
    # Auto-Calibrate Torque
    torque_sensor.calibrate()
    
    print("System Ready. Entering Control Loop.")
    
    # State for smoothing
    smoothed_torque = 0.0
    torque_history = []

    # Voltage ceiling ramp state — starts at normal ceiling, ramps up when sweat reduction fires
    current_v_ceiling = config.MOTOR_MAX_OUTPUT_V
    
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

            # 2. LIME-BIKE STYLE ASYMMETRIC SMOOTHING (Peak Track & Hold)
            # Lime bikes use a steep attack and a slow, continuous decay to completely eliminate dead-spots.
            # We bypass the 'torque_history' list entirely for this.
            
            if raw_torque > smoothed_torque:
                # Fast response to new effort (Tracks peaks instantly)
                smoothed_torque += (raw_torque - smoothed_torque) * 0.5 
            else:
                # Very slow decay to 'hold' the peak over the dead spots of the pedal stroke
                smoothed_torque += (raw_torque - smoothed_torque) * 0.015
            
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
            
            # MOTOR_TEST mode forces sweat reduction on immediately (no ML required).
            # ACTUATION mode uses the ML trigger latch as normal.
            in_sweat_reduction = (
                (web_server.ride_mode == "ACTUATION" and sweat_predictor.triggered) or
                web_server.ride_mode == "MOTOR_TEST"
            )

            # Voltage ceiling ramp — runs every iteration so the ceiling decays while stopped,
            # preventing a full-power surge when accelerating hard from a traffic light stop.
            # While not pedalling in sweat reduction mode, target drops to cruise ceiling (3.5V)
            # so the ceiling has to ramp back up on restart rather than sitting at 4.5V.
            if in_sweat_reduction:
                if is_pedaling and current_speed_kph >= config.SWEAT_REDUCTION_LAUNCH_KPH:
                    target_ceiling = sweat_reduction_ceiling(current_speed_kph)
                else:
                    target_ceiling = config.SWEAT_REDUCTION_CRUISE_V
            else:
                target_ceiling = config.MOTOR_MAX_OUTPUT_V
            if current_v_ceiling < target_ceiling:
                current_v_ceiling = min(current_v_ceiling + config.SWEAT_REDUCTION_RAMP_RATE_V_PER_S, target_ceiling)
            elif current_v_ceiling > target_ceiling:
                current_v_ceiling = max(current_v_ceiling - config.SWEAT_REDUCTION_RAMP_RATE_V_PER_S, target_ceiling)

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
                v_out_max = current_v_ceiling

                # Final Voltage
                target_voltage = v_out_min + (assist_factor * (v_out_max - v_out_min))
                
            else:
                # Immediate safety cutoff drops below motor kick-in threshold
                target_voltage = config.MOTOR_IDLE_OUTPUT_V
            
            # 4. OUTPUT
            motor.set_output(target_voltage)
            
            # --- Slow Sensor Polling (Every 10s) ---
            if aht_sensor is not None and (time.time() - last_aht_read_time) > 10.0:
                try:
                    current_temp_c = aht_sensor.temperature
                    current_humid_pct = aht_sensor.relative_humidity
                except Exception:
                    pass # Ignore random I2C dropouts from electrical noise
                last_aht_read_time = time.time()
            
            # Debug Stats, ML Inference & CSV Logging (Every ~1s)
            if (getattr(main, "counter", 0)) % 20 == 0:

                # --- ML INFERENCE (actuation rides only) ---
                ml_probability = 0.0
                if web_server.ride_active and web_server.ride_mode == "ACTUATION":
                    _, ml_probability = sweat_predictor.update(
                        smoothed_torque, current_cadence_rpm, current_temp_c, current_humid_pct
                    )
                    # Notify web server once on first confirmed trigger
                    if sweat_predictor.triggered and not predictor_notified:
                        web_server.sweat_reduction_active = True
                        web_server.sweat_triggered_at = datetime.now().isoformat()
                        predictor_notified = True
                        print(f"\n[ML] *** SWEAT ONSET CONFIRMED — switching to sweat reduction mode ***")

                current_power_band = "HIGH" if in_sweat_reduction else "LOW"

                cache_flag = "*" if hdrop_manager.is_cached else ""
                fluid_display = f"{hdrop_manager.current_fluid_l:.3f}L{cache_flag}" if hdrop_manager.current_fluid_l is not None else "None"
                rate_display = f"{hdrop_manager.current_sweat_rate_l_hr:.3f}L/h{cache_flag}" if hdrop_manager.current_sweat_rate_l_hr is not None else "None"
                skin_display = f"{hdrop_manager.current_skin_temp_c:.1f}°C" if hdrop_manager.current_skin_temp_c is not None else "None"
                if web_server.ride_mode == "MOTOR_TEST":
                    ml_display = "forced"
                elif web_server.ride_mode == "ACTUATION":
                    ml_display = f"{ml_probability:.2f}"
                else:
                    ml_display = "off"
                print(f"RPM: {current_cadence_rpm:.1f} | Spd: {current_speed_kph:.1f} | Trq: {smoothed_torque:.1f} | V_Out: {target_voltage:.2f} | Band: {current_power_band} | ML: {ml_display} | Fluid: {fluid_display} | Rate: {rate_display} | Skin: {skin_display}", flush=True)

                # --- CSV LOGGING LOGIC ---
                if web_server.ride_active and not is_logging:
                    if not os.path.exists("ride_logs"):
                        os.makedirs("ride_logs")

                    current_ride_id = "RIDE_" + datetime.now().strftime('%Y%m%d_%H%M%S')
                    web_server.last_ride_id = current_ride_id

                    # Reset ML predictor state for the new ride
                    sweat_predictor.reset()
                    predictor_notified = False

                    filename = f"ride_logs/{current_ride_id}.csv"
                    csv_file = open(filename, 'w', newline='')
                    csv_writer = csv.writer(csv_file)
                    csv_writer.writerow([
                        "ride_id", "timestamp", "rpm", "speed_kph", "torque_nm",
                        "voltage_out", "battery_voltage_v", "motor_current_a", "motor_power_w",
                        "power_band", "temp_c", "humidity_pct", "fluid_loss_l",
                        "sweat_rate_l_hr", "skin_temp_c",
                        "ml_sweat_probability", "sweat_reduction_active"
                    ])
                    is_logging = True
                    print(f"\n[IoT] STARTED RECORDING {current_ride_id} — mode: {web_server.ride_mode}")

                elif not web_server.ride_active and is_logging:
                    if csv_file:
                        csv_file.close()
                    is_logging = False
                    current_ride_id = None
                    print("\n[IoT] STOPPED RECORDING AND SAVED CSV")

                if is_logging and csv_writer:
                    row_data = {
                        "ride_id": current_ride_id,
                        "timestamp": datetime.now().isoformat(),
                        "rpm": round(current_cadence_rpm, 1),
                        "speed_kph": round(current_speed_kph, 1),
                        "torque_nm": round(smoothed_torque, 1),
                        "voltage_out": round(target_voltage, 2),
                        "battery_voltage_v": round(current_battery_voltage_v, 2),
                        "motor_current_a": round(current_motor_amps_a, 2),
                        "motor_power_w": round(current_motor_power_w, 2),
                        "power_band": current_power_band,
                        "temp_c": round(current_temp_c, 2),
                        "humidity_pct": round(current_humid_pct, 2),
                        "fluid_loss_l": round(hdrop_manager.current_fluid_l, 4) if hdrop_manager.current_fluid_l is not None else None,
                        "sweat_rate_l_hr": round(hdrop_manager.current_sweat_rate_l_hr, 4) if hdrop_manager.current_sweat_rate_l_hr is not None else None,
                        "skin_temp_c": round(hdrop_manager.current_skin_temp_c, 2) if hdrop_manager.current_skin_temp_c is not None else None,
                        "ml_sweat_probability": round(ml_probability, 4),
                        "sweat_reduction_active": in_sweat_reduction,
                    }

                    csv_writer.writerow([
                        row_data["ride_id"], row_data["timestamp"], row_data["rpm"],
                        row_data["speed_kph"], row_data["torque_nm"], row_data["voltage_out"],
                        row_data["battery_voltage_v"], row_data["motor_current_a"], row_data["motor_power_w"],
                        row_data["power_band"], row_data["temp_c"], row_data["humidity_pct"],
                        row_data["fluid_loss_l"], row_data["sweat_rate_l_hr"], row_data["skin_temp_c"],
                        row_data["ml_sweat_probability"], row_data["sweat_reduction_active"],
                    ])
                    csv_file.flush()

                    # Route to correct Supabase table based on ride mode
                    supabase_table = "actuation_ride_metrics_v1" if web_server.ride_mode in ("ACTUATION", "MOTOR_TEST") else "ride_metrics_v2"
                    cloud_queue.put((supabase_table, row_data))
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
    try:
        # Dynamically calculate the Pi's active Wi-Fi / Hotspot IP Address
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        current_ip = s.getsockname()[0]
        s.close()
        
        # Fire the autonomous email alert!
        import email_notifier
        email_notifier.fire_alert(
            "🚀 Pi Dashboard is Live!", 
            f"Your E-Bike computer just booted successfully!\n\nOpen Safari/Chrome on your phone and tap this exact link to start your ride:\nhttp://{current_ip}:5000\n\n(Note: If on the road, ensure your phone's hotspot is on!)"
        )
    except Exception as e:
        print(f"Failed to auto-email boot IP: {e}")
        
    main()
