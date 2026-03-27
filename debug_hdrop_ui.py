import uiautomator2 as u2

print("Connecting to phone via ADB...")
try:
    d = u2.connect()
    print(f"Connected to: {d.info.get('productName', 'Unknown')}")
    
    print("\n--- Dumping all TEXT visible on screen ---")
    for i, elem in enumerate(d(className="android.widget.TextView")):
        text = elem.get_text()
        if text:
            print(f"[{i}] -> '{text}'")
            
    print("\nDone! Please copy and paste this output to me!")
            
except Exception as e:
    print(f"Failed to connect or read UI: {e}")
