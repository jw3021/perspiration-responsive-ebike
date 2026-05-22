import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re

# Set up paths to safely import Supabase credentials from the global config
try:
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.py')
    with open(config_path, 'r') as f:
        config_text = f.read()

    SUPABASE_URL = re.search(r'SUPABASE_URL\s*=\s*["\']([^"\']+)["\']', config_text).group(1)
    SUPABASE_KEY = re.search(r'SUPABASE_KEY\s*=\s*["\']([^"\']+)["\']', config_text).group(1)

    from supabase import create_client
except Exception as e:
    print(f"Error loading Supabase credentials: {e}")
    sys.exit(1)

# Rides excluded due to sensor faults or corrupted data
EXCLUDED_RIDES = {
    'RIDE_20260416_102808',  # torque sensor fault (117.3 Nm avg — hardware error)
    'RIDE_20260331_151943',  # HDrop not reset between sessions — fluid loss carried over from prior ride
    'RIDE_20260330_155917',  # 0.55 L fluid loss with survey score 2 (Light) — inconsistent
}

def fetch_surveys(client):
    print("Fetching survey results from 'ride_surveys' table...")
    response = client.table("ride_surveys").select("*").execute()
    data = response.data
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)

def fetch_peak_sweat_rate(client):
    print("Fetching sweat rate telemetry from 'ride_metrics_v2'...")
    all_data = []
    chunk_size = 1000
    start = 0
    while True:
        response = client.table("ride_metrics_v2").select("ride_id, sweat_rate_l_hr").range(start, start + chunk_size - 1).execute()
        data = response.data
        if not data:
            break
        all_data.extend(data)
        if len(data) < chunk_size:
            break
        start += chunk_size

    df = pd.DataFrame(all_data)
    if df.empty:
        return pd.DataFrame()

    df['sweat_rate_l_hr'] = pd.to_numeric(df['sweat_rate_l_hr'], errors='coerce')
    peak_df = df.groupby('ride_id')['sweat_rate_l_hr'].max().reset_index()
    peak_df.rename(columns={'sweat_rate_l_hr': 'peak_sweat_rate_l_hr'}, inplace=True)
    return peak_df

def print_ride_table(merged_df):
    df = merged_df.copy()
    df['sweat_perception_score'] = pd.to_numeric(df['sweat_perception_score'], errors='coerce')
    df['peak_sweat_rate_l_hr'] = pd.to_numeric(df['peak_sweat_rate_l_hr'], errors='coerce')
    df = df.sort_values('peak_sweat_rate_l_hr', ascending=False)
    print("\n  Rides sorted by peak sweat rate:")
    print(f"  {'Ride ID':<32} {'Peak Rate (L/hr)':>17} {'Survey Score':>13}")
    print("  " + "-"*64)
    for _, row in df.iterrows():
        print(f"  {row['ride_id']:<32} {row['peak_sweat_rate_l_hr']:>17.3f} {int(row['sweat_perception_score']):>13}")

def plot_correlation(merged_df, output_dir):
    print("Generating Peak Sweat Rate vs. Survey Score scatter plot...")

    plt.figure(figsize=(10, 6))

    x = merged_df['peak_sweat_rate_l_hr'].fillna(0)
    y = pd.to_numeric(merged_df['sweat_perception_score'], errors='coerce')

    plt.scatter(x, y, color='#2ECC71', s=120, alpha=0.4, edgecolors='black', linewidths=0.8, label='Historical Rides')

    if len(merged_df) > 1:
        z = np.polyfit(x, y, 1)
        p = np.poly1d(z)
        x_line = np.linspace(x.min(), x.max(), 200)
        plt.plot(x_line, p(x_line), "r--", linewidth=2.5, alpha=0.7, label="Trendline")

    plt.title("Peak Sweat Rate vs. Post-Ride Perceived Sweat Score", fontsize=14, fontweight='bold')
    plt.xlabel("Peak Sweat Rate During Ride (L/hr)", fontsize=12)
    plt.ylabel("Post-Ride Sweat Survey Score (1-5)", fontsize=12)

    plt.yticks([1, 2, 3, 4, 5], ['1 (Dry)', '2 (Light)', '3 (Moderate)', '4 (Heavy)', '5 (Max)'])
    plt.ylim(0.5, 5.5)
    plt.grid(True, linestyle='--', alpha=0.3)
    plt.legend(loc='upper left')

    output_path = os.path.join(output_dir, '03.5_peak_sweat_rate_survey.png')
    plt.savefig(output_path, bbox_inches='tight')
    plt.close()
    print(f"-> Saved plot: {output_path}")

def analyse_threshold(merged_df):
    print("\n" + "="*60)
    print("  THRESHOLD CALIBRATION (Peak Sweat Rate)")
    print("="*60)

    df = merged_df.copy()
    df['sweat_perception_score'] = pd.to_numeric(df['sweat_perception_score'], errors='coerce')
    df['peak_sweat_rate_l_hr'] = pd.to_numeric(df['peak_sweat_rate_l_hr'], errors='coerce')
    df = df.dropna(subset=['sweat_perception_score', 'peak_sweat_rate_l_hr'])

    labels = {1: 'Completely Dry', 2: 'Lightly Sweating',
              3: 'Moderately Sweaty', 4: 'Very Sweaty', 5: 'Max Effort (Dripping)'}

    print("\n  Mean peak sweat rate per subjective rating:")
    print(f"  {'Rating':<10} {'Label':<28} {'Mean Peak (L/hr)':<18} {'N Rides'}")
    print("  " + "-"*62)

    band_means = {}
    for rating in sorted(df['sweat_perception_score'].unique()):
        subset = df[df['sweat_perception_score'] == rating]['peak_sweat_rate_l_hr']
        mean_val = subset.mean()
        band_means[rating] = mean_val
        label = labels.get(int(rating), 'Unknown')
        print(f"  {int(rating):<10} {label:<28} {mean_val:<18.3f} {len(subset)}")

    missing = {1, 2, 3, 4, 5} - set(int(r) for r in df['sweat_perception_score'].unique())
    if missing:
        print(f"\n  No data yet for rating(s): {sorted(missing)} — collect more rides.")

    if 2 in band_means and 3 in band_means:
        personal_threshold = (band_means[2] + band_means[3]) / 2.0
        print(f"\n  Mean peak rate at rating 2 (Lightly Sweating)  : {band_means[2]:.3f} L/hr")
        print(f"  Mean peak rate at rating 3 (Moderately Sweaty) : {band_means[3]:.3f} L/hr")
        print(f"\n  ► Empirical threshold (midpoint 2→3)           : {personal_threshold:.3f} L/hr")
        print(f"  ► Hardcoded threshold currently in model        : 0.300 L/hr")

        diff = personal_threshold - 0.300
        if abs(diff) < 0.05:
            print(f"\n  ✅ Empirical threshold within 0.05 L/hr of hardcoded value — 0.3 L/hr is well calibrated.")
        elif diff > 0:
            print(f"\n  ⚠️  Empirical threshold is {diff:.3f} L/hr ABOVE 0.3 — consider raising the threshold.")
        else:
            print(f"\n  ⚠️  Empirical threshold is {abs(diff):.3f} L/hr BELOW 0.3 — consider lowering the threshold.")

        return personal_threshold
    else:
        print("\n  ⚠️  Need rides rated both 2 and 3 to calculate the empirical threshold midpoint.")
        return None

def main():
    print("="*60)
    print(" STEP 3.5: PEAK SWEAT RATE vs. SURVEY SCORE")
    print("="*60)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    surveys_df = fetch_surveys(client)
    telemetry_df = fetch_peak_sweat_rate(client)

    if surveys_df.empty or telemetry_df.empty:
        print("Not enough data to cross-reference tables.")
        return

    merged_df = pd.merge(telemetry_df, surveys_df, on='ride_id', how='inner')
    merged_df = merged_df[~merged_df['ride_id'].isin(EXCLUDED_RIDES)]

    print(f"\n✅ Matched {len(merged_df)} rides with both telemetry and a survey score.")

    if len(merged_df) == 0:
        print("⚠️ No matching rides found.")
        return

    output_dir = os.path.dirname(os.path.abspath(__file__))
    print_ride_table(merged_df)
    plot_correlation(merged_df, output_dir)
    analyse_threshold(merged_df)

if __name__ == "__main__":
    main()
