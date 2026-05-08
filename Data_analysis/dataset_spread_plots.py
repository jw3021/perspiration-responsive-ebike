"""
dataset_spread_plots.py
-----------------------
Visual spread analysis of the collected ride dataset.

Produces:
  1. Box plots for key metrics (one box per ride, side by side)
  2. Histograms / KDE for ambient conditions (temp, humidity)
  3. Sweat rate vs temperature scatter — highlights coverage gaps

Saves all figures to Data_analysis/spread_plots/ and also displays them.

Run from any directory:
    python Data_analysis/dataset_spread_plots.py
"""

import sys
import os
import re
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

# --------------------------------------------------------------------------
# Supabase connection
# --------------------------------------------------------------------------
try:
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.py')
    with open(config_path, 'r') as f:
        config_text = f.read()

    SUPABASE_URL = re.search(r'SUPABASE_URL\s*=\s*["\']([^"\']+)["\']', config_text).group(1)
    SUPABASE_KEY = re.search(r'SUPABASE_KEY\s*=\s*["\']([^"\']+)["\']', config_text).group(1)

    from supabase import create_client
except Exception as e:
    print(f"Error loading config or supabase: {e}")
    sys.exit(1)


OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spread_plots")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_all_data(client):
    all_data = []
    chunk_size = 1000
    start = 0
    while True:
        response = client.table("ride_metrics_v2").select("*").range(start, start + chunk_size - 1).execute()
        data = response.data
        if not data:
            break
        all_data.extend(data)
        if len(data) < chunk_size:
            break
        start += chunk_size
    return pd.DataFrame(all_data)


def short_ride_label(ride_id: str) -> str:
    """Turn RIDE_20260330_155917 into '30 Mar\n15:59'."""
    try:
        parts = ride_id.split('_')
        date_str = parts[1]   # 20260330
        time_str = parts[2]   # 155917
        from datetime import datetime
        dt = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")
        return dt.strftime("%d %b\n%H:%M")
    except Exception:
        return ride_id[:8]


# --------------------------------------------------------------------------
# PLOT 1 — Box plots: key metrics, one box per ride
# --------------------------------------------------------------------------
def plot_boxplots(df: pd.DataFrame, ride_labels: dict):
    metrics = [
        ("temp_c",        "Ambient Temp (°C)"),
        ("humidity_pct",  "Humidity (%)"),
        ("skin_temp_c",   "Skin Temp (°C)"),
        ("sweat_rate_l_hr", "Sweat Rate (L/h)"),
        ("speed_kph",     "Speed (km/h)"),
        ("power_watts",   "Power (W)"),
        ("torque_nm",     "Torque (Nm)"),
    ]
    # Filter to metrics that actually exist in this dataset
    metrics = [(col, label) for col, label in metrics if col in df.columns]

    n = len(metrics)
    ncols = 3
    nrows = int(np.ceil(n / ncols))

    fig, axes = plt.subplots(nrows, ncols, figsize=(14, 4 * nrows))
    fig.suptitle("Distribution of Key Metrics — One Box per Ride", fontsize=14, fontweight='bold', y=1.01)
    axes = np.array(axes).flatten()

    ride_ids = sorted(df['ride_id'].unique())
    x_labels = [ride_labels.get(r, r[:8]) for r in ride_ids]

    for ax, (col, ylabel) in zip(axes, metrics):
        data_per_ride = [pd.to_numeric(df[df['ride_id'] == r][col], errors='coerce').dropna().values
                         for r in ride_ids]
        bp = ax.boxplot(data_per_ride, patch_artist=True, notch=False,
                        medianprops=dict(color='black', linewidth=2))
        colors = plt.cm.tab10(np.linspace(0, 1, len(ride_ids)))
        for patch, color in zip(bp['boxes'], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.7)
        ax.set_xticks([])
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(ylabel, fontsize=10)
        ax.grid(axis='y', alpha=0.3)

    # Hide any unused subplots
    for ax in axes[n:]:
        ax.set_visible(False)

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "01_boxplots_per_ride.png")
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"  Saved: {out}")
    plt.show()


# --------------------------------------------------------------------------
# PLOT 2 — Ambient condition histograms (temperature + humidity)
# --------------------------------------------------------------------------
def plot_ambient_histograms(df: pd.DataFrame):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    fig.suptitle("Ambient Condition Coverage", fontsize=13, fontweight='bold')

    for ax, col, xlabel, color, target_bins in [
        (axes[0], 'temp_c',       'Temperature (°C)', '#e07b39', range(0, 41, 5)),
        (axes[1], 'humidity_pct', 'Humidity (%)',     '#4a90d9', range(0, 101, 10)),
    ]:
        if col not in df.columns:
            ax.set_visible(False)
            continue

        series = pd.to_numeric(df[col], errors='coerce').dropna()

        # Histogram of raw data points
        ax.hist(series, bins=list(target_bins), color=color, alpha=0.65, edgecolor='white', label='Data points')

        # Overlay a per-ride mean marker
        for ride_id, grp in df.groupby('ride_id'):
            mean_val = pd.to_numeric(grp[col], errors='coerce').mean()
            ax.axvline(mean_val, color='black', linewidth=1, linestyle='--', alpha=0.5)

        ax.set_xlabel(xlabel, fontsize=10)
        ax.set_ylabel("Number of data points", fontsize=10)
        ax.set_title(f"{xlabel} distribution\n(dashed = per-ride mean)", fontsize=10)
        ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "02_ambient_histograms.png")
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"  Saved: {out}")
    plt.show()


# --------------------------------------------------------------------------
# PLOT 3 — Sweat rate vs ambient temperature (scatter, one point per minute)
# --------------------------------------------------------------------------
def plot_sweat_vs_temp(df: pd.DataFrame, ride_labels: dict):
    if 'sweat_rate_l_hr' not in df.columns or 'temp_c' not in df.columns:
        print("  Skipping sweat-vs-temp plot: missing columns.")
        return

    fig, ax = plt.subplots(figsize=(9, 5))

    ride_ids = sorted(df['ride_id'].unique())
    colors = plt.cm.tab10(np.linspace(0, 1, len(ride_ids)))

    for ride_id, color in zip(ride_ids, colors):
        grp = df[df['ride_id'] == ride_id].copy()
        x = pd.to_numeric(grp['temp_c'], errors='coerce')
        y = pd.to_numeric(grp['sweat_rate_l_hr'], errors='coerce')
        mask = x.notna() & y.notna() & (y > 0)
        label = ride_labels.get(ride_id, ride_id[:8])
        ax.scatter(x[mask], y[mask], s=6, alpha=0.4, color=color, label=label)

        # Per-ride mean dot
        if mask.sum() > 0:
            ax.scatter(x[mask].mean(), y[mask].mean(), s=80, color=color,
                       edgecolors='black', linewidths=1, zorder=5)

    ax.set_xlabel("Ambient Temperature (°C)", fontsize=11)
    ax.set_ylabel("Sweat Rate (L/h)", fontsize=11)
    ax.set_title("Sweat Rate vs Ambient Temperature\n(small dots = raw, large dots = ride mean)", fontsize=11)
    ax.legend(title="Ride", fontsize=8, title_fontsize=9, loc='upper left')
    ax.grid(alpha=0.3)

    # Shade the temperature zones you haven't covered well
    temp_min = pd.to_numeric(df['temp_c'], errors='coerce').min()
    temp_max = pd.to_numeric(df['temp_c'], errors='coerce').max()
    ax.set_xlim(min(0, temp_min - 2), max(40, temp_max + 2))

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "03_sweat_vs_temperature.png")
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"  Saved: {out}")
    plt.show()


# --------------------------------------------------------------------------
# PLOT 4 — Per-ride mean comparison bar chart
# --------------------------------------------------------------------------
def plot_per_ride_means(df: pd.DataFrame, ride_labels: dict):
    metrics = [
        ("temp_c",          "Avg Temp (°C)"),
        ("humidity_pct",    "Avg Humidity (%)"),
        ("sweat_rate_l_hr", "Avg Sweat Rate (L/h)"),
        ("speed_kph",       "Avg Speed (km/h)"),
        ("power_watts",     "Avg Power (W)"),
    ]
    metrics = [(col, label) for col, label in metrics if col in df.columns]

    ride_ids = sorted(df['ride_id'].unique())
    x_labels = [ride_labels.get(r, r[:8]) for r in ride_ids]
    x = np.arange(len(ride_ids))
    colors = plt.cm.tab10(np.linspace(0, 1, len(ride_ids)))

    n = len(metrics)
    fig, axes = plt.subplots(1, n, figsize=(3.5 * n, 5))
    if n == 1:
        axes = [axes]
    fig.suptitle("Per-Ride Mean Comparison", fontsize=13, fontweight='bold')

    for ax, (col, ylabel) in zip(axes, metrics):
        means = [pd.to_numeric(df[df['ride_id'] == r][col], errors='coerce').mean() for r in ride_ids]
        bars = ax.bar(x, means, color=colors, edgecolor='white', alpha=0.85)
        ax.set_xticks(x)
        ax.set_xticklabels(x_labels, fontsize=8)
        ax.set_ylabel(ylabel, fontsize=9)
        ax.set_title(ylabel, fontsize=10)
        ax.grid(axis='y', alpha=0.3)
        # Value labels on bars
        for bar, val in zip(bars, means):
            if not np.isnan(val):
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01 * bar.get_height(),
                        f"{val:.1f}", ha='center', va='bottom', fontsize=7)

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "04_per_ride_means.png")
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"  Saved: {out}")
    plt.show()


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# PLOT 5 — Single box plot: overall spread of each key metric
# --------------------------------------------------------------------------
def plot_overall_boxplot(df: pd.DataFrame):
    metrics = [
        ("temp_c",          "Temp\n(°C)"),
        ("humidity_pct",    "Humidity\n(%)"),
        ("skin_temp_c",     "Skin Temp\n(°C)"),
        ("sweat_rate_l_hr", "Sweat Rate\n(L/h)"),
        ("speed_kph",       "Speed\n(km/h)"),
        ("power_watts",     "Power\n(W)"),
        ("torque_nm",       "Torque\n(Nm)"),
    ]
    metrics = [(col, label) for col, label in metrics if col in df.columns]

    data   = [pd.to_numeric(df[col], errors='coerce').dropna().values for col, _ in metrics]
    labels = [label for _, label in metrics]

    fig, ax = plt.subplots(figsize=(11, 5))
    bp = ax.boxplot(data, patch_artist=True, notch=False,
                    medianprops=dict(color='black', linewidth=2))

    colors = plt.cm.tab10(np.linspace(0, 1, len(metrics)))
    for patch, color in zip(bp['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.75)

    ax.set_xticks(range(1, len(metrics) + 1))
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_title("Overall Spread — All Rides Combined", fontsize=13, fontweight='bold')
    ax.set_ylabel("Value", fontsize=10)
    ax.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "05_overall_boxplot.png")
    plt.savefig(out, dpi=150, bbox_inches='tight')
    print(f"  Saved: {out}")
    plt.show()


def main():
    print("=" * 60)
    print("  DATASET SPREAD VISUALISATION")
    print("=" * 60)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Fetching data from Supabase...")
    df = fetch_all_data(client)

    if df.empty:
        print("No data found.")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    ride_labels = {r: short_ride_label(r) for r in df['ride_id'].unique()}

    print(f"  {df['ride_id'].nunique()} rides | {len(df):,} rows\n")
    print("Generating plots...")

    plot_boxplots(df, ride_labels)
    plot_ambient_histograms(df)
    plot_sweat_vs_temp(df, ride_labels)
    plot_per_ride_means(df, ride_labels)
    plot_overall_boxplot(df)

    print(f"\nAll plots saved to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
