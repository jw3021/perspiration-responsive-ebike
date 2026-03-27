#!/usr/bin/env python3
"""
hDrop Fluid Loss Reader — Raspberry Pi Edition
================================================
Reads fluid loss values from the hDrop Android app via USB.
The Android phone running the hDrop app is plugged directly into the Pi.

This script is standalone and will be integrated into the e-bike
controller later.

Prerequisites (on the Pi):
    sudo apt-get update
    sudo apt-get install -y adb
    pip3 install uiautomator2

First-time phone setup:
    1. Enable Developer Options on the Android phone
       (Settings > About Phone > tap Build Number 7 times)
    2. Enable USB Debugging in Developer Options
    3. Plug the phone into the Pi via USB
    4. On the phone, accept the "Allow USB debugging?" prompt
    5. Run: adb devices   (should show your phone listed)
    6. Run: python3 -m uiautomator2 init   (installs the ATX agent on the phone)

Usage:
    python3 hdrop_reader.py
"""

import time
import os
import subprocess
import csv
from datetime import datetime

try:
    import uiautomator2 as u2
except ImportError:
    print("=" * 60)
    print("ERROR: uiautomator2 is not installed.")
    print("Install it with:  pip3 install uiautomator2")
    print("Then run:          python3 -m uiautomator2 init")
    print("=" * 60)
    exit(1)


# ─── CONFIGURATION ──────────────────────────────────────────
HDROP_PACKAGE = "com.hdroptech.app"
POLL_INTERVAL_S = 2          # Seconds between readings
RECONNECT_DELAY_S = 5        # Seconds to wait before reconnecting
LOG_TO_CSV = True            # Save readings to CSV file
CSV_FILENAME = "hdrop_log.csv"
MAX_CONSECUTIVE_ERRORS = 10  # Reconnect after this many errors in a row
# ────────────────────────────────────────────────────────────


def check_adb_available():
    """Verify that ADB is installed and accessible on the Pi."""
    try:
        result = subprocess.run(
            ["adb", "version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version_line = result.stdout.strip().split("\n")[0]
            print(f"  ADB: {version_line}")
            return True
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  ADB check error: {e}")

    print("ERROR: ADB is not installed or not in PATH.")
    print("Install with:  sudo apt-get install -y adb")
    return False


def check_phone_connected():
    """Check if any Android device is connected via ADB."""
    try:
        result = subprocess.run(
            ["adb", "devices"],
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split("\n")
        # First line is header "List of devices attached"
        # Connected devices appear as "<serial>\tdevice"
        devices = [
            line for line in lines[1:]
            if line.strip() and "device" in line and "unauthorized" not in line
        ]
        if devices:
            serial = devices[0].split("\t")[0]
            print(f"  Phone: {serial}")
            return serial
        else:
            # Check if unauthorized
            unauthorized = [line for line in lines[1:] if "unauthorized" in line]
            if unauthorized:
                print("ERROR: Phone is connected but USB debugging is not authorized.")
                print("       Please accept the USB debugging prompt on the phone.")
            else:
                print("ERROR: No Android device found.")
                print("       Make sure the phone is plugged in and USB debugging is enabled.")
            return None
    except Exception as e:
        print(f"  Device check error: {e}")
        return None


def connect_to_phone():
    """
    Connect to the Android phone using uiautomator2.
    Returns a u2.Device object or None on failure.
    """
    try:
        d = u2.connect()  # Connects to the first available USB device
        # Verify connection is alive
        info = d.info
        print(f"  Device: {info.get('productName', 'Unknown')}")
        print(f"  Screen: {info.get('displayWidth', '?')}x{info.get('displayHeight', '?')}")
        return d
    except Exception as e:
        print(f"  Connection failed: {e}")
        return None


def ensure_hdrop_foreground(d):
    """
    Check if the hDrop app is in the foreground and the screen is on.
    Returns True if it is. If not, prints a warning but still returns True 
    to force reading just in case app_current() is glitching.
    """
    try:
        # We must ensure the screen is on, otherwise the UI tree is empty!
        if not d.info.get('screenOn'):
            print("  [zZz] Waking up phone screen...")
            d.screen_on()
            time.sleep(1) # Wait for screen to turn on

        current = d.app_current()
        pkg = current.get("package", "unknown")
        if pkg == HDROP_PACKAGE:
            return True
        else:
            # Silencing the annoying UIAutomator package mis-read warning
            # print(f"  [?] reported foreground app is '{pkg}' (will try reading anyway)")
            return True
    except Exception as e:
        print(f"  Could not check foreground app: {e}")
        return True


def launch_hdrop(d):
    """Attempt to launch or bring the hDrop app to the foreground."""
    try:
        print("  Launching hDrop app...")
        d.app_start(HDROP_PACKAGE)
        time.sleep(3)  # Give the app time to load
        return ensure_hdrop_foreground(d)
    except Exception as e:
        print(f"  Could not launch hDrop: {e}")
        return False


def get_hdrop_metrics(d):
    """
    Extract the fluid loss and temperature values from the hDrop app UI.
    Returns: dict {"fluid": float or None, "temp": float or None}
    """
    try:
        all_text = []
        for elem in d(className="android.widget.TextView"):
            text = elem.get_text()
            if text:
                all_text.append(text)

        fluid = None
        temp = None

        for i, text in enumerate(all_text):
            t = " ".join(text.upper().split())
            
            # Fluid Loss Look-up
            if "FLUID" in t and "LOSS" in t and ("L" in t or "(L)" in t):
                if i < len(all_text) - 1:
                    raw_value = all_text[i + 1].strip()
                    if raw_value in ("--", "-", "—", ""):
                        fluid = 0.0
                    else:
                        clean_val = "".join(c for c in raw_value if c.isdigit() or c == '.')
                        if clean_val:
                            try: fluid = float(clean_val)
                            except ValueError: pass
                            
            # Temperature Look-up
            # Note: The UI drops the literal string "31°C" in some cases.
            if "°C" in t:
                raw_value = text.strip()
                clean_val = "".join(c for c in raw_value if c.isdigit() or c == '.')
                if clean_val:
                    try: temp = float(clean_val)
                    except ValueError: pass
            
            # Fallback if only the label "TEMP. SENSOR" is found. Note the value sits right ABOVE it (i - 1) in the UI tree!
            elif "TEMP" in t and "SENSOR" in t:
                if i > 0:
                    raw_value = all_text[i - 1].strip()
                    if raw_value in ("--", "-", "—", ""):
                        temp = 0.0
                    elif "°C" in raw_value.upper():
                        clean_val = "".join(c for c in raw_value if c.isdigit() or c == '.')
                        if clean_val:
                            try: temp = float(clean_val)
                            except ValueError: pass

        return {"fluid": fluid, "temp": temp}

    except Exception as e:
        print(f"  Error reading UI: {e}")
        return {"fluid": None, "temp": None}

def init_csv():
    """Create CSV log file with headers if it doesn't exist."""
    if not os.path.exists(CSV_FILENAME):
        with open(CSV_FILENAME, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "fluid_loss_L"])
        print(f"  CSV log: {os.path.abspath(CSV_FILENAME)}")


def log_to_csv(value):
    """Append a timestamped reading to the CSV log."""
    try:
        with open(CSV_FILENAME, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([datetime.now().isoformat(), value])
    except Exception as e:
        print(f"  CSV write error: {e}")


# ─── PUBLIC API ─────────────────────────────────────────────
# These functions can be imported by other scripts later.

_device = None
_last_fluid_loss = None


def init_hdrop():
    """
    Initialise the hDrop reader.
    Call once at startup. Returns True on success.
    """
    global _device
    print("\n--- hDrop Reader Init ---")

    if not check_adb_available():
        return False

    serial = check_phone_connected()
    if not serial:
        return False

    _device = connect_to_phone()
    if not _device:
        return False

    if LOG_TO_CSV:
        init_csv()

    print("  hDrop reader ready.\n")
    return True


def read_hdrop():
    """
    Read the current fluid loss and temperature values from the hDrop app.
    Returns dict: {"fluid": float, "temp": float} or Nones if unavailable.
    """
    global _device, _last_fluid_loss

    if _device is None:
        return {"fluid": None, "temp": None}

    if not ensure_hdrop_foreground(_device):
        # Try to bring it back
        if not launch_hdrop(_device):
            return {"fluid": None, "temp": None}

    metrics = get_hdrop_metrics(_device)
    if metrics["fluid"] is not None:
        _last_fluid_loss = metrics["fluid"]
    return metrics


def get_last_hdrop_value():
    """Return the most recent successfully read fluid loss value."""
    return _last_fluid_loss


# ─── STANDALONE MODE ────────────────────────────────────────

def main():
    """Main monitoring loop when run as a standalone script."""

    print("=" * 60)
    print("  hDrop Fluid Loss Reader — Raspberry Pi")
    print("=" * 60)

    # ── Pre-flight checks ──
    if not init_hdrop():
        print("\nStartup failed. Please fix the issues above and try again.")
        return

    print("-" * 60)
    print("  Monitoring hDrop fluid loss (Ctrl+C to stop)")
    print("-" * 60)

    last_value = None
    consecutive_errors = 0

    try:
        while True:
            try:
                metrics = read_hdrop()
                value = metrics["fluid"]
                tval = metrics["temp"]

                if value is not None:
                    consecutive_errors = 0  # Reset error counter

                    # Force endless printing in standalone mode so user sees it actively monitoring
                    ts = datetime.now().strftime("%H:%M:%S")
                    tstr = f"{tval:.1f} °C" if tval is not None else "--- °C"
                    print(f"  [{ts}]  Fluid Loss: {value:.3f} L  |  Skin Temp: {tstr}")
                    
                    if value != last_value:
                        if LOG_TO_CSV:
                            log_to_csv(value)
                        last_value = value
                else:
                    if last_value is not None:
                        print("  Waiting for data (dash displayed)...")
                        last_value = None
                    consecutive_errors += 1

            except Exception as e:
                print(f"  Read error: {e}")
                consecutive_errors += 1

            # If too many errors, try reconnecting
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(f"\n  {consecutive_errors} consecutive errors — reconnecting...")
                time.sleep(RECONNECT_DELAY_S)
                _device_ok = init_hdrop()
                if _device_ok:
                    consecutive_errors = 0
                else:
                    print("  Reconnection failed. Retrying in 10s...")
                    time.sleep(10)

            time.sleep(POLL_INTERVAL_S)

    except KeyboardInterrupt:
        print("\n\n  Monitoring stopped.")
        if _last_fluid_loss is not None:
            print(f"  Last recorded fluid loss: {_last_fluid_loss:.3f} L")
        if LOG_TO_CSV:
            print(f"  Log saved to: {os.path.abspath(CSV_FILENAME)}")
        print()


if __name__ == "__main__":
    main()
