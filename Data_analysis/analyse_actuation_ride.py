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
import numpy as np
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

    ax.set_xlabel("Elapsed (min)", fontsize=13)
    ax.set_ylabel("Avg rider leg power (W)", fontsize=13)
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


def list_qualifying_rides(min_duration_min=5):
    """
    Return a DataFrame of all actuation rides longer than min_duration_min,
    sorted by ride_id. Fetches only ride_id + timestamp to stay efficient.
    """
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    print(f"Fetching ride index from {TABLE}...")
    all_rows = []
    page, page_size = 0, 1000
    while True:
        result = (
            sb.table(TABLE)
            .select("ride_id,timestamp")
            .order("timestamp")
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        )
        all_rows.extend(result.data)
        if len(result.data) < page_size:
            break
        page += 1

    meta = pd.DataFrame(all_rows)
    meta["timestamp"] = pd.to_datetime(meta["timestamp"])
    durations = meta.groupby("ride_id")["timestamp"].agg(
        lambda x: (x.max() - x.min()).total_seconds() / 60
    )
    qualifying = (
        durations[durations >= min_duration_min]
        .reset_index()
        .rename(columns={"timestamp": "duration_min"})
        .sort_values("ride_id")
        .reset_index(drop=True)
    )
    print(f"  {len(qualifying)} rides >= {min_duration_min} min  "
          f"(from {len(durations)} total in table)\n")
    return qualifying


def plot_sweat_validation(df, ride_id, bin_seconds=30):
    """
    Mirror of plot_power_reduction: average sweat rate per time bin,
    split at the ML trigger. Uses sweat_rate_l_hr if logged; otherwise
    estimates rate from the derivative of cumulative fluid_loss_l.
    """
    if "fluid_loss_l" not in df.columns or df["fluid_loss_l"].isna().all():
        print(f"No fluid loss data for {ride_id} — skipping sweat validation plot.")
        return

    trigger_min = None
    if "sweat_reduction_active" in df.columns and df["sweat_reduction_active"].any():
        trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]
    if trigger_min is None:
        print("No actuation trigger — skipping sweat validation plot.")
        return

    df = df.copy()

    if "sweat_rate_l_hr" in df.columns and df["sweat_rate_l_hr"].notna().sum() > 10:
        df["sweat_signal"] = pd.to_numeric(df["sweat_rate_l_hr"], errors="coerce")
    else:
        dt_hr = df["elapsed_min"].diff() / 60.0
        dl    = df["fluid_loss_l"].diff()
        df["sweat_signal"] = (dl / dt_hr).clip(lower=0)

    bin_min = bin_seconds / 60.0
    df["bin"] = (df["elapsed_min"] / bin_min).apply(int) * bin_min
    binned = (
        df.groupby("bin")["sweat_signal"]
        .mean()
        .reset_index()
        .rename(columns={"bin": "bin_start_min", "sweat_signal": "avg_sweat_rate"})
    )

    before = binned[binned["bin_start_min"] <  trigger_min]
    after  = binned[binned["bin_start_min"] >= trigger_min]

    fig, ax = plt.subplots(figsize=(12, 5))
    bar_width = bin_min * 0.85

    ax.bar(before["bin_start_min"], before["avg_sweat_rate"],
           width=bar_width, align='edge',
           color=plot_style.PRIMARY, alpha=0.55, edgecolor='white', linewidth=0.4,
           label='Before actuation')
    ax.bar(after["bin_start_min"], after["avg_sweat_rate"],
           width=bar_width, align='edge',
           color=plot_style.ACCENT, alpha=0.55, edgecolor='white', linewidth=0.4,
           label='After actuation')

    ax.set_xlim(left=0)
    ax.axvline(trigger_min, color=plot_style.NEUTRAL, linestyle='--',
               linewidth=1.2, label=f'ML trigger ({trigger_min:.1f} min)')

    x_max = df["elapsed_min"].max()
    pre_mean = post_mean = None
    if not before.empty:
        pre_mean = before["avg_sweat_rate"].mean()
        ax.plot([0, trigger_min], [pre_mean, pre_mean],
                color=plot_style.PRIMARY, linestyle='-', linewidth=2.2,
                zorder=3, label='Pre mean')
    if not after.empty:
        post_mean = after["avg_sweat_rate"].mean()
        ax.plot([trigger_min, x_max], [post_mean, post_mean],
                color=plot_style.ACCENT, linestyle='-', linewidth=2.2,
                zorder=3, label='Post mean')

    ax.set_xlabel("Elapsed (min)", fontsize=13)
    ax.set_ylabel("Sweat rate (L/hr)", fontsize=13)
    ax.legend(loc='upper right', fontsize=9)

    if pre_mean is not None and post_mean is not None:
        delta = post_mean - pre_mean
        pct   = f"{delta/pre_mean*100:+.1f}%" if pre_mean > 0 else "n/a (pre=0)"
        print(f"\n  Pre-actuation avg sweat rate  : {pre_mean:.4f} L/hr")
        print(f"  Post-actuation avg sweat rate : {post_mean:.4f} L/hr")
        print(f"  Change                        : {delta:+.4f} L/hr  ({pct})\n")

    plt.tight_layout()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               f"{ride_id}_sweat_validation.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Plot saved: {output_path}")


def plot_counterfactual_projection(df, ride_id):
    """
    Fit a linear trend to pre-actuation cumulative fluid loss, project it
    forward as a counterfactual (no actuation), and overlay the actual
    post-actuation trajectory. The shaded gap = fluid loss avoided.
    """
    if "fluid_loss_l" not in df.columns or df["fluid_loss_l"].isna().all():
        print(f"No fluid loss data for {ride_id} — skipping counterfactual plot.")
        return

    trigger_min = None
    if "sweat_reduction_active" in df.columns and df["sweat_reduction_active"].any():
        trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]
    if trigger_min is None:
        print("No actuation trigger — skipping counterfactual plot.")
        return

    fluid = df.dropna(subset=["fluid_loss_l"]).copy()
    pre   = fluid[fluid["elapsed_min"] <  trigger_min]
    post  = fluid[fluid["elapsed_min"] >= trigger_min]

    if len(pre) < 5:
        print("Too few pre-actuation fluid loss points — skipping counterfactual plot.")
        return

    coeffs = np.polyfit(pre["elapsed_min"], pre["fluid_loss_l"], 1)
    slope  = coeffs[0]   # L/min

    t_end   = fluid["elapsed_min"].max()
    t_proj  = np.linspace(trigger_min, t_end, 300)
    cf_proj = np.polyval(coeffs, t_proj)

    actual_end    = post["fluid_loss_l"].iloc[-1] if not post.empty else np.nan
    projected_end = float(np.polyval(coeffs, t_end))
    avoided_ml    = (projected_end - actual_end) * 1000

    fig, ax = plt.subplots(figsize=(10, 5))

    # Actual trace
    ax.plot(fluid["elapsed_min"], fluid["fluid_loss_l"],
            color=plot_style.PRIMARY, linewidth=2.0,
            label='Actual fluid loss', zorder=3)

    # Pre-actuation linear fit (extended to trigger for continuity)
    t_fit = np.linspace(float(pre["elapsed_min"].min()), trigger_min, 100)
    ax.plot(t_fit, np.polyval(coeffs, t_fit),
            color=plot_style.NEUTRAL, linestyle='--', linewidth=1.2)

    # Counterfactual projection
    ax.plot(t_proj, cf_proj,
            color=plot_style.NEUTRAL, linestyle=':', linewidth=1.8,
            label='Projected without actuation')

    # Shaded gap
    if not post.empty:
        t_actual  = post["elapsed_min"].values
        cf_actual = np.polyval(coeffs, t_actual)
        mask = cf_actual > post["fluid_loss_l"].values
        ax.fill_between(t_actual, post["fluid_loss_l"].values, cf_actual,
                        where=mask, color=plot_style.ACCENT, alpha=0.20,
                        label='Fluid loss avoided')

    # ML trigger — vertical line with direct text annotation
    ax.axvline(trigger_min, color=plot_style.NEUTRAL, linestyle='--', linewidth=1.2)
    ax.text(trigger_min + 0.3, ax.get_ylim()[1] * 0.97,
            f'ML trigger\n({trigger_min:.1f} min)',
            fontsize=8, va='top', color=plot_style.NEUTRAL)

    # Sweat threshold — horizontal line with direct text annotation
    ax.axhline(FLUID_THRESHOLD_L, color=plot_style.ACCENT, linestyle=':',
               linewidth=1.0, alpha=0.8)
    ax.text(0.4, FLUID_THRESHOLD_L + 0.008,
            f'Sweat threshold ({FLUID_THRESHOLD_L} L)',
            fontsize=8, va='bottom', color=plot_style.ACCENT)

    ax.set_xlabel("Elapsed (min)", fontsize=13)
    ax.set_ylabel("Cumulative fluid loss (L)", fontsize=13)
    ax.set_xlim(left=0)
    ax.legend(loc='upper left', fontsize=9)

    if not np.isnan(avoided_ml):
        print(f"\n  Pre-actuation sweat slope     : {slope*1000:.2f} mL/min")
        print(f"  Projected end-of-ride loss    : {projected_end:.3f} L")
        print(f"  Actual end-of-ride loss       : {actual_end:.3f} L")
        print(f"  Estimated fluid loss avoided  : {avoided_ml:.0f} mL\n")

    plt.tight_layout()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               f"{ride_id}_counterfactual.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Plot saved: {output_path}")


def plot_multi_ride_sweat(all_rides):
    """
    Overlay sweat-rate trajectories from multiple actuation rides, with time
    normalised so t=0 is the ML trigger for each ride. Shows individual ride
    traces plus a mean curve across all rides.
    all_rides: list of (df, ride_id) tuples.
    """
    T_PRE  = 12   # minutes before trigger to show
    T_POST = 20   # minutes after trigger to show
    SMOOTH = 90   # rolling-average window in seconds (1 Hz data)

    fig, ax = plt.subplots(figsize=(11, 5))
    valid_segments = []

    colours = [plot_style.PRIMARY, plot_style.ACCENT, plot_style.LIGHT_BLUE,
               plot_style.NEUTRAL, '#6B8E23', '#8B008B']

    for i, (df, ride_id) in enumerate(all_rides):
        if ("sweat_rate_l_hr" not in df.columns or
                df["sweat_rate_l_hr"].isna().all()):
            continue
        if ("sweat_reduction_active" not in df.columns or
                not df["sweat_reduction_active"].any()):
            continue

        trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]
        d = df.copy()
        d["t_rel"]  = d["elapsed_min"] - trigger_min
        d["sr"]     = pd.to_numeric(d["sweat_rate_l_hr"], errors="coerce")
        d["sr_smooth"] = d["sr"].rolling(SMOOTH, min_periods=1, center=True).mean()

        seg = d[(d["t_rel"] >= -T_PRE) & (d["t_rel"] <= T_POST)].dropna(subset=["sr_smooth"])
        if seg.empty:
            continue

        colour = colours[i % len(colours)]
        ax.plot(seg["t_rel"], seg["sr_smooth"],
                color=colour, linewidth=1.2, alpha=0.5,
                label=ride_id[-15:])
        valid_segments.append(seg[["t_rel", "sr_smooth"]].copy())

    if len(valid_segments) >= 2:
        t_grid = np.linspace(-T_PRE, T_POST, 400)
        matrix = np.array([
            np.interp(t_grid, seg["t_rel"].values, seg["sr_smooth"].values,
                      left=np.nan, right=np.nan)
            for seg in valid_segments
        ])
        mean_curve = np.nanmean(matrix, axis=0)
        ax.plot(t_grid, mean_curve,
                color='black', linewidth=2.4, zorder=5,
                label=f'Mean  (n={len(valid_segments)})')

    ax.axvline(0, color=plot_style.NEUTRAL, linestyle='--',
               linewidth=1.2, label='ML trigger  (t = 0)')
    ax.set_xlabel("Time relative to ML trigger (min)", fontsize=13)
    ax.set_ylabel("Sweat rate (L/hr)", fontsize=13)
    ax.set_xlim(-T_PRE, T_POST)
    ax.legend(loc='upper right', fontsize=9)

    plt.tight_layout()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "multi_ride_sweat_overlay.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Multi-ride sweat overlay saved: {output_path}")


def plot_multi_ride_fluid_loss(all_rides):
    """
    Multi-ride fluid loss overlay normalised to t=0 at the ML trigger.
    Each ride's cumulative fluid loss is shifted so it equals 0 at trigger time,
    showing pre-trigger buildup rate and post-trigger trajectory on a common axis.
    A dashed counterfactual projects the mean pre-trigger slope forward to show
    what would have accumulated without actuation.
    """
    T_PRE  = 10   # minutes before trigger to show
    T_POST = 18   # minutes after trigger to show

    fig, ax = plt.subplots(figsize=(11, 5))

    colours = [plot_style.PRIMARY, plot_style.ACCENT, plot_style.LIGHT_BLUE,
               '#6B8E5E', '#8B6098']

    pre_slopes   = []
    valid_segs   = []

    for i, (df, ride_id) in enumerate(all_rides):
        if "fluid_loss_l" not in df.columns or df["fluid_loss_l"].isna().all():
            continue
        if not ("sweat_reduction_active" in df.columns and
                df["sweat_reduction_active"].any()):
            continue

        trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]
        fluid       = pd.to_numeric(df["fluid_loss_l"], errors="coerce")

        # Fluid loss at trigger moment (interpolated)
        fluid_at_trigger = float(np.interp(
            trigger_min, df["elapsed_min"].values, fluid.ffill().values
        ))

        d = df.copy()
        d["t_rel"]    = d["elapsed_min"] - trigger_min
        d["fl_delta"] = fluid - fluid_at_trigger   # 0 at trigger

        seg = d[(d["t_rel"] >= -T_PRE) & (d["t_rel"] <= T_POST)].dropna(subset=["fl_delta"])
        if seg.empty:
            continue

        # Fit pre-trigger slope (mL/min) for counterfactual
        pre_seg = seg[seg["t_rel"] < 0]
        if len(pre_seg) >= 5:
            slope = np.polyfit(pre_seg["t_rel"], pre_seg["fl_delta"], 1)[0]
            pre_slopes.append(slope)

        colour = colours[i % len(colours)]
        ax.plot(seg["t_rel"], seg["fl_delta"],
                color=colour, linewidth=1.3, alpha=0.45)
        valid_segs.append(seg[["t_rel", "fl_delta"]].copy())

    if not valid_segs:
        print("No valid rides for multi-ride fluid loss plot.")
        plt.close(fig)
        return

    # Mean curve across all rides
    t_grid = np.linspace(-T_PRE, T_POST, 400)
    matrix = np.array([
        np.interp(t_grid, s["t_rel"].values, s["fl_delta"].values,
                  left=np.nan, right=np.nan)
        for s in valid_segs
    ])
    mean_curve = np.nanmean(matrix, axis=0)
    ax.plot(t_grid, mean_curve,
            color='black', linewidth=2.4, zorder=5,
            label=f'Mean  (n={len(valid_segs)})')

    # Counterfactual: project mean pre-trigger slope forward from t=0
    if pre_slopes:
        mean_slope = float(np.mean(pre_slopes))   # L/min
        t_cf  = np.linspace(0, T_POST, 200)
        cf    = mean_slope * t_cf
        ax.plot(t_cf, cf,
                color=plot_style.NEUTRAL, linewidth=1.6, linestyle='--', zorder=4,
                label=f'Projected  ({mean_slope*1000:.1f} mL/min pre-trigger slope)')

        # Shade gap between projection and mean actual post-trigger
        t_post_mask = t_grid >= 0
        cf_on_grid  = mean_slope * t_grid[t_post_mask]
        actual_post = mean_curve[t_post_mask]
        valid_mask  = ~np.isnan(actual_post) & (cf_on_grid > actual_post)
        if valid_mask.any():
            ax.fill_between(t_grid[t_post_mask], actual_post, cf_on_grid,
                            where=valid_mask,
                            color=plot_style.ACCENT, alpha=0.15,
                            label='Fluid loss avoided (mean)')

    ax.axvline(0, color=plot_style.NEUTRAL, linestyle='--',
               linewidth=1.2, label='ML trigger  (t = 0)')
    ax.axhline(0, color='black', linewidth=0.5, alpha=0.3)

    ax.set_xlabel("Time relative to ML trigger (min)", fontsize=13)
    ax.set_ylabel("Fluid loss relative to trigger (L)", fontsize=13)
    ax.set_xlim(-T_PRE, T_POST)
    ax.legend(loc='upper left', fontsize=9)

    plt.tight_layout()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "multi_ride_fluid_loss_overlay.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Multi-ride fluid loss overlay saved: {output_path}")


def plot_fluid_loss_summary(all_rides):
    """
    Bar chart: end-of-ride fluid loss per actuation ride, coloured by
    intervention mode — reactive (sweat already building) vs proactive
    (triggered before onset). Threshold line at FLUID_THRESHOLD_L.
    """
    import datetime
    REACTIVE_SR_THRESHOLD = 0.15   # L/hr pre-trigger — above this = reactive

    records = []
    for df, ride_id in all_rides:
        if "fluid_loss_l" not in df.columns or df["fluid_loss_l"].isna().all():
            continue
        fluid = pd.to_numeric(df["fluid_loss_l"], errors="coerce").dropna()
        if fluid.empty:
            continue
        end_val = float(fluid.iloc[-1])

        reactive = False
        if "sweat_reduction_active" in df.columns and df["sweat_reduction_active"].any():
            trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]
            pre_sr = pd.to_numeric(
                df.loc[df["elapsed_min"] < trigger_min, "sweat_rate_l_hr"],
                errors="coerce"
            ).mean()
            reactive = (not pd.isna(pre_sr)) and (pre_sr >= REACTIVE_SR_THRESHOLD)

        records.append({"end_loss": end_val, "reactive": reactive})

    if not records:
        print("No data for fluid loss summary.")
        return

    fig, ax = plt.subplots(figsize=(7, 4.2))
    x       = list(range(len(records)))
    colours = [plot_style.PRIMARY if r["reactive"] else plot_style.LIGHT_BLUE
               for r in records]

    bars = ax.bar(x, [r["end_loss"] for r in records],
                  color=colours, alpha=0.72, edgecolor='white', linewidth=0.5,
                  width=0.55)

    ax.axhline(FLUID_THRESHOLD_L, color=plot_style.ACCENT, linestyle='--',
               linewidth=1.4, label=f'Sweat threshold ({FLUID_THRESHOLD_L} L)')

    ax.set_xticks(x)
    ax.set_xticklabels([str(i + 1) for i in x], fontsize=11)
    ax.set_xlabel("Ride", fontsize=13)
    ax.set_ylabel("End-of-ride fluid loss (L)", fontsize=13)
    ax.set_ylim(0, max(r["end_loss"] for r in records) * 1.3)

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor=plot_style.PRIMARY,    alpha=0.72,
              label='Reactive — sweat building at trigger'),
        Patch(facecolor=plot_style.LIGHT_BLUE, alpha=0.72,
              label='Proactive — triggered before onset'),
        plt.Line2D([0], [0], color=plot_style.ACCENT, linestyle='--',
                   linewidth=1.4, label=f'Sweat threshold ({FLUID_THRESHOLD_L} L)'),
    ]
    legend = ax.legend(handles=legend_elements, fontsize=9, loc='upper right',
                       frameon=True, framealpha=0.92, edgecolor='#cccccc')

    plt.tight_layout()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "actuation_fluid_loss_summary.png")
    fig.savefig(output_path)
    plt.close(fig)
    print(f"Fluid loss summary saved: {output_path}")


def plot_sweat_grid(all_rides):
    """
    Diagnostic grid: one panel per ride showing raw sweat rate vs elapsed time
    with the actuation trigger marked. Used to visually inspect which rides are
    usable for validation.
    """
    n     = len(all_rides)
    ncols = 3
    nrows = (n + ncols - 1) // ncols

    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4 * nrows),
                             sharey=False)
    axes = np.array(axes).flatten()

    for i, (df, ride_id) in enumerate(all_rides):
        ax = axes[i]

        fluid = pd.to_numeric(df.get("fluid_loss_l", pd.Series(dtype=float)),
                              errors="coerce")

        trigger_min = None
        if "sweat_reduction_active" in df.columns and df["sweat_reduction_active"].any():
            trigger_min = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]

        ax.plot(df["elapsed_min"], fluid,
                color=plot_style.PRIMARY, linewidth=1.4)
        if trigger_min is not None:
            ax.axvline(trigger_min, color=plot_style.ACCENT, linestyle='--',
                       linewidth=1.2, label=f'Trigger ({trigger_min:.1f} min)')
            ax.legend(fontsize=8)

        short = ride_id.replace("RIDE_", "")
        ax.set_title(short, fontsize=10, fontweight='bold')
        ax.set_xlabel("Elapsed (min)", fontsize=9)
        ax.set_ylabel("Fluid loss (L)", fontsize=9)
        ax.set_xlim(left=0)

    # Hide unused panels
    for j in range(n, len(axes)):
        axes[j].set_visible(False)

    plt.suptitle("Sweat rate diagnostic — all qualifying rides", fontsize=12,
                 fontweight='bold', y=1.01)
    plt.tight_layout()
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "sweat_diagnostic_grid.png")
    fig.savefig(output_path, bbox_inches='tight')
    plt.close(fig)
    print(f"Sweat diagnostic grid saved: {output_path}")


def print_multi_ride_stats(all_rides):
    """
    Print a per-ride table and aggregate statistics across all actuation rides.
    Covers duration, temperature, humidity, trigger time, leg power, fluid loss,
    and sweat rate — everything needed for a results write-up.
    """
    rows = []
    for df, ride_id in all_rides:
        r = {"ride_id": ride_id}

        # Duration
        r["duration_min"] = df["elapsed_min"].max()

        # Trigger time
        r["trigger_min"] = None
        if "sweat_reduction_active" in df.columns and df["sweat_reduction_active"].any():
            r["trigger_min"] = df.loc[df["sweat_reduction_active"], "elapsed_min"].iloc[0]

        # Trigger as % of ride
        r["trigger_pct"] = (r["trigger_min"] / r["duration_min"] * 100
                            if r["trigger_min"] is not None else None)

        # Environment (whole-ride mean)
        r["temp_c"]      = df["temp_c"].mean()     if "temp_c"       in df.columns else None
        r["humidity_pct"]= df["humidity_pct"].mean()if "humidity_pct" in df.columns else None

        # Speed
        r["avg_speed_kph"] = df["speed_kph"].mean() if "speed_kph" in df.columns else None
        r["max_speed_kph"] = df["speed_kph"].max()  if "speed_kph" in df.columns else None

        # Leg power before / after trigger
        df2 = df.copy()
        df2["leg_power_w"] = (pd.to_numeric(df2["torque_nm"], errors="coerce") *
                              pd.to_numeric(df2["rpm"],       errors="coerce") * 0.10472)
        if r["trigger_min"] is not None:
            pre  = df2.loc[df2["elapsed_min"] <  r["trigger_min"], "leg_power_w"]
            post = df2.loc[df2["elapsed_min"] >= r["trigger_min"], "leg_power_w"]
            r["pre_leg_power_w"]  = pre.mean()
            r["post_leg_power_w"] = post.mean()
        else:
            r["pre_leg_power_w"] = r["post_leg_power_w"] = None

        # Fluid loss
        if "fluid_loss_l" in df.columns and df["fluid_loss_l"].notna().any():
            fluid = pd.to_numeric(df["fluid_loss_l"], errors="coerce").dropna()
            r["end_fluid_loss_l"] = float(fluid.iloc[-1]) if not fluid.empty else None
        else:
            r["end_fluid_loss_l"] = None

        # Sweat rate before / after trigger
        if "sweat_rate_l_hr" in df.columns and r["trigger_min"] is not None:
            sr = pd.to_numeric(df["sweat_rate_l_hr"], errors="coerce")
            r["pre_sweat_rate_l_hr"]  = sr[df["elapsed_min"] <  r["trigger_min"]].mean()
            r["post_sweat_rate_l_hr"] = sr[df["elapsed_min"] >= r["trigger_min"]].mean()
        else:
            r["pre_sweat_rate_l_hr"] = r["post_sweat_rate_l_hr"] = None

        rows.append(r)

    if not rows:
        return

    W = 72
    print("\n" + "=" * W)
    print("  MULTI-RIDE ACTUATION SUMMARY")
    print("=" * W)

    # Per-ride table
    hdr = f"  {'Ride':<22} {'Dur':>5} {'Trig':>5} {'Trig%':>6} {'Temp':>5} {'RH':>5} {'Pre-LP':>7} {'Post-LP':>8} {'FL(L)':>6}"
    print(hdr)
    print("  " + "-" * (W - 2))
    for r in rows:
        short = r["ride_id"].replace("RIDE_", "")
        trig  = f"{r['trigger_min']:.1f}"   if r["trigger_min"]       is not None else "—"
        tpct  = f"{r['trigger_pct']:.0f}%"  if r["trigger_pct"]       is not None else "—"
        temp  = f"{r['temp_c']:.1f}"        if r["temp_c"]            is not None else "—"
        rh    = f"{r['humidity_pct']:.0f}"  if r["humidity_pct"]      is not None else "—"
        prelp = f"{r['pre_leg_power_w']:.0f}"  if r["pre_leg_power_w"]  is not None else "—"
        polp  = f"{r['post_leg_power_w']:.0f}" if r["post_leg_power_w"] is not None else "—"
        fl    = f"{r['end_fluid_loss_l']:.3f}" if r["end_fluid_loss_l"] is not None else "—"
        print(f"  {short:<22} {r['duration_min']:>5.1f} {trig:>5} {tpct:>6} "
              f"{temp:>5} {rh:>5} {prelp:>7} {polp:>8} {fl:>6}")

    print("  " + "-" * (W - 2))

    # Aggregate stats
    def _mean(key):
        vals = [r[key] for r in rows if r[key] is not None and not pd.isna(r[key])]
        return (sum(vals) / len(vals), min(vals), max(vals)) if vals else (None, None, None)

    def _fmt(tup, decimals=1):
        if tup[0] is None:
            return "—"
        return f"{tup[0]:.{decimals}f}  (range {tup[1]:.{decimals}f}–{tup[2]:.{decimals}f})"

    dur   = _mean("duration_min")
    trig  = _mean("trigger_min")
    tpct  = _mean("trigger_pct")
    temp  = _mean("temp_c")
    rh    = _mean("humidity_pct")
    spd   = _mean("avg_speed_kph")
    prelp = _mean("pre_leg_power_w")
    polp  = _mean("post_leg_power_w")
    fl    = _mean("end_fluid_loss_l")
    presr = _mean("pre_sweat_rate_l_hr")
    posr  = _mean("post_sweat_rate_l_hr")

    print(f"\n  Rides included            : {len(rows)}")
    print(f"  Avg duration              : {_fmt(dur)} min")
    print(f"  Avg trigger time          : {_fmt(trig)} min")
    print(f"  Avg trigger as % of ride  : {_fmt(tpct, 0)}%")
    print(f"  Avg temperature           : {_fmt(temp)} °C")
    print(f"  Avg humidity              : {_fmt(rh, 0)} %RH")
    print(f"  Avg speed                 : {_fmt(spd)} km/h")
    print(f"  Avg pre-trigger leg power : {_fmt(prelp, 0)} W")
    print(f"  Avg post-trigger leg power: {_fmt(polp, 0)} W")
    if prelp[0] and polp[0]:
        delta = polp[0] - prelp[0]
        print(f"  Avg leg power change      : {delta:+.0f} W  ({delta/prelp[0]*100:+.1f}%)")
    print(f"  Avg end-of-ride fluid loss: {_fmt(fl, 3)} L")
    print(f"  Avg pre-trigger sweat rate: {_fmt(presr, 4)} L/hr")
    print(f"  Avg post-trigger sweat rate:{_fmt(posr, 4)} L/hr")
    print("=" * W + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sweat-grid":
        # ── Quick visual diagnostic across all qualifying rides ───────────────
        qualifying = list_qualifying_rides(min_duration_min=5)
        all_rides  = []
        for _, row in qualifying.iterrows():
            try:
                df, ride_id = fetch_ride(row["ride_id"])
                all_rides.append((df, ride_id))
            except Exception as e:
                print(f"  Error fetching {row['ride_id']}: {e}")
        plot_sweat_grid(all_rides)

    elif len(sys.argv) > 1 and sys.argv[1] == "--all-sweat":
        # ── Multi-ride sweat validation ─────────────────────────────────────
        # 154715 excluded: 62% data coverage due to a 308 s gap mid-ride.
        EXCLUDE_RIDES = {"RIDE_20260526_154715"}

        qualifying = list_qualifying_rides(min_duration_min=5)
        all_rides  = []
        for _, row in qualifying.iterrows():
            if row["ride_id"] in EXCLUDE_RIDES:
                print(f"--- {row['ride_id']}  — excluded (data quality)")
                continue
            try:
                df, ride_id = fetch_ride(row["ride_id"])
                if not ("sweat_reduction_active" in df.columns and
                        df["sweat_reduction_active"].any()):
                    print(f"--- {ride_id}  — no actuation trigger, skipped")
                    continue
                print(f"--- {ride_id}  ({row['duration_min']:.1f} min) ---")
                plot_sweat_validation(df, ride_id)
                plot_counterfactual_projection(df, ride_id)
                all_rides.append((df, ride_id))
            except Exception as e:
                print(f"  Error processing {row['ride_id']}: {e}")
        if len(all_rides) >= 2:
            plot_multi_ride_sweat(all_rides)
            plot_multi_ride_fluid_loss(all_rides)
            plot_fluid_loss_summary(all_rides)
        print_multi_ride_stats(all_rides)
        print(f"\nDone — {len(all_rides)} actuation rides.")
    else:
        # ── Single ride (default / explicit ride ID) ─────────────────────────
        target = sys.argv[1] if len(sys.argv) > 1 else None
        df, ride_id = fetch_ride(target)
        print_summary(df, ride_id)
        plot_ride(df, ride_id)
        plot_power_reduction(df, ride_id)
        plot_sweat_validation(df, ride_id)
        plot_counterfactual_projection(df, ride_id)
