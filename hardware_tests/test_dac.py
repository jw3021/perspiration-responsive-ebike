#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import time
import board
import busio
import adafruit_mcp4725

try:
    import config
    mcp_address = config.MCP4725_ADDRESS
except ImportError:
    mcp_address = 0x62 # default

def main():
    print("DAC (MCP4725) Test Script")
    
    # Initialize I2C
    try:
        i2c = board.I2C() 
    except Exception as e:
        print(f"I2C Init Failed (board.I2C): {e}")
        try:
             i2c = busio.I2C(board.SCL, board.SDA)
             print("Initialized I2C using busio.")
        except Exception as e2:
             print(f"Critical: Cannot initialize I2C: {e2}")
             return

    # Initialize DAC
    try:
        dac = adafruit_mcp4725.MCP4725(i2c, address=mcp_address)
        print(f"MCP4725 DAC connected successfully at address {hex(mcp_address)}.")
    except Exception as e:
        print(f"Failed to connect to MCP4725 DAC: {e}")
        return

    print("\nEnter a voltage to test the motor controller, or 'q' to quit.")
    print("WARNING: Make sure your bike is secure, as the motor might spin!")
    
    try:
        while True:
            user_input = input("Voltage (0.0 - 3.3V): ")
            if user_input.lower() == 'q':
                break
            
            try:
                voltage = float(user_input)
                
                if voltage < 0.0 or voltage > 3.3:
                    print("Output clamped to between 0.0 and 3.3V for safety.")
                    
                voltage = max(0.0, min(3.3, voltage))
                
                # 12-bit DAC: 0-4095. Powered by 3.3V logic line.
                raw_value = int((voltage / 3.3) * 4095)
                dac.raw_value = raw_value
                print(f"-> Set DAC output to {voltage}V (raw value: {raw_value})")
                
            except ValueError:
                print("Invalid input. Please enter a valid number (e.g. 1.5).")
                
    except KeyboardInterrupt:
        pass
    finally:
        print("\nResetting DAC output to 0V (safe state)...")
        try:
            dac.raw_value = 0
            time.sleep(0.1) # Give it a moment to apply
        except Exception:
            pass
        print("Done. Goodbye!")

if __name__ == "__main__":
    main()
