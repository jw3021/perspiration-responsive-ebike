import sys
import os
import pandas as pd
import matplotlib.pyplot as plt
import re

num_rides = 5

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

def fetch_all_data(client):
    """Fetch all rows via pagination."""
    print("Fetching raw data from Supabase...")
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

def plot_sweat_onset(df, output_dir):
    """Plot the comparison of Mechanical Output vs Sweat Response"""
    rides = df['ride_id'].unique()

    for rid in rides:
        ride_df = df[df['ride_id'] == rid].copy()
        ride_df = ride_df.sort_values('timestamp')

        # Calculate elapsed minutes
        ride_df['elapsed_min'] = (ride_df['timestamp'] - ride_df['timestamp'].iloc[0]).dt.total_seconds() / 60.0

        # Smooth out the mechanical effort using a 60-row moving average (~3 seconds of data)
        ride_df['torque_rolling_avg'] = ride_df['torque_nm'].rolling(window=60, min_periods=1).mean()

        # Fill missing sweat values for the visualizer
        ride_df['sweat_rate_l_hr'] = ride_df['sweat_rate_l_hr'].fillna(method='ffill').fillna(0)

        fig, ax1 = plt.subplots(figsize=(12, 6))

        # Primary Axis: Mechanical Torque
        color = 'tab:orange'
        ax1.set_xlabel('Elapsed Time (Minutes)')
        ax1.set_ylabel('Torque (Nm) [Rolling Avg]', color=color)
        ax1.plot(ride_df['elapsed_min'], ride_df['torque_rolling_avg'], color=color, alpha=0.7, label='Mechanical Torque')
        ax1.tick_params(axis='y', labelcolor=color)

        # Secondary Axis: Biological Output (Sweat)
        ax2 = ax1.twinx()
        color = 'tab:red'
        ax2.set_ylabel('Sweat Rate (L/hr)', color=color)
        ax2.plot(ride_df['elapsed_min'], ride_df['sweat_rate_l_hr'], color=color, linewidth=2.5, label='Sweat Rate')
        ax2.tick_params(axis='y', labelcolor=color)

        plt.title(f"EDA: Checking 'Time to Sweat Onset'\nRide ID: {rid}")
        fig.tight_layout()

        # Combine legends beautifully
        lines_1, labels_1 = ax1.get_legend_handles_labels()
        lines_2, labels_2 = ax2.get_legend_handles_labels()
        ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')

        plot_path = os.path.join(output_dir, f"01_eda_sweat_onset_{rid}.png")
        plt.savefig(plot_path)
        print(f"-> Saved Onset Plot: {plot_path}")
        plt.close()

def main():
    print("="*50)
    print(" STEP 1: INITIAL E.D.A - SWEAT ONSET VISUALIZER")
    print("="*50)

    # Rides excluded due to sensor faults or corrupted data
    EXCLUDED_RIDES = {
        'RIDE_20260416_102808',  # torque sensor fault (117.3 Nm avg — hardware error)
        'RIDE_20260331_151943',  # HDrop not reset between sessions — fluid loss carried over from prior ride
        'RIDE_20260330_155917',  # 0.55 L fluid loss with survey score 2 (Light) — inconsistent
    }

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    df = fetch_all_data(client)
    df = df[~df['ride_id'].isin(EXCLUDED_RIDES)]

    if df.empty:
        print("No ride data found. Aborting EDA.")
        return

    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # To keep it lightweight, let's only analyze the 3 most recent rides
    recent_rides = df.groupby('ride_id')['timestamp'].max().sort_values(ascending=False).head(num_rides).index
    df_recent = df[df['ride_id'].isin(recent_rides)]

    output_dir = os.path.dirname(os.path.abspath(__file__))
    plot_sweat_onset(df_recent, output_dir)
    print("\nDone! Please review the generated PNG graphs in this directory.")

if __name__ == "__main__":
    main()
