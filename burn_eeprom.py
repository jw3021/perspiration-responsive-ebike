import time
import board
import config

print("Connecting to I2C Bus...")
i2c = board.I2C()
address = config.MCP4725_ADDRESS

# We want roughly 1.0V resting voltage. Because the Cycle Analyst Faults if it sees > 1.0V, 
# let's be extremely safe and burn 0.5V (so it boots perfectly safe, then leaps to 1.0V when Python runs)
safe_boot_voltage = 0.5
val = int((safe_boot_voltage / config.DAC_VDD_V) * 4095)

print(f"Burning physical {safe_boot_voltage}V idle-state into MCP4725 EEPROM at {hex(address)}...")

while not i2c.try_lock():
    pass

try:
    # 0x60 is the hardware I2C command to 'Write to EEPROM' natively inside the DAC chip chip
    command = 0x60
    high_byte = (val >> 4) & 0xFF
    low_byte = (val << 4) & 0xFF
    
    i2c.writeto(address, bytes([command, high_byte, low_byte]))
    time.sleep(0.1) # Give the EEPROM 100ms to physically burn the silicon
    print("\nSUCCESS! Hardware patched!")
    print("The Pi will now instantly output 0.5V the precise millisecond it receives power.")
except Exception as e:
    print(f"Error burning EEPROM: {e}")
finally:
    i2c.unlock()
