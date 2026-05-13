import sys
import os
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# --- CONFIG (mirrors ebike_controller config values directly) ---
MIN_TORQUE_NM       = 5.0
MAX_TORQUE_INPUT_NM = 60.0
MOTOR_IDLE_OUTPUT_V = 1.0
MOTOR_MIN_ASSIST_V  = 1.5
BAND_MAX_V = {"LOW": 2.5, "HIGH": 4.5}

# --- SUPABASE ---
try:
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.py')
    with open(config_path, 'r') as f:
        config_text = f.read()
    SUPABASE_URL = re.search(r'SUPABASE_URL\s*=\s*["\']([^"\']+)["\']', config_text).group(1)
    SUPABASE_KEY = re.search(r'SUPABASE_KEY\s*=\s*["\']([^"\']+)["\']', config_text).group(1)
    from supabase import create_client
except Exception as e:
    print(f"Error loading Supabase credentials: {e}")
    sys.exit(1)


def fetch_assist_data(client):
    """Fetch torque_nm, voltage_out, and power_band from all rides."""
    print("Fetching assist data from Supabase...")
    all_data = []
    chunk_size = 1000
    start = 0
    while True:
        response = (
            client.table("ride_metrics_v2")
            .select("torque_nm, voltage_out, power_band, speed_kph")
            .range(start, start + chunk_size - 1)
            .execute()
        )
        data = response.data
        if not data:
            break
        all_data.extend(data)
        if len(data) < chunk_size:
            break
        start += chunk_size

    df = pd.DataFrame(all_data)
    df = df.dropna(subset=["torque_nm", "voltage_out"])
    df["torque_nm"]   = pd.to_numeric(df["torque_nm"],   errors="coerce")
    df["voltage_out"] = pd.to_numeric(df["voltage_out"], errors="coerce")
    df["speed_kph"]   = pd.to_numeric(df["speed_kph"],   errors="coerce")

    # Keep only rows where assist was genuinely active
    df = df[
        (df["torque_nm"]   > MIN_TORQUE_NM) &
        (df["voltage_out"] > MOTOR_IDLE_OUTPUT_V) &
        (df["speed_kph"]   < 25.0)
    ]
    return df.dropna(subset=["torque_nm", "voltage_out"])


def theoretical_voltage(torque_nm, max_v):
    """Compute the DAC output voltage for a given rider torque and power band ceiling."""
    torque_nm = np.asarray(torque_nm, dtype=float)
    v_out = np.where(
        torque_nm < MIN_TORQUE_NM,
        MOTOR_IDLE_OUTPUT_V,
        MOTOR_MIN_ASSIST_V + np.clip(
            (torque_nm - MIN_TORQUE_NM) / (MAX_TORQUE_INPUT_NM - MIN_TORQUE_NM), 0.0, 1.0
        ) * (max_v - MOTOR_MIN_ASSIST_V)
    )
    return v_out


def main():
    print("=" * 55)
    print("  STEP 0: ASSIST CHARACTERISATION — MOTOR PROFILE PLOT")
    print("=" * 55)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    df = fetch_assist_data(client)
    print(f"  Loaded {len(df):,} active-assist data points.")

    torque_range = np.linspace(0, 70, 500)

    fig = plt.figure(figsize=(20, 6))
    fig.suptitle("E-Bike Assist Characterisation: Commercial vs. Proposed System", fontsize=13, fontweight="bold")
    gs = gridspec.GridSpec(1, 3, figure=fig, wspace=0.38)

    # ------------------------------------------------------------------ #
    #  LEFT PANEL — Commercial mid-drive (torque-proportional)            #
    # ------------------------------------------------------------------ #
    ax1 = fig.add_subplot(gs[0])

    modes = {
        "Eco  (1.5×)":   1.5,
        "Sport (2.0×)":  2.0,
        "Turbo (3.5×)":  3.5,
    }
    colours = ["#2196F3", "#FF9800", "#F44336"]

    for (label, mult), colour in zip(modes.items(), colours):
        ax1.plot(torque_range, torque_range * mult, label=label, color=colour, linewidth=2)

    ax1.plot(torque_range, torque_range, color="grey", linewidth=1,
             linestyle="--", label="No assist (1×)", alpha=0.6)

    ax1.set_xlabel("Rider Input Torque (Nm)", fontsize=11)
    ax1.set_ylabel("Total Torque at Wheel (Nm)  [Rider + Motor]", fontsize=11)
    ax1.set_title("Commercial Mid-Drive\n(e.g. Bosch, Shimano Steps)", fontsize=11)
    ax1.set_xlim(0, 70)
    ax1.set_ylim(0, 250)
    ax1.legend(fontsize=9)
    ax1.grid(True, alpha=0.3)

    # ------------------------------------------------------------------ #
    #  RIGHT PANEL — This system (torque → DAC voltage)                   #
    # ------------------------------------------------------------------ #
    ax2 = fig.add_subplot(gs[1])

    # Real logged data scatter (all bands together, sampled for clarity)
    sample = df.sample(n=min(3000, len(df)), random_state=42) if len(df) > 3000 else df
    ax2.scatter(
        sample["torque_nm"], sample["voltage_out"],
        alpha=0.12, s=6, color="#607D8B", zorder=2
    )

    # Theoretical curves — two modes only
    band_labels = {"LOW": "Normal Mode (2.5V ceiling)", "HIGH": "Sweat Reduction Mode (4.5V ceiling)"}
    band_colours = {"LOW": "#4CAF50", "HIGH": "#F44336"}
    for band, max_v in BAND_MAX_V.items():
        v_curve = theoretical_voltage(torque_range, max_v)
        ax2.plot(torque_range, v_curve, color=band_colours[band],
                 linewidth=2.5, label=band_labels[band], zorder=3)

    # Annotate the saturation point
    ax2.axvline(x=MAX_TORQUE_INPUT_NM, color="black", linewidth=1,
                linestyle=":", alpha=0.6, label=f"Saturation ({int(MAX_TORQUE_INPUT_NM)} Nm)")
    ax2.axvline(x=MIN_TORQUE_NM, color="grey", linewidth=1,
                linestyle=":", alpha=0.5, label=f"Engage threshold ({int(MIN_TORQUE_NM)} Nm)")

    ax2.set_xlabel("Rider Input Torque (Nm)", fontsize=11)
    ax2.set_ylabel("DAC Output Voltage (V)  →  Motor Command", fontsize=11)
    ax2.set_title("Custom System\n(Open-loop torque → voltage; shown at low-speed ceiling)", fontsize=11)
    ax2.set_xlim(0, 70)
    ax2.set_ylim(0.8, 5.0)
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)

    # ------------------------------------------------------------------ #
    #  RIGHT PANEL 2 — Cold-start boost: speed vs voltage ceiling        #
    # ------------------------------------------------------------------ #
    ax3 = fig.add_subplot(gs[2])

    COLD_START_CUTOFF_KPH = 12.0
    V_NORMAL = 2.5
    V_MAX    = 4.5

    speed_range = np.linspace(0, 25, 500)

    # Normal mode: flat ceiling at 2.5V at all speeds
    ax3.plot(speed_range, np.full_like(speed_range, V_NORMAL),
             color="#4CAF50", linewidth=2.5, label="Normal Mode (2.5V)")

    # Sweat reduction mode: tapers from 4.5V at standstill to 3.0V at 12 km/h, then holds flat.
    # The cold-start slope is a property of this mode, not a separate state.
    V_SWEAT_CRUISE = 3.0
    sweat_ceiling = np.where(
        speed_range < COLD_START_CUTOFF_KPH,
        V_MAX - (speed_range / COLD_START_CUTOFF_KPH) * (V_MAX - V_SWEAT_CRUISE),
        V_SWEAT_CRUISE
    )
    ax3.plot(speed_range, sweat_ceiling,
             color="#F44336", linewidth=2.5, label="Sweat Reduction Mode (4.5V → 3.0V)")

    # Shade the gap between normal ceiling and sweat reduction ceiling
    ax3.fill_between(speed_range, V_NORMAL, sweat_ceiling,
                     color="#F44336", alpha=0.07, zorder=1)

    # Highlight the cold-start zone where the ceiling is most impactful
    ax3.axvspan(0, COLD_START_CUTOFF_KPH, color="#FF9800", alpha=0.10, zorder=0)
    ax3.axvline(x=COLD_START_CUTOFF_KPH, color="#FF9800", linewidth=1.2,
                linestyle="--", alpha=0.8)

    # Airflow recovery label only
    ax3.text(COLD_START_CUTOFF_KPH + 0.5, 2.35, f"Airflow recovery\n(~{int(COLD_START_CUTOFF_KPH)} km/h)",
             fontsize=8, color="#8B4000", ha="left", va="top")

    ax3.set_xlabel("Speed (km/h)", fontsize=11)
    ax3.set_ylabel("Voltage Ceiling (V)  →  Max Motor Command", fontsize=11)
    ax3.set_title("Mode Voltage Ceiling vs. Speed\n(Cold-start benefit)", fontsize=11)
    ax3.set_xlim(0, 25)
    ax3.set_ylim(1.5, 5.2)
    ax3.legend(fontsize=9, loc="upper right")
    ax3.grid(True, alpha=0.3)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "00_assist_characterisation.png")
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    print(f"\n-> Saved: {output_path}")
    plt.close()
    print("Done.")


if __name__ == "__main__":
    main()
