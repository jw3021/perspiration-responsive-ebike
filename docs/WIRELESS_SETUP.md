# Wireless Setup & Field Connectivity Guide

This guide covers how to set up your Raspberry Pi for **Wireless SSH**, allowing you to remove the USB data cable and connect to the bike controller wirelessly.

## 1. The Concepts

You have two main options for wireless connectivity. For an E-Bike, **Option B (Hotspot)** is often better for field use.

| Feature        | Option A: Home Wi-Fi (Client Mode)        | Option B: Field Hotspot (AP Mode)                        |
| :------------- | :---------------------------------------- | :------------------------------------------------------- |
| **Best For**   | Installing updates, downloading libraries | **Tuning the bike outside**, on the road, or in a garage |
| **Dependency** | Needs your home Router                    | Needs **NO** external hardware                           |
| **Range**      | Limited to your house                     | Works anywhere (Pi creates the network)                  |
| **Internet**   | Yes                                       | No (unless bridged, which is complex)                    |

---

## 2. Connecting to Home Wi-Fi (Initial Setup)

You must be connected via USB Gadget mode first to set this up.

1.  **SSH into the Pi** (from your PC terminal):

    ```powershell
    ssh pi@192.168.1.87
    ```

    _Password matches what you set (default: `raspberry`, unless you changed it)_

2.  **Open Network Config**:

    ```bash
    sudo raspi-config
    ```

3.  **Navigate**:
    - Select **1 System Options** -> **S1 Wireless LAN**.
    - Enter your **SSID** (WiFi Name).
    - Enter your **Passphrase** (WiFi Password).
    - Select **Finish**.

4.  **Verify IP**:

    ```bash
    hostname -I
    ```

    _Write down the IP address (e.g., `192.168.1.45`)._

5.  **Go Wireless**:
    - Shut down: `sudo shutdown -h now`.
    - Unplug USB from PC.
    - Connect Pi to Bike Battery/External Power (PWR port).
    - On PC: `ssh pi@<IP_ADDRESS>` or `ssh pi@raspberrypi.local`.

---

## 3. Setting up "Field Hotspot" Mode (Recommended)

This makes the Pi broadcast its own Wi-Fi network (e.g., "EBIKE_CONTROLLER") so you can connect to it with your laptop or phone anywhere.

**We will use `RaspAP` or a simple `nmcli` setup.** The simplest manual method is usually `NetworkManager`.

### Step 1: Install Network Manager

(While connected to Home Wi-Fi)

```bash
sudo apt update
sudo apt install network-manager
```

### Step 2: Create the Hotspot

Run the following command in the Pi terminal (replace `MyEbike` and `password`):

```bash
sudo nmcli device wifi hotspot ifname wlan0 con-name "MyEbike" ssid "MyEbike" password "password123"
```

### Step 3: Connect

1.  On your PC/Phone, look for Wi-Fi network **"MyEbike"**.
2.  Connect with **"password123"**.
3.  SSH into the Pi:
    ```bash
    ssh pi@10.42.0.1
    ```
    _(NetworkManager hotspots usually default to `10.42.0.1`)_.

---

## 4. Switching Modes

If you need to switch back to Home Wi-Fi for updates:

1.  **Stop Hotspot**: `sudo nmcli connection down "MyEbike"`
2.  **Connect Home**: `sudo nmcli device wifi connect "YourHomeSSID" password "YourPassword"`
