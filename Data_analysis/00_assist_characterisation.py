import sys
import os
import numpy as np
import matplotlib.pyplot as plt

# Thesis style
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plot_style
plot_style.apply()

# --- CONFIG (mirrors ebike_controller config values directly) ---
MIN_TORQUE_NM       = 5.0
MAX_TORQUE_INPUT_NM = 60.0
MOTOR_IDLE_OUTPUT_V = 1.0
MOTOR_MIN_ASSIST_V  = 1.5
BAND_MAX_V = {"LOW": 2.5, "HIGH": 4.5}


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


def plot_torque_voltage(torque_range, output_dir):
    """Custom system: rider torque → DAC voltage (theoretical curves, no scatter)."""
    fig, ax = plt.subplots(figsize=(7, 5))

    band_labels  = {"LOW": "Normal Mode", "HIGH": "Sweat Reduction Mode"}
    band_colours = {"LOW": plot_style.PRIMARY, "HIGH": plot_style.ACCENT}

    for band, max_v in BAND_MAX_V.items():
        v_curve = theoretical_voltage(torque_range, max_v)
        ax.plot(torque_range, v_curve, color=band_colours[band],
                linewidth=1.8, label=band_labels[band])

    ax.axvline(x=MAX_TORQUE_INPUT_NM, color=plot_style.NEUTRAL, linestyle='--',
               linewidth=1.2, label=f"Saturation ({int(MAX_TORQUE_INPUT_NM)} Nm)")

    ax.set_xlabel("Rider input torque (Nm)")
    ax.set_ylabel("DAC output voltage (V)")
    ax.set_xlim(0, 70)
    ax.set_ylim(0.8, 5.0)
    ax.legend(loc='upper left')

    output_path = os.path.join(output_dir, "00_torque_voltage.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"-> Saved: {output_path}")


def plot_speed_ceiling(output_dir):
    """Voltage ceiling vs speed — cold-start benefit."""
    COLD_START_CUTOFF_KPH = 12.5
    V_NORMAL      = 2.5
    V_MAX         = 4.5
    V_SWEAT_CRUISE = 3.0

    speed_range = np.linspace(0, 25, 500)

    fig, ax = plt.subplots(figsize=(7, 5))

    ax.plot(speed_range, np.full_like(speed_range, V_NORMAL),
            color=plot_style.PRIMARY, linewidth=1.8, label="Normal Mode")

    sweat_ceiling = np.where(
        speed_range < COLD_START_CUTOFF_KPH,
        V_MAX - (speed_range / COLD_START_CUTOFF_KPH) * (V_MAX - V_SWEAT_CRUISE),
        V_SWEAT_CRUISE
    )
    ax.plot(speed_range, sweat_ceiling,
            color=plot_style.ACCENT, linewidth=1.8, label="Sweat Reduction Mode")

    ax.fill_between(speed_range, V_NORMAL, sweat_ceiling,
                    color=plot_style.ACCENT, alpha=0.08)

    ax.axvspan(0, COLD_START_CUTOFF_KPH, color=plot_style.LIGHT_BLUE, alpha=0.12, zorder=0)

    ax.text(COLD_START_CUTOFF_KPH + 0.5, 1.1,
            f"← Cold-start zone (~{int(COLD_START_CUTOFF_KPH)} km/h)",
            fontsize=8, color=plot_style.NEUTRAL, ha="left", va="bottom")

    ax.set_xlabel("Speed (km/h)")
    ax.set_ylabel("Voltage ceiling (V)")
    ax.set_xlim(0, 25)
    ax.set_ylim(0.8, 5.0)
    ax.legend(loc="upper right")

    output_path = os.path.join(output_dir, "00_speed_ceiling.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"-> Saved: {output_path}")


def main():
    print("=" * 55)
    print("  STEP 0: ASSIST CHARACTERISATION — MOTOR PROFILE PLOTS")
    print("=" * 55)

    output_dir   = os.path.dirname(os.path.abspath(__file__))
    torque_range = np.linspace(0, 70, 500)

    plot_torque_voltage(torque_range, output_dir)
    plot_speed_ceiling(output_dir)
    print("Done.")


if __name__ == "__main__":
    main()
