#!/usr/bin/env python3
"""
Analyse Last Ride — Pull the most recent ride from Supabase and produce
a full dashboard of plots to evaluate system performance.

Usage:
    python analyse_last_ride.py              # latest ride
    python analyse_last_ride.py RIDE_20250328_143000  # specific ride ID
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.dates as mdates
from supabase import create_client

# ── Supabase ────────────────────────────────────────────────────────────────

def fetch_ride(ride_id: str | None = None) -> pd.DataFrame:
    """
    Fetch rows for the given ride_id, or the most recent ride if None.
    Returns a DataFrame sorted by timestamp.
    """
    from credentials import SUPABASE_URL, SUPABASE_KEY
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    if ride_id is None:
        # Find the latest ride_id by getting the most recent row
        result = (
            sb.table("ride_metrics_v2")
            .select("ride_id")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise RuntimeError("No rides found in Supabase.")
        ride_id = result.data[0]["ride_id"]
        print(f"Most recent ride: {ride_id}")

    # Fetch all rows for that ride (Supabase max 1000 rows per call — paginate if needed)
    all_rows = []
    page = 0
    page_size = 1000
    while True:
        result = (
            sb.table("ride_metrics_v2")
            .select("*")
            .eq("ride_id", ride_id)
            .order("timestamp")
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        )
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break
        page += 1

    if not all_rows:
        raise RuntimeError(f"No data found for ride_id '{ride_id}'.")

    df = pd.DataFrame(all_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Elapsed time in minutes (easier to read on x-axis than clock time)
    df["elapsed_min"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds() / 60.0

    print(f"Fetched {len(df)} rows  |  "
          f"Duration: {df['elapsed_min'].max():.1f} min  |  "
          f"Ride ID: {ride_id}")
    return df, ride_id


# ── Stats ────────────────────────────────────────────────────────────────────

def print_summary(df: pd.DataFrame, ride_id: str):
    duration_min = df["elapsed_min"].max()

    assist_threshold_v = 1.05  # anything above idle (1.0V) = assist active
    pct_assist = (df["voltage_out"] > assist_threshold_v).mean() * 100

    hdrop_coverage = df["fluid_loss_l"].notna().mean() * 100
    total_fluid = df["fluid_loss_l"].max() if df["fluid_loss_l"].notna().any() else None
    avg_sweat_rate = df["sweat_rate_l_hr"].mean() if df["sweat_rate_l_hr"].notna().any() else None

    print("\n" + "=" * 55)
    print(f"  RIDE SUMMARY  —  {ride_id}")
    print("=" * 55)
    print(f"  Duration          : {duration_min:.1f} min")
    print(f"  Rows logged       : {len(df)}")
    print(f"  Max speed         : {df['speed_kph'].max():.1f} km/h")
    print(f"  Avg speed         : {df['speed_kph'].mean():.1f} km/h")
    print(f"  Max cadence       : {df['rpm'].max():.0f} RPM")
    print(f"  Avg cadence       : {df['rpm'][df['rpm'] > 0].mean():.0f} RPM  (when pedalling)")
    print(f"  Max torque        : {df['torque_nm'].max():.1f} Nm")
    print(f"  Motor assist      : {pct_assist:.1f}% of ride time")
    if "motor_power_w" in df.columns and df["motor_power_w"].notna().any():
        max_pwr = df["motor_power_w"].max()
        avg_pwr = df["motor_power_w"][df["motor_power_w"] > 0].mean()
        print(f"  Max motor power   : {max_pwr:.0f} W")
        print(f"  Avg motor power   : {avg_pwr:.0f} W  (when active)")
    print(f"  Ambient temp      : {df['temp_c'].mean():.1f} °C avg")
    print(f"  Humidity          : {df['humidity_pct'].mean():.1f}% avg")
    if total_fluid is not None:
        print(f"  Total fluid loss  : {total_fluid:.3f} L")
    if avg_sweat_rate is not None:
        print(f"  Avg sweat rate    : {avg_sweat_rate:.3f} L/h")
    print(f"  HDrop coverage    : {hdrop_coverage:.0f}% of rows had data")
    print("=" * 55 + "\n")


# ── Plots ────────────────────────────────────────────────────────────────────

def plot_ride(df: pd.DataFrame, ride_id: str):
    x = df["elapsed_min"]

    fig = plt.figure(figsize=(16, 14))
    fig.suptitle(f"Ride Analysis  —  {ride_id}", fontsize=14, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)

    # ── 1. Speed over time ───────────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.plot(x, df["speed_kph"], color="#2196F3", linewidth=1.2, label="Speed")
    ax1.axhline(25.0, color="red", linestyle="--", linewidth=0.8, alpha=0.7, label="Legal limit (25 km/h)")
    ax1.set_title("Speed")
    ax1.set_xlabel("Elapsed (min)")
    ax1.set_ylabel("km/h")
    ax1.legend(fontsize=7)
    ax1.grid(True, alpha=0.3)

    # ── 2. Cadence (RPM) over time ───────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(x, df["rpm"], color="#4CAF50", linewidth=1.2)
    ax2.axhline(10.0, color="orange", linestyle="--", linewidth=0.8, alpha=0.7, label="Min cadence (10 RPM)")
    ax2.set_title("Cadence")
    ax2.set_xlabel("Elapsed (min)")
    ax2.set_ylabel("RPM")
    ax2.legend(fontsize=7)
    ax2.grid(True, alpha=0.3)

    # ── 3. Torque & Motor voltage (dual axis) ────────────────────────────────
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.plot(x, df["torque_nm"], color="#FF9800", linewidth=1.2, label="Torque (Nm)")
    ax3.set_ylabel("Torque (Nm)", color="#FF9800")
    ax3.tick_params(axis="y", labelcolor="#FF9800")
    ax3b = ax3.twinx()
    ax3b.plot(x, df["voltage_out"], color="#9C27B0", linewidth=1.0, alpha=0.8, label="V_out")
    ax3b.axhline(1.0, color="#9C27B0", linestyle=":", linewidth=0.7, alpha=0.5)  # idle line
    ax3b.set_ylabel("Motor voltage (V)", color="#9C27B0")
    ax3b.tick_params(axis="y", labelcolor="#9C27B0")
    ax3.set_title("Torque & Motor Output")
    ax3.set_xlabel("Elapsed (min)")
    ax3.grid(True, alpha=0.3)
    # Combined legend
    lines1, labels1 = ax3.get_legend_handles_labels()
    lines2, labels2 = ax3b.get_legend_handles_labels()
    ax3.legend(lines1 + lines2, labels1 + labels2, fontsize=7)

    # ── 4. Fluid loss over time ──────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 0])
    fluid_data = df.dropna(subset=["fluid_loss_l"])
    if not fluid_data.empty:
        ax4.plot(fluid_data["elapsed_min"], fluid_data["fluid_loss_l"],
                 color="#00BCD4", linewidth=1.5, marker="o", markersize=3, label="Fluid loss (L)")
        ax4.fill_between(fluid_data["elapsed_min"], fluid_data["fluid_loss_l"],
                         alpha=0.15, color="#00BCD4")
    else:
        ax4.text(0.5, 0.5, "No HDrop data", transform=ax4.transAxes,
                 ha="center", va="center", color="grey")
    ax4.set_title("Cumulative Fluid Loss")
    ax4.set_xlabel("Elapsed (min)")
    ax4.set_ylabel("Litres")
    ax4.grid(True, alpha=0.3)

    # ── 5. Sweat rate over time ──────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1, 1])
    rate_data = df.dropna(subset=["sweat_rate_l_hr"])
    if not rate_data.empty:
        ax5.plot(rate_data["elapsed_min"], rate_data["sweat_rate_l_hr"],
                 color="#F44336", linewidth=1.5, label="Sweat rate (L/h)")
        ax5.fill_between(rate_data["elapsed_min"], rate_data["sweat_rate_l_hr"],
                         alpha=0.15, color="#F44336")
    else:
        ax5.text(0.5, 0.5, "No sweat rate data", transform=ax5.transAxes,
                 ha="center", va="center", color="grey")
    ax5.set_title("Sweat Rate")
    ax5.set_xlabel("Elapsed (min)")
    ax5.set_ylabel("L / hour")
    ax5.grid(True, alpha=0.3)

    # ── 6. Skin temp vs ambient temp ─────────────────────────────────────────
    ax6 = fig.add_subplot(gs[1, 2])
    ax6.plot(x, df["temp_c"], color="#795548", linewidth=1.2, label="Ambient")
    skin_data = df.dropna(subset=["skin_temp_c"])
    if not skin_data.empty:
        ax6.plot(skin_data["elapsed_min"], skin_data["skin_temp_c"],
                 color="#FF5722", linewidth=1.5, label="Skin temp")
    ax6.set_title("Temperature")
    ax6.set_xlabel("Elapsed (min)")
    ax6.set_ylabel("°C")
    ax6.legend(fontsize=7)
    ax6.grid(True, alpha=0.3)

    # ── 7. Torque vs Voltage scatter (verify algorithm mapping) ────────────────
    ax7 = fig.add_subplot(gs[2, 0])
    sc = ax7.scatter(df["torque_nm"], df["voltage_out"],
                     c=df["speed_kph"], cmap="viridis", s=8, alpha=0.5)
    plt.colorbar(sc, ax=ax7, label="Speed (km/h)")
    ax7.set_title("Torque → Algorithm Voltage\n(coloured by speed)")
    ax7.set_xlabel("Torque (Nm)")
    ax7.set_ylabel("Voltage out (V)")
    ax7.grid(True, alpha=0.3)

    # ── 8. Speed distribution histogram ──────────────────────────────────────
    ax8 = fig.add_subplot(gs[2, 1])
    moving = df[df["speed_kph"] > 1.0]["speed_kph"]
    ax8.hist(moving, bins=25, color="#607D8B", edgecolor="white", linewidth=0.5)
    ax8.axvline(moving.mean(), color="red", linestyle="--", linewidth=1.0,
                label=f"Mean {moving.mean():.1f} km/h")
    ax8.set_title("Speed Distribution\n(moving only, > 1 km/h)")
    ax8.set_xlabel("km/h")
    ax8.set_ylabel("Count")
    ax8.legend(fontsize=7)
    ax8.grid(True, alpha=0.3)

    # ── 9. Torque vs Physical Motor Power scatter (verify actual terrain) ─────
    ax9 = fig.add_subplot(gs[2, 2])
    if "motor_power_w" in df.columns and df["motor_power_w"].notna().any():
        sc9 = ax9.scatter(df["torque_nm"], df["motor_power_w"],
                         c=df["speed_kph"], cmap="plasma", s=8, alpha=0.6)
        plt.colorbar(sc9, ax=ax9, label="Speed (km/h)")
        ax9.set_title("Leg Torque vs Motor Power (W)\n(Actual Thermodynamic Effort)")
        ax9.set_ylabel("Motor Power (Watts)")
    else:
        ax9.text(0.5, 0.5, "No Motor Power Logged", transform=ax9.transAxes,
                 ha="center", va="center", color="grey")
        ax9.set_title("Leg Torque vs Motor Power (W)")
        
    ax9.set_xlabel("Torque (Nm)")
    ax9.grid(True, alpha=0.3)

    plt.savefig(os.path.join(os.path.dirname(__file__), f"{ride_id}_analysis.png"),
                dpi=150, bbox_inches="tight")
    print(f"Plot saved: {ride_id}_analysis.png")
    plt.show()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    target_ride_id = sys.argv[1] if len(sys.argv) > 1 else None

    df, ride_id = fetch_ride(target_ride_id)
    print_summary(df, ride_id)
    plot_ride(df, ride_id)
