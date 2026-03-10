#!/usr/bin/env python3
import time
import board
import busio
import RPi.GPIO as GPIO
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn

try:
    import config
except ImportError:
    print("Error: config.py not found. Please ensure it exists.")
    exit(1)

# Globals for cadence tracking
pulse_count = 0
direction = "Unknown"
last_pulse_time = 0.0
current_rpm = 0.0

def cadence_callback(channel):
    global pulse_count, direction, last_pulse_time, current_rpm
    
    current_time = time.time()
    
    # Calculate RPM
    # We only calculate if we have a valid last_pulse_time and ignore ultra-fast noise (< 0.01s)
    if last_pulse_time > 0:
        dt = current_time - last_pulse_time
        if dt > 0.01 and dt < 2.0: 
            # RPM = (pulses per rev) in 1 minute
            current_rpm = (1.0 / config.CADENCE_PULSES_PER_REV) * (60.0 / dt)
            
    last_pulse_time = current_time
    
    # Read state of Phase B to determine direction
    level_b = GPIO.input(config.GPIO_CADENCE_B)
    
    # Inverted direction logic for physical mounting quirks
    if level_b == GPIO.HIGH:
        direction = "Forward"
        pulse_count += 1
    else:
        direction = "Backward"
        pulse_count -= 1

def main():
    global current_rpm
    print("--- SENSOR DIAGNOSTICS SCRIPT ---")
    
    # 1. Initialize I2C and ADC (Torque Sensor)
    try:
        i2c = board.I2C() 
    except Exception:
        try:
             i2c = busio.I2C(board.SCL, board.SDA)
        except Exception as e:
             print(f"Critical: Cannot initialize I2C: {e}")
             return

    try:
        ads = ADS.ADS1115(i2c, address=config.ADS1115_ADDRESS)
        
        # We assume A0 (P0) based on your configuration. 
        # In newer versions of the Adafruit library, passing the integer channel directly is supported or required.
        pin = getattr(ADS, f"P{config.TORQUE_SENSOR_CHANNEL}", config.TORQUE_SENSOR_CHANNEL)
        chan = AnalogIn(ads, pin)
            
        print(f"Torque Sensor (ADS1115) found at address {hex(config.ADS1115_ADDRESS)}.")
    except Exception as e:
        print(f"Failed to connect to torque sensor ADC: {e}")
        return

    # 2. Initialize GPIO (Cadence Sensor)
    polling_mode = False
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(config.GPIO_CADENCE_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(config.GPIO_CADENCE_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        
        try:
            GPIO.add_event_detect(config.GPIO_CADENCE_A, GPIO.RISING, callback=cadence_callback, bouncetime=10)
            print(f"Cadence sensors initialized on pins D{config.GPIO_CADENCE_A} and D{config.GPIO_CADENCE_B} (Interrupt Mode).")
        except RuntimeError as e:
            print(f"Hardware interrupt failed ({e}). Falling back to Polling Mode.")
            polling_mode = True
            
    except Exception as e:
        print(f"Failed to initialize GPIO for cadence sensor: {e}")
        return

    print("\nReading sensors... (Press Ctrl+C to stop)")
    print("1. Apply weight to the pedals to see the Torque Voltage change.")
    print("2. Spin the pedals to see the Cadence Pulses and Direction change.")
    print("-" * 60)
    
    try:
        last_state_a = GPIO.input(config.GPIO_CADENCE_A)
        while True:
            # Polling fallback logic if interrupts failed
            if polling_mode:
                current_state_a = GPIO.input(config.GPIO_CADENCE_A)
                if current_state_a == GPIO.HIGH and last_state_a == GPIO.LOW:
                    # Manually trigger callback on rising edge
                    cadence_callback(config.GPIO_CADENCE_A)
                last_state_a = current_state_a

            # If we haven't received a pulse in 2 seconds, we've stopped pedaling
            if time.time() - last_pulse_time > 2.0:
                current_rpm = 0.0

            # Read real-time voltage from the torque sensor
            torque_volts = chan.voltage
            
            # Print state to screen, clearing the line each time for a clean output
            print(f"\rTorque: {torque_volts:.3f} V  |  Pulses: {pulse_count:5}  |  RPM: {current_rpm:5.1f}  |  Dir: {direction:8}", end="")
            
            # Shorter sleep if we are polling so we don't miss quick pulses
            time.sleep(0.01 if polling_mode else 0.1)
            
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()
        print("\n\nTest finished. GPIO cleaned up.")

if __name__ == "__main__":
    main()
