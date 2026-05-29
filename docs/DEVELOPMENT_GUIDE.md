# PRO Development Workflow: "Live Coding" via USB

The best way to develop on a Pi Zero 2 W is **Headless USB Gadget Mode** combined with **VS Code Remote - SSH**.

**Why this is the best method:**

1.  **Single Cable**: Power and Data travel over one USB cable. No HDMI, no keyboard, no separate power supply needed.
2.  **Live Editing**: You edit files in VS Code on your PC, but they are _saved directly on the Pi_.
3.  **Instant Feedback**: You run the code in the VS Code integrated terminal. No file copying steps.

---

## ONE-TIME SETUP (Do this first)

### 1. Prepare the SD Card (Before putting it in the Pi)

Insert the fresh SD card into your PC. You will see a small partition called `boot`.

**A. Enable USB Ethernet (Gadget Mode)**

1.  Open `config.txt` in VS Code (or Notepad++).
    - Add this line to the very bottom:
      ```text
      dtoverlay=dwc2
      ```
    - _Save and close._

2.  Open `cmdline.txt`. **CRITICAL:** This file must be **ONE SINGLE LINE**.
    - Find the text `rootwait`.
    - Insert `modules-load=dwc2,g_ether` immediately after it, separated by a single space.
    - Example result:
      ```text
      console=serial0,115200 console=tty1 root=PARTUUID=... rootwait modules-load=dwc2,g_ether fsck.repair=yes ...
      ```
    - _Save and close._

**B. Enable SSH**

1.  Create a completely empty file named `ssh` (no extension!) in the root of the `boot` drive.
    - _Tip: In Windows Explorer, right-click -> New -> Text Document. Name it `ssh` and delete the `.txt` extension._

**C. Configure Wi-Fi (Optional but recommended for updates)**

1.  Create a file `wpa_supplicant.conf` in `boot` with your wifi details:

    ```text
    country=GB
    ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
    update_config=1

    network={
        ssid="YourWiFiName"
        psk="YourWiFiPassword"
    }
    ```

---

### 2. Connect Hardware

1.  Eject SD card and insert into Pi.
2.  **CRITICAL**: Connect your high-quality USB data cable to the **USB Port** (inner port, usually labeled 'USB'), **NOT** the 'PWR' port.
3.  Connect the other end to your PC.
4.  Wait ~90 seconds for the first boot.

### 3. Windows Network Setup (Active Driver)

1.  On your PC, you should hear the "USB Connected" sound.
2.  Check **Device Manager** -> **Network Adapters**.
    - Look for "USB Ethernet/RNDIS Gadget" or similar.
    - **If you see "COM Port" or "Unknown Device"**:
      1. Right-click device -> Update Driver.
      2. Browse my computer -> Let me pick from a list.
      3. Microsoft -> **Remote NDIS Compatible Device**.
      4. Install that driver.

### 4. VS Code Setup

1.  Install the **Remote - SSH** extension by Microsoft from the Extensions sidebar.
2.  Press `F1` (or Ctrl+Shift+P) -> Type `Remote-SSH: Connect to Host...`
3.  Enter: `pi@raspberrypi.local`
4.  Select "Linux", then "Continue" (if prompted about key fingerprint).
5.  Password is usually `raspberry` (or your configured user/pass).

---

## THE DAILY WORKFLOW

Once connected, your VS Code window is now "inside" the Pi.

1.  **Open Folder**:
    - File -> Open Folder -> `/home/pi/code` (Create this storage folder).
2.  **Transfer Your Code**:
    - Simply drag and drop the Python files from your PC folder into the VS Code file explorer sidebar. They will upload instantly.
3.  **Run & Debug**:
    - Open the Terminal in VS Code (`Ctrl + ` `).
    - Type `python3 ebike_controller.py`.
    - You will see the live output:
      ```text
      Spd: 0.0 | RPM: 15.0 | Trq: 12.3Nm | Out: 1.45V
      ```
4.  **Iterate**:
    - See a bug? Change the code in the editor.
    - Press `Ctrl+S` (Save).
    - Click in the terminal, press `Up Arrow` -> `Enter` to restart the script.

## PRO TIPS

1.  **Auto-Restart Loop**:
    To avoid restarting manually, install `watchdog`:

    ```bash
    pip3 install watchdog
    ```

    Run your script with `watchmedo`:

    ```bash
    watchmedo auto-restart --patterns="*.py" --recursive -- python3 ebike_controller.py
    ```

    _Now, whenever you Ctrl+S, the code automatically restarts!_

2.  **Plotting Data**:
    If you need to visualize the data, simply print it as CSV in the terminal, copy-paste it into Excel/Python later, OR pipe it to a file on the Pi:
    ```bash
    python3 ebike_controller.py > log.csv
    ```
    Then open `log.csv` in VS Code to see it.
