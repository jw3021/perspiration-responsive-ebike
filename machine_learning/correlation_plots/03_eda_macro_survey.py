import sys
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import re

# Thesis style
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import plot_style
plot_style.apply()

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

def fetch_surveys(client):
    print("Fetching survey results from 'ride_surveys' table...")
    response = client.table("ride_surveys").select("*").execute()
    data = response.data
    if not data:
        return pd.DataFrame()
    return pd.DataFrame(data)

def fetch_macro_telemetry(client):
    print("Fetching telemetry to aggregate total fluid loss from 'ride_metrics_v2'...")
    all_data = []
    chunk_size = 1000
    start = 0
    while True:
        # We only strictly need ride_id and fluid_loss_l for this aggregation (saves memory)
        response = client.table("ride_metrics_v2").select("ride_id, fluid_loss_l").range(start, start + chunk_size - 1).execute()
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

    # Force numbers and calculate the total fluid loss (which is just the peak value reached in that session)
    df['fluid_loss_l'] = pd.to_numeric(df['fluid_loss_l'], errors='coerce')
    macro_df = df.groupby('ride_id')['fluid_loss_l'].max().reset_index()
    macro_df.rename(columns={'fluid_loss_l': 'total_fluid_loss_l'}, inplace=True)
    return macro_df

def print_ride_table(merged_df):
    df = merged_df.copy()
    df['sweat_perception_score'] = pd.to_numeric(df['sweat_perception_score'], errors='coerce')
    df['total_fluid_loss_l'] = pd.to_numeric(df['total_fluid_loss_l'], errors='coerce')
    df = df.sort_values('total_fluid_loss_l', ascending=False)
    print("\n  Rides sorted by total fluid loss:")
    print(f"  {'Ride ID':<32} {'Fluid Loss (L)':>15} {'Survey Score':>13}")
    print("  " + "-"*62)
    for _, row in df.iterrows():
        print(f"  {row['ride_id']:<32} {row['total_fluid_loss_l']:>15.3f} {int(row['sweat_perception_score']):>13}")

def plot_correlation(merged_df, output_dir):
    print("Generating biological vs subjective Scatter Plot...")

    plt.figure(figsize=(10, 6))

    x = merged_df['total_fluid_loss_l'].fillna(0)
    y = pd.to_numeric(merged_df['sweat_perception_score'], errors='coerce')

    plt.scatter(x, y, color=plot_style.PRIMARY, s=120, alpha=0.4,
                edgecolors=plot_style.DARK_BLUE, linewidths=0.8, label='Historical Rides')

    if len(merged_df) > 1:
        z = np.polyfit(x, y, 1)
        p = np.poly1d(z)
        plt.plot(x, p(x), color=plot_style.ACCENT,
                 linewidth=2.0, alpha=0.85, label='Physiological Trendline')

    plt.xlabel("Total Fluid Loss Measured by Wearable (Litres)")
    plt.ylabel("Post-Ride Sweat Survey Score (1–5)")
    plt.yticks([1, 2, 3, 4, 5], ['1 (Dry)', '2 (Light)', '3 (Moderate)', '4 (Heavy)', '5 (Max)'])
    plt.ylim(0.5, 5.5)
    plt.legend(loc='upper left')

    output_path = os.path.join(output_dir, '03_survey_correlation_plot.png')
    plt.savefig(output_path, bbox_inches='tight')
    plt.close()

    print(f"-> Saved Correlational Plot: {output_path}")

def analyse_threshold(merged_df):
    """
    Use the survey ratings to empirically derive the personal sweat threshold.
    The transition we care about is between rating 2 (Lightly Sweating) and
    rating 3 (Moderately Sweaty) — that midpoint is where the threshold should sit.
    """
    print("\n" + "="*60)
    print("  THRESHOLD CALIBRATION ANALYSIS")
    print("="*60)

    merged_df = merged_df.copy()
    merged_df['sweat_perception_score'] = pd.to_numeric(merged_df['sweat_perception_score'], errors='coerce')
    merged_df['total_fluid_loss_l'] = pd.to_numeric(merged_df['total_fluid_loss_l'], errors='coerce')
    merged_df = merged_df.dropna(subset=['sweat_perception_score', 'total_fluid_loss_l'])

    # Mean fluid loss per rating band
    print("\n  Mean fluid loss per subjective rating:")
    print(f"  {'Rating':<10} {'Label':<28} {'Mean Fluid (L)':<16} {'N Rides'}")
    print("  " + "-"*60)

    labels = {1: 'Completely Dry', 2: 'Lightly Sweating',
              3: 'Moderately Sweaty', 4: 'Very Sweaty', 5: 'Max Effort (Dripping)'}

    band_means = {}
    for rating in sorted(merged_df['sweat_perception_score'].unique()):
        subset = merged_df[merged_df['sweat_perception_score'] == rating]['total_fluid_loss_l']
        mean_val = subset.mean()
        band_means[rating] = mean_val
        label = labels.get(int(rating), 'Unknown')
        print(f"  {int(rating):<10} {label:<28} {mean_val:<16.3f} {len(subset)}")

    # Missing bands
    all_ratings = {1, 2, 3, 4, 5}
    seen_ratings = set(int(r) for r in merged_df['sweat_perception_score'].unique())
    missing = all_ratings - seen_ratings
    if missing:
        print(f"\n  ⚠️  No data yet for rating(s): {sorted(missing)} — dataset limitation, collect more rides.")

    # Derive the personal threshold: midpoint between mean fluid loss at rating 2 and rating 3
    if 2 in band_means and 3 in band_means:
        personal_threshold = (band_means[2] + band_means[3]) / 2.0
        print(f"\n  Mean fluid loss at rating 2 (Lightly Sweating)  : {band_means[2]:.3f} L")
        print(f"  Mean fluid loss at rating 3 (Moderately Sweaty) : {band_means[3]:.3f} L")
        print(f"\n  ► Personal sweat threshold (midpoint 2→3)       : {personal_threshold:.3f} L")
        print(f"  ► Hardcoded threshold currently in model        : 0.300 L")

        diff = personal_threshold - 0.300
        if abs(diff) < 0.05:
            print(f"\n  ✅ Personal threshold is within 0.05 L of the hardcoded value — 0.3 L/hr is well calibrated.")
        elif diff > 0:
            print(f"\n  ⚠️  Personal threshold is {diff:.3f} L ABOVE 0.3 — consider raising the threshold.")
        else:
            print(f"\n  ⚠️  Personal threshold is {abs(diff):.3f} L BELOW 0.3 — consider lowering the threshold.")

        return personal_threshold
    else:
        print("\n  ⚠️  Need rides rated both 2 and 3 to calculate the personal threshold midpoint.")
        return None


def main():
    print("="*60)
    print(" STEP 3: MACRO EDA - SUBJECTIVE SURVEY CORRELATION")
    print("="*60)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    surveys_df = fetch_surveys(client)
    telemetry_df = fetch_macro_telemetry(client)

    if surveys_df.empty or telemetry_df.empty:
        print("Not enough data to cross-reference tables.")
        return

    # Rides excluded due to sensor faults or corrupted data (not short/dry rides — those are valid)
    EXCLUDED_RIDES = {
        'RIDE_20260416_102808',  # torque sensor fault (117.3 Nm avg — hardware error)
        'RIDE_20260331_151943',  # HDrop not reset between sessions — fluid loss carried over from prior ride
        'RIDE_20260330_155917',  # 0.55 L fluid loss with survey score 2 (Light) — inconsistent
    }

    # Perform strict INNER JOIN to ensure we only plot rides that have both biological data AND a survey score
    merged_df = pd.merge(telemetry_df, surveys_df, on='ride_id', how='inner')
    merged_df = merged_df[~merged_df['ride_id'].isin(EXCLUDED_RIDES)]

    print(f"\n✅ Matched {len(merged_df)} distinct rides that contain both a Survey Score and Telemetry.")

    if len(merged_df) == 0:
        print("⚠️ No matching rides found between the two tables.")
        print("Did you submit the survey on the web app for the rides you just tracked?")
        return

    output_dir = os.path.dirname(os.path.abspath(__file__))
    print_ride_table(merged_df)
    plot_correlation(merged_df, output_dir)
    analyse_threshold(merged_df)
    print("\nNext steps: Open the generated PNG to visually prove your personalized biological threshold!")

if __name__ == "__main__":
    main()
