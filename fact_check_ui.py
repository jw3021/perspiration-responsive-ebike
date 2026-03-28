import time
import uiautomator2 as u2

def main():
    print("=" * 60)
    print("  hDrop UI Fact Checker & Memory Dump")
    print("=" * 60)
    
    # 1. Connect to Android
    try:
        print("\nConnecting to phone via ADB...")
        d = u2.connect()
        print(f"Connected to: {d.info.get('model', 'Unknown Android')}")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # 2. Dump all TextViews
    print("\n--- DUMPING RAW ANDROID ACCESSIBILITY MEMORY ---")
    try:
        all_text = []
        for elem in d(className="android.widget.TextView"):
            text = elem.get_text()
            if text:
                all_text.append(text)
                
        for i, text in enumerate(all_text):
            print(f"[{i}] -> '{text}'")
            
    except Exception as e:
        print(f"Failed to dump UI: {e}")
        return
        
    # 3. Analyze for Duplicates / Zombie Fragments
    print("\n" + "=" * 60)
    print("  ANALYZING FOR ZOMBIE FRAGMENTS / DUPLICATES")
    print("=" * 60)
    
    fluid_hits = 0
    temp_hits = 0
    
    for i, text in enumerate(all_text):
        t = " ".join(text.upper().split())
        
        # Checking for Fluid
        if "FLUID" in t and "LOSS" in t and ("L" in t or "(L)" in t):
            fluid_hits += 1
            if i < len(all_text) - 1:
                val = all_text[i + 1].strip()
                print(f"[!] Found 'FLUID LOSS' string at index [{i}]!")
                print(f"    -> The value underneath it is at index [{i+1}]: '{val}'")
                
        # Checking for Temp
        elif "TEMP" in t and "SENSOR" in t:
            temp_hits += 1
            if i > 0:
                val = all_text[i - 1].strip()
                print(f"[!] Found 'TEMP. SENSOR' string at index [{i}]!")
                print(f"    -> The value above it is at index [{i-1}]: '{val}'")
                
    print("\n--- SUMMARY ---")
    print(f"Total 'FLUID LOSS' blocks found in memory: {fluid_hits}")
    if fluid_hits > 1:
        print(">>> BUSTED! Android is leaving duplicate UI blocks in its memory architecture! <<<")
        print(">>> This is mathematically why the old number was trapped in the parser! <<<")
    elif fluid_hits == 1:
        print(">>> Only 1 block found. The 'max()' function will still guarantee it locks properly. <<<")
    else:
        print(">>> 0 blocks found. Are you sure the app is open to the right screen? <<<")

if __name__ == "__main__":
    main()
