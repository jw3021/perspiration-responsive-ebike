import serial
import time
import sys

# Import the existing config for the serial port
try:
    import config
except ImportError:
    print("Error: Ensure you are running this in your Pi_code directory.")
    sys.exit(1)

def test_serial():
    print("="*60)
    print("  CYCLE ANALYST V3: RAW DATA HEX/STRING DUMPER")
    print("="*60)
    print(f"Connecting to {config.SERIAL_PORT} at {config.SERIAL_BAUD} baud...\n")
    
    try:
        ser = serial.Serial(config.SERIAL_PORT, config.SERIAL_BAUD, timeout=3)
    except Exception as e:
        print(f"Failed to open port: {e}")
        return

    # Flush any garbage data sitting in the buffer
    ser.reset_input_buffer()
    
    lines_read = 0
    print("Waiting for data stream (Make sure the Cycle Analyst is physically ON)...\n")
    
    while lines_read < 5:
        if ser.in_waiting:
            # Read a raw line from the CA
            raw_bytes = ser.readline()
            
            try:
                line = raw_bytes.decode('utf-8', errors='ignore').strip()
                parts = line.split('\t')
                
                print(f"--- READ #{lines_read + 1} ---")
                print(f"RAW STRING  : '{line}'")
                print(f"TOTAL PARTS : {len(parts)} blocks detected separated by tabs")
                
                if len(parts) > 3:
                    print(f"Index [0] (Ah)    -> {parts[0]}")
                    print(f"Index [1] (Volts) -> {parts[1]}")
                    print(f"Index [2] (Amps)  -> {parts[2]}")
                    print(f"Index [3] (Speed) -> {parts[3]}")
                else:
                    print(">>> WARNING: Format is completely different! Grin Firmware mismatch!")
                    
                print("-" * 60)
                lines_read += 1
                
            except Exception as e:
                print(f"Parse error on line: {e}")
        else:
            time.sleep(0.1)
            
    ser.close()
    print("\nSUCCESS: Dump completed. Inspect the indices above to guarantee the positions!")

if __name__ == "__main__":
    test_serial()
