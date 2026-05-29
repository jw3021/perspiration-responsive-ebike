#!/usr/bin/env python3
"""
Analyse Actuation Ride — Pull the most recent actuation ride from Supabase
and produce a dashboard focused on ML prediction vs actual sweat onset.

Usage:
    python analyse_actuation_ride.py              # latest actuation ride
    python analyse_actuation_ride.py RIDE_20260526_153652  # specific ride ID
"""

import sys
import os
import re
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import plot_style
plot_style.apply()

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

FLUID_THRESHOLD_L    = 0.17
DECISION_THRESHOLD   = 0.20
TABLE                = "actuation_ride_metrics_v1"


def fetch_ride(ride_id=None):
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    if ride_id is None:
        result = (
            sb.table(TABLE)
            .select("ride_id")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise RuntimeError(f"No rides found in {TABLE}.")
        ride_id = result.data[0]["ride_id"]
        print(f"Most recent actuation ride: {ride_id}")

    all_rows = []
    page, page_size = 0, 1000
    while True:
        result = (
            sb.table(TABLE)
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
        raise RuntimeError(f"No data found for ride_id '{ride_id}' in {TABLE}.")

    df = pd.DataFrame(all_rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["elapsed_min"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds() / 60.0

    for col in ["torque_nm", "speed_kph", "rpm", "voltage_out", "temp_c",
                "humidity_pct", "fluid_loss_l", "ml_sweat_probability",
                "sweat_rate_l_hr", "motor_power_w"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "sweat_reduction_active" in df.columns:
        df["sweat_reduction_active"] = df["sweat_reduction_active"].astype(str).str.lower() == "true"

    print(f"Fetched {len(df)} rows  |  Duration: {df['elapsed_min'].max():.1f} min  |  Ride: {ride_id}")

    # Check for gaps > 5 seconds
    gaps = df["timestamp"].diff().dt.total_seconds()
    big_gaps = gaps[gaps > 5].dropna()
    if not big_gaps.empty:
        print(f"\n  ⚠️  Data gaps detected (>{5}s):")
        for idx, g in big_gaps.items():
            print(f"     @ {df.loc[idx, 'elapsed_min']:.1f} min — gap of {g:.0f}s")
    else:
        print("  ✅ No significant data gaps.")

    expected_rows = int(df["elapsed_min"].max() * 60)
    coverage = len(df) / expected_rows * 100 if expected_rows > 0 else 100
    print(f"  Row coverage: {len(df)}/{expected_rows} expected ({coverage:.0f}%)\n")

    return df, ride_id


def print_summary(df, ride_id):
    duration_min   = df["elapsed_min"].max()
    fluid_max      = df["fluid_loss_l"].max() if df["fluid_loss_l"].notna().any() else None
    triggered      = df["sweat_reduction_active"].any() if "sweat_reduction_active" in df.columns else False

    # Trigger time
    trigger_min = None
    if triggered:
        trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]

    # Fluid threshold crossing time
    fluid_cross_min = None
    if fluid_max is not None and fluid_max >= FLUID_THRESHOLD_L:
        cross = df.loc[df["fluid_loss_l"] >= FLUID_THRESHOLD_L, "elapsed_min"]
        if not cross.empty:
            fluid_cross_min = cross.iloc[0]

    print("\n" + "=" * 55)
    print(f"  ACTUATION RIDE SUMMARY  —  {ride_id}")
    print("=" * 55)
    print(f"  Duration              : {duration_min:.1f} min")
    print(f"  Rows logged           : {len(df)}")
    print(f"  Max speed             : {df['speed_kph'].max():.1f} km/h")
    print(f"  Avg torque (active)   : {df.loc[df['torque_nm']>5,'torque_nm'].mean():.1f} Nm")
    print(f"  Ambient temp          : {df['temp_c'].mean():.1f} °C avg")
    print(f"  Humidity              : {df['humidity_pct'].mean():.1f}% avg")
    if fluid_max is not None:
        print(f"  Total fluid loss      : {fluid_max:.3f} L  (threshold: {FLUID_THRESHOLD_L} L)")
    print(f"  Sweat reduction fired : {'YES' if triggered else 'NO'}")
    if trigger_min is not None:
        print(f"  ML trigger time       : {trigger_min:.1f} min")
    if fluid_cross_min is not None:
        print(f"  Fluid threshold cross : {fluid_cross_min:.1f} min")
    if trigger_min is not None and fluid_cross_min is not None:
        lead = fluid_cross_min - trigger_min
        print(f"  Lead time             : {lead:+.1f} min  ({'early' if lead > 0 else 'late'})")
    print("=" * 55 + "\n")


def plot_ride(df, ride_id):
    x = df["elapsed_min"]

    # Work out key events for vertical reference lines
    trigger_min = None
    if "sweat_reduction_active" in df.columns and df["sweat_reduction_active"].any():
        trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]

    fluid_cross_min = None
    if df["fluid_loss_l"].notna().any() and df["fluid_loss_l"].max() >= FLUID_THRESHOLD_L:
        cross = df.loc[df["fluid_loss_l"] >= FLUID_THRESHOLD_L, "elapsed_min"]
        if not cross.empty:
            fluid_cross_min = cross.iloc[0]

    fig = plt.figure(figsize=(16, 14))
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.50, wspace=0.38)

    def vlines(ax):
        """Add trigger and fluid-threshold crossing lines to any axis."""
        if trigger_min is not None:
            ax.axvline(trigger_min, color=plot_style.ACCENT, linestyle='--',
                       linewidth=1.0, label='ML trigger')
        if fluid_cross_min is not None:
            ax.axvline(fluid_cross_min, color=plot_style.PRIMARY, linestyle=':',
                       linewidth=1.0, label='Fluid threshold crossed')

    # ── 1. ML probability over time ──────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :2])   # spans two columns — most important panel
    if "ml_sweat_probability" in df.columns:
        ax1.plot(x, df["ml_sweat_probability"], color=plot_style.PRIMARY,
                 linewidth=1.8, label='ML probability')
        ax1.axhline(DECISION_THRESHOLD, color=plot_style.NEUTRAL, linestyle='--',
                    linewidth=1.2, label=f'Decision threshold ({DECISION_THRESHOLD})')
        if "sweat_reduction_active" in df.columns:
            ax1.fill_between(x, 0, df["sweat_reduction_active"].astype(float),
                             color=plot_style.ACCENT, alpha=0.12, label='Sweat reduction active')
    vlines(ax1)
    ax1.set_xlabel("Elapsed (min)")
    ax1.set_ylabel("Predicted probability")
    ax1.set_ylim(-0.05, 1.05)
    ax1.legend(loc='upper left', fontsize=8)

    # ── 2. Fluid loss vs threshold ───────────────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 2])
    fluid_data = df.dropna(subset=["fluid_loss_l"])
    if not fluid_data.empty:
        ax2.plot(fluid_data["elapsed_min"], fluid_data["fluid_loss_l"],
                 color=plot_style.PRIMARY, linewidth=1.8, label='Fluid loss (L)')
        ax2.fill_between(fluid_data["elapsed_min"], fluid_data["fluid_loss_l"],
                         alpha=0.12, color=plot_style.PRIMARY)
        ax2.axhline(FLUID_THRESHOLD_L, color=plot_style.ACCENT, linestyle='--',
                    linewidth=1.2, label=f'Threshold ({FLUID_THRESHOLD_L} L)')
    else:
        ax2.text(0.5, 0.5, "No HDrop data", transform=ax2.transAxes,
                 ha="center", va="center", color=plot_style.NEUTRAL)
    vlines(ax2)
    ax2.set_xlabel("Elapsed (min)")
    ax2.set_ylabel("Litres")
    ax2.legend(loc='upper left', fontsize=8)

    # ── 3. Speed ─────────────────────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[1, 0])
    ax3.plot(x, df["speed_kph"], color=plot_style.PRIMARY, linewidth=1.4)
    ax3.axhline(25.0, color=plot_style.NEUTRAL, linestyle='--', linewidth=1.0, label='25 km/h limit')
    vlines(ax3)
    ax3.set_xlabel("Elapsed (min)")
    ax3.set_ylabel("Speed (km/h)")
    ax3.legend(fontsize=8)

    # ── 4. Torque & voltage (dual axis) ──────────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 1])
    ax4.plot(x, df["torque_nm"], color=plot_style.PRIMARY, linewidth=1.4, label='Torque (Nm)')
    ax4.set_ylabel("Torque (Nm)")
    ax4b = ax4.twinx()
    ax4b.plot(x, df["voltage_out"], color=plot_style.ACCENT, linewidth=1.0,
              alpha=0.85, label='V_out')
    ax4b.set_ylabel("Motor voltage (V)")
    ax4b.spines['right'].set_visible(True)
    ax4b.spines['right'].set_color('#555555')
    ax4b.spines['right'].set_linewidth(0.8)
    lines1, labels1 = ax4.get_legend_handles_labels()
    lines2, labels2 = ax4b.get_legend_handles_labels()
    ax4.legend(lines1 + lines2, labels1 + labels2, fontsize=8)
    ax4.set_xlabel("Elapsed (min)")
    vlines(ax4)

    # ── 5. Temp & humidity ───────────────────────────────────────────────────
    ax5 = fig.add_subplot(gs[1, 2])
    ax5.plot(x, df["temp_c"], color=plot_style.PRIMARY, linewidth=1.4, label='Temp (°C)')
    ax5b = ax5.twinx()
    ax5b.plot(x, df["humidity_pct"], color=plot_style.ACCENT, linewidth=1.0,
              alpha=0.85, label='Humidity (%)')
    ax5b.set_ylabel("Humidity (%)")
    ax5b.spines['right'].set_visible(True)
    ax5b.spines['right'].set_color('#555555')
    ax5b.spines['right'].set_linewidth(0.8)
    lines1, labels1 = ax5.get_legend_handles_labels()
    lines2, labels2 = ax5b.get_legend_handles_labels()
    ax5.legend(lines1 + lines2, labels1 + labels2, fontsize=8)
    ax5.set_xlabel("Elapsed (min)")
    ax5.set_ylabel("Temp (°C)")

    # ── 6. Motor power ───────────────────────────────────────────────────────
    ax6 = fig.add_subplot(gs[2, 0])
    if "motor_power_w" in df.columns and df["motor_power_w"].notna().any():
        ax6.plot(x, df["motor_power_w"], color=plot_style.PRIMARY, linewidth=1.4)
        if trigger_min is not None:
            ax6.axvline(trigger_min, color=plot_style.ACCENT, linestyle='--', linewidth=1.0)
    else:
        ax6.text(0.5, 0.5, "No motor power data", transform=ax6.transAxes,
                 ha="center", va="center", color=plot_style.NEUTRAL)
    ax6.set_xlabel("Elapsed (min)")
    ax6.set_ylabel("Motor power (W)")

    # ── 7. Voltage distribution: LOW vs HIGH band ────────────────────────────
    ax7 = fig.add_subplot(gs[2, 1])
    if "power_band" in df.columns:
        low  = df.loc[df["power_band"] == "LOW",  "voltage_out"].dropna()
        high = df.loc[df["power_band"] == "HIGH", "voltage_out"].dropna()
        if not low.empty:
            ax7.hist(low,  bins=20, color=plot_style.PRIMARY, alpha=0.7,
                     label='Normal mode', edgecolor='none')
        if not high.empty:
            ax7.hist(high, bins=20, color=plot_style.ACCENT,  alpha=0.7,
                     label='Sweat reduction mode', edgecolor='none')
        ax7.legend(fontsize=8)
    ax7.set_xlabel("Voltage out (V)")
    ax7.set_ylabel("Count")

    # ── 8. Cadence ───────────────────────────────────────────────────────────
    ax8 = fig.add_subplot(gs[2, 2])
    ax8.plot(x, df["rpm"], color=plot_style.PRIMARY, linewidth=1.4)
    vlines(ax8)
    ax8.set_xlabel("Elapsed (min)")
    ax8.set_ylabel("Cadence (RPM)")

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               f"{ride_id}_actuation_analysis.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Plot saved: {output_path}")


def plot_power_reduction(df, ride_id, bin_seconds=30):
    """
    Second output plot: rider leg power in discrete time bins, split at the ML trigger.
    Leg power = torque_nm * rpm * 0.10472  (W)
    Shows whether the increased motor assist allowed the rider to reduce personal effort.
    """
    # Leg power (rider mechanical input)
    df = df.copy()
    df["leg_power_w"] = df["torque_nm"] * df["rpm"] * 0.10472

    # Work out trigger time
    trigger_min = None
    if "sweat_reduction_active" in df.columns and df["sweat_reduction_active"].any():
        trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]

    if trigger_min is None:
        print("No actuation trigger found — skipping power reduction plot.")
        return

    # Bin into discrete windows
    bin_min = bin_seconds / 60.0
    df["bin"] = (df["elapsed_min"] / bin_min).apply(int) * bin_min

    binned = (
        df.groupby("bin")["leg_power_w"]
        .mean()
        .reset_index()
        .rename(columns={"bin": "bin_start_min", "leg_power_w": "avg_leg_power_w"})
    )

    before = binned[binned["bin_start_min"] < trigger_min]
    after  = binned[binned["bin_start_min"] >= trigger_min]

    fig, ax = plt.subplots(figsize=(12, 5))

    bar_width = bin_min * 0.85

    ax.bar(before["bin_start_min"], before["avg_leg_power_w"],
           width=bar_width, align='edge',
           color=plot_style.PRIMARY, alpha=0.55, edgecolor='white', linewidth=0.4,
           label='Before actuation')
    ax.bar(after["bin_start_min"], after["avg_leg_power_w"],
           width=bar_width, align='edge',
           color=plot_style.ACCENT, alpha=0.55, edgecolor='white', linewidth=0.4,
           label='After actuation')

    ax.set_xlim(left=0)

    ax.axvline(trigger_min, color=plot_style.NEUTRAL, linestyle='--',
               linewidth=1.2, label=f'ML trigger ({trigger_min:.1f} min)')

    # Mean lines — same color as bars, solid, full opacity so they read as the mean of their group
    x_max = df["elapsed_min"].max()
    if not before.empty:
        pre_mean = before["avg_leg_power_w"].mean()
        ax.plot([0, trigger_min], [pre_mean, pre_mean],
                color=plot_style.PRIMARY, linestyle='-', linewidth=2.2,
                zorder=3, label='Pre mean')
    if not after.empty:
        post_mean = after["avg_leg_power_w"].mean()
        ax.plot([trigger_min, x_max], [post_mean, post_mean],
                color=plot_style.ACCENT, linestyle='-', linewidth=2.2,
                zorder=3, label='Post mean')

    ax.set_xlabel("Elapsed (min)", fontsize=12)
    ax.set_ylabel("Avg rider leg power (W)", fontsize=12)
    ax.legend(loc='upper right', fontsize=9)

    # Print stats
    if not before.empty and not after.empty:
        delta = post_mean - pre_mean
        print(f"\n  Pre-actuation avg leg power  : {pre_mean:.0f} W")
        print(f"  Post-actuation avg leg power : {post_mean:.0f} W")
        print(f"  Change                       : {delta:+.0f} W  ({delta/pre_mean*100:+.1f}%)\n")

    plt.tight_layout()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               f"{ride_id}_power_reduction.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Plot saved: {output_path}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    df, ride_id = fetch_ride(target)
    print_summary(df, ride_id)
    plot_ride(df, ride_id)
    plot_power_reduction(df, ride_id)
