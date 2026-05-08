"""
dataset_coverage.py
-------------------
Prints a console summary of the mean, min, max, and spread of important
metrics across all collected ride data.  Helps identify gaps — e.g. where
temperature or humidity coverage is thin — so you know what conditions
to target on future rides.

Run from any directory:
    python Data_analysis/dataset_coverage.py
"""

import sys
import os
import re
import pandas as pd

# --------------------------------------------------------------------------
# Supabase connection (same safe pattern as database_stats.py)
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


# Metrics to analyse, grouped for readability
METRIC_GROUPS = {
    "Environment": ["temp_c", "humidity_pct"],
    "Rider physiology": ["skin_temp_c", "sweat_rate_l_hr", "fluid_loss_l"],
    "Performance": ["speed_kph", "torque_nm", "rpm", "power_watts"],
    "Derived / rolling": ["torque_rolling_3min", "rpm_rolling_3min",
                          "exertion_debt_kj", "exertion_intensity_kj_per_min"],
}

# Soft targets — flag if the range is narrower than these thresholds
RANGE_WARNINGS = {
    "temp_c":        ("Temperature range < 10 °C — try riding in more varied weather", 10),
    "humidity_pct":  ("Humidity range < 30 % — try riding in more varied humidity", 30),
}


def print_group(name: str, cols: list, df: pd.DataFrame):
    available = [c for c in cols if c in df.columns]
    if not available:
        return

    print(f"\n  {'─' * 56}")
    print(f"  {name.upper()}")
    print(f"  {'─' * 56}")
    header = f"  {'Metric':<35} {'Mean':>8} {'Min':>8} {'Max':>8} {'Range':>8}  {'Non-null':>8}"
    print(header)
    print(f"  {'─' * 56}")

    for col in available:
        series = pd.to_numeric(df[col], errors='coerce').dropna()
        if series.empty:
            print(f"  {col:<35} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>8}  {'0':>8}")
            continue
        mean = series.mean()
        lo   = series.min()
        hi   = series.max()
        rng  = hi - lo
        nn   = len(series)
        print(f"  {col:<35} {mean:>8.2f} {lo:>8.2f} {hi:>8.2f} {rng:>8.2f}  {nn:>8,}")

        if col in RANGE_WARNINGS:
            msg, threshold = RANGE_WARNINGS[col]
            if rng < threshold:
                print(f"  {'':>2}  ⚠  {msg}")


def ride_level_summary(df: pd.DataFrame):
    """One row per ride — ambient conditions and key performance averages."""
    records = []
    for ride_id, grp in df.groupby('ride_id'):
        start = pd.to_datetime(grp['timestamp']).min()
        rec = {
            'Ride':         ride_id,
            'Date':         start.strftime('%Y-%m-%d'),
            'Temp (°C)':    pd.to_numeric(grp.get('temp_c'), errors='coerce').mean(),
            'Humidity (%)': pd.to_numeric(grp.get('humidity_pct'), errors='coerce').mean(),
            'Skin T (°C)':  pd.to_numeric(grp.get('skin_temp_c'), errors='coerce').mean(),
            'Sweat (L/h)':  pd.to_numeric(grp.get('sweat_rate_l_hr'), errors='coerce').mean(),
            'Speed (km/h)': pd.to_numeric(grp.get('speed_kph'), errors='coerce').mean(),
            'Power (W)':    pd.to_numeric(grp.get('power_watts'), errors='coerce').mean(),
        }
        records.append(rec)

    summary = pd.DataFrame(records).sort_values('Date').reset_index(drop=True)
    return summary


def main():
    print("=" * 62)
    print("  DATASET COVERAGE & RANGE REPORT")
    print("=" * 62)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    df = fetch_all_data(client)

    if df.empty:
        print("\nNo data found in ride_metrics_v2.")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    n_rides = df['ride_id'].nunique()
    n_rows  = len(df)
    date_range = f"{df['timestamp'].min().strftime('%Y-%m-%d')} → {df['timestamp'].max().strftime('%Y-%m-%d')}"

    print(f"\n  Rides collected : {n_rides}")
    print(f"  Total rows      : {n_rows:,}")
    print(f"  Date range      : {date_range}")

    # --- Per-metric statistics ---
    for group_name, cols in METRIC_GROUPS.items():
        print_group(group_name, cols, df)

    # --- Per-ride ambient summary ---
    print(f"\n\n{'=' * 62}")
    print("  PER-RIDE AMBIENT & PERFORMANCE SUMMARY")
    print(f"{'=' * 62}")
    ride_df = ride_level_summary(df)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    pd.set_option('display.float_format', '{:.2f}'.format)
    print(ride_df.to_string(index=False))

    # --- Temperature bucket coverage ---
    print(f"\n\n{'=' * 62}")
    print("  TEMPERATURE BUCKET COVERAGE  (rides per 5 °C band)")
    print(f"{'=' * 62}")
    ride_df['Temp bucket'] = pd.cut(
        ride_df['Temp (°C)'],
        bins=range(0, 46, 5),
        right=False,
        labels=[f"{b}–{b+5} °C" for b in range(0, 41, 5)]
    )
    bucket_counts = ride_df['Temp bucket'].value_counts().sort_index()
    for bucket, count in bucket_counts.items():
        bar = '█' * count
        flag = '  ← needs more data' if count < 2 else ''
        print(f"  {str(bucket):<12}  {bar:<10} {count}{flag}")

    print(f"\n  Report complete.\n")


if __name__ == "__main__":
    main()
