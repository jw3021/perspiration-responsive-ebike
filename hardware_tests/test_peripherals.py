#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
import board
import busio
import RPi.GPIO as GPIO
import adafruit_ads1x15.ads1115 as ADS
from adafruit_ads1x15.analog_in import AnalogIn
import adafruit_mcp4725
import adafruit_ahtx0  # Added for Temp/Humid Sensor
import serial

# Import Config for pins
try:
    import config
except ImportError:
    print("Error: config.py not found.")
    exit(1)

def test_i2c():
    print("\n--- Testing I2C Devices ---")
    try:
        i2c = board.I2C()
        # Scan
        while not i2c.try_lock():
            pass
        devices = i2c.scan()
        i2c.unlock()
        print(f"I2C Devices Found: {[hex(x) for x in devices]}")
        
        # Check specific devices
        if config.ADS1115_ADDRESS in devices:
            print(f"PASS: ADS1115 found at {hex(config.ADS1115_ADDRESS)}")
        else:
            print(f"FAIL: ADS1115 not found at {hex(config.ADS1115_ADDRESS)}")
            
        if config.MCP4725_ADDRESS in devices:
            print(f"PASS: MCP4725 found at {hex(config.MCP4725_ADDRESS)}")
        else:
            print(f"FAIL: MCP4725 not found at {hex(config.MCP4725_ADDRESS)}")
            
        # Check for AHT25 (Address is usually 0x38)
        if 0x38 in devices:
            print(f"PASS: AHT25 Sensor found at 0x38")
        else:
            print(f"FAIL: AHT25 Sensor not found at 0x38")
            
        return i2c
    except Exception as e:
        print(f"I2C Test Failed: {e}")
        return None

def test_adc(i2c):
    print("\n--- Testing ADC (Torque Sensor) ---")
    if not i2c: return
    try:
        ads = ADS.ADS1115(i2c)
        chan = AnalogIn(ads, 0)
        print("Reading ADC Channel A0 (Press Ctrl+C to stop)...")
        for _ in range(10):
            print(f"Voltage: {chan.voltage:.4f} V")
            time.sleep(0.5)
    except Exception as e:
        print(f"ADC Test Failed: {e}")

def test_dac(i2c):
    print("\n--- Testing DAC (Motor Output) ---")
    if not i2c: return
    try:
        dac = adafruit_mcp4725.MCP4725(i2c, address=config.MCP4725_ADDRESS)
        print("Ramping DAC Output 0V -> 3.3V...")
        for v in [0.0, 1.0, 2.0, 3.0, 3.3]:
             val = int((v / 3.3) * 4095)
             dac.raw_value = val
             print(f"Set DAC to {v}V (Raw: {val})")
             time.sleep(0.5)
        # Reset to 0
        dac.raw_value = 0
        print("DAC Reset to 0V")
    except Exception as e:
        print(f"DAC Test Failed: {e}")

def test_aht(i2c):
    print("\n--- Testing AHT25 (Temp/Humid) ---")
    if not i2c: return
    try:
        sensor = adafruit_ahtx0.AHTx0(i2c)
        print("Reading Sensor (5 readings)...")
        for _ in range(5):
            print(f"Temp: {sensor.temperature:.2f} C | Humid: {sensor.relative_humidity:.2f} %")
            time.sleep(1)
    except ValueError:
         print("AHT25 not connected (Address 0x38 not found)")
    except Exception as e:
        print(f"AHT Test Failed: {e}")

def test_serial():
    print("\n--- Testing Serial (Cycle Analyst) ---")
    try:
        ser = serial.Serial(config.SERIAL_PORT, config.SERIAL_BAUD, timeout=1)
        print(f"Opened {config.SERIAL_PORT}. Waiting for data (5s)...")
        start = time.time()
        while (time.time() - start) < 5:
            if ser.in_waiting:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                print(f"RX: {line}")
            time.sleep(0.1)
        ser.close()
    except Exception as e:
        print(f"Serial Test Failed: {e}")

def test_gpio():
    print("\n--- Testing GPIO (Cadence) ---")
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(config.GPIO_CADENCE_A, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(config.GPIO_CADENCE_B, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    
    print("Monitoring GPIO 23/24 for 5 Seconds (Rotate Cranks)...")
    start = time.time()
    try:
        while (time.time() - start) < 5:
            a = GPIO.input(config.GPIO_CADENCE_A)
            b = GPIO.input(config.GPIO_CADENCE_B)
            print(f"Pin 23: {a} | Pin 24: {b}", end='\r')
            time.sleep(0.1)
        print("\nGPIO Test Done.")
    except KeyboardInterrupt:
        pass
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    i2c = test_i2c()
    if i2c:
        test_adc(i2c)
        test_dac(i2c)
        test_aht(i2c)
    test_serial()
    test_gpio()
