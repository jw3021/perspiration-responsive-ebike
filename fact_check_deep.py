import uiautomator2 as u2

def main():
    print("=" * 60)
    print("  DEEP MEMORY & CANVAS DUMPER")
    print("=" * 60)
    
    try:
        print("\nConnecting to Android...")
        d = u2.connect()
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    print("\n--- HUNTING FOR HIDDEN 0.28 IN OVERLAYS ---")
    all_elements = d()
    found = False
    
    for i, elem in enumerate(all_elements):
        info = elem.info
        text = info.get('text', '')
        desc = info.get('contentDescription', '')
        cls = info.get('className', '')
        
        # We are looking for anything remotely resembling a decimal number
        if text or desc:
            print(f"[{cls}]: text='{text}' | desc='{desc}'")
            if "0.2" in str(text) or "0.2" in str(desc) or "0.3" in str(text) or "0.3" in str(desc):
                found = True
                
    print("\n===============================")
    if not found:
        print(">>> CRITICAL FAILURE: '0.28' does not legally exist as text inside the Android OS!")
        print(">>> This confirms the number you are staring at is literally an animated graphic/canvas (an image) and cannot be scraped natively without OCR.")
    else:
        print(">>> Look through the output above. If you see '0.28' hiding inside a 'desc=' field, it means the developers hid it in an accessibility layer and we can perfectly extract it!")

if __name__ == "__main__":
    main()
