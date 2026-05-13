import sys
import os
import pandas as pd
import numpy as np
import re
import matplotlib.pyplot as plt

# Set up paths to safely import Supabase credentials from the global config
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

def engineer_features(df):
    print("Processing individual rides to mathematically engineer features...")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    engineered_rides = []
    rides = df['ride_id'].unique()
    
    for rid in rides:
        ride_df = df[df['ride_id'] == rid].copy()
        ride_df = ride_df.sort_values('timestamp').reset_index(drop=True)
        
        # 1. Delta Time (seconds between readings for physics calculations)
        ride_df['dt_seconds'] = ride_df['timestamp'].diff().dt.total_seconds().fillna(0)
        
        # 2. THE INSIGHT: 'Exertion Debt' (Cumulative Work in kiloJoules)
        # Power (Watts) = Torque (Nm) * RPM * (2 * PI / 60) -> 0.10472
        # Work (Joules) = Power * time(seconds)
        ride_df['power_watts'] = ride_df['torque_nm'] * ride_df['rpm'] * 0.10472
        ride_df['work_joules'] = ride_df['power_watts'] * ride_df['dt_seconds']
        ride_df['exertion_debt_kj'] = ride_df['work_joules'].cumsum() / 1000.0

        # 2b. Exertion Intensity (kJ/min) — separates "worked hard" from "rode for a long time"
        # Answers: "how hard have you been working on average so far?"
        elapsed_minutes = ride_df['dt_seconds'].cumsum() / 60.0
        ride_df['exertion_intensity_kj_per_min'] = ride_df['exertion_debt_kj'] / elapsed_minutes.replace(0, np.nan)
        ride_df['exertion_intensity_kj_per_min'] = ride_df['exertion_intensity_kj_per_min'].fillna(0)
        
        # 3. Rolling Mechanical Averages (Using Time-Based Windows)
        ride_df = ride_df.set_index('timestamp')
        ride_df['torque_rolling_3min'] = ride_df['torque_nm'].rolling('3min').mean().fillna(0)
        ride_df['rpm_rolling_3min'] = ride_df['rpm'].rolling('3min').mean().fillna(0)
        ride_df = ride_df.reset_index()
        
        # 4. FINAL INSIGHT: Fix the 'Step-Function' Biological Output
        # Forward fill the wearable data, then apply a rolling smooth to curve the data beautifully.
        # Ensure we don't trigger future warnings by inferring objects directly
        ride_df['sweat_rate_l_hr'] = pd.to_numeric(ride_df['sweat_rate_l_hr'], errors='coerce')
        # limit=30 caps forward-fill at 30 rows (30 seconds at ~1s per row).
        # Beyond that, a gap in the sweat sensor is treated as missing (0) rather
        # than propagating a potentially stale reading indefinitely.
        ride_df['sweat_rate_raw'] = ride_df['sweat_rate_l_hr'].ffill(limit=30).fillna(0)
        
        # Smooth out the jagged blocks over a 10-second time-based rolling window.
        # Time-based ensures consistency regardless of any variation in logging rate.
        ride_df = ride_df.set_index('timestamp')
        ride_df['sweat_rate_smoothed'] = ride_df['sweat_rate_raw'].rolling('10s', min_periods=1, center=True).mean()
        ride_df = ride_df.reset_index()
        
        # Create the Binary Target for the Classification Model 
        # (Assuming 0.3 L/hr is the threshold for 'significant physiological shift')
        ride_df['is_sweating'] = (ride_df['sweat_rate_smoothed'] > 0.3).astype(int)
        
        engineered_rides.append(ride_df)
        
    # SMASH everything into one global dataframe - the ML models playground!
    global_df = pd.concat(engineered_rides, ignore_index=True)
    return global_df

def plot_engineered_features(df, output_dir):
    print("\nGenerating 'Before/After' feature visualisations...")
    rides = df['ride_id'].unique()
    
    # Just plot the 2 most recent rides so we don't spam the folder
    for rid in rides[-2:]:
        ride_df = df[df['ride_id'] == rid].copy()
        ride_df = ride_df.sort_values('timestamp')
        ride_df['elapsed_min'] = (ride_df['timestamp'] - ride_df['timestamp'].iloc[0]).dt.total_seconds() / 60.0
        
        fig, ax1 = plt.subplots(figsize=(12, 6))
        
        # Original vs Smoothed Biological Target on ax1
        color = 'tab:red'
        ax1.set_xlabel('Elapsed Time (Minutes)')
        ax1.set_ylabel('Sweat Rate (L/hr)', color=color)
        ax1.plot(ride_df['elapsed_min'], ride_df['sweat_rate_raw'], color='lightpink', linewidth=2, linestyle='--', label='Raw Step-Function Sweat')
        ax1.plot(ride_df['elapsed_min'], ride_df['sweat_rate_smoothed'], color='red', linewidth=3, label='Engineered Smooth Target')
        ax1.tick_params(axis='y', labelcolor=color)
        
        # New Exertion Debt bucket on ax2
        ax2 = ax1.twinx()
        color = 'tab:blue'
        ax2.set_ylabel('Engineered Feature: Exertion Debt (kJ)', color=color)
        ax2.plot(ride_df['elapsed_min'], ride_df['exertion_debt_kj'], color=color, linewidth=2.5, label='Cumulative Exertion Debt')
        ax2.tick_params(axis='y', labelcolor=color)
        
        plt.title(f"Visualising Feature Engineering Transformations\nRide ID: {rid}")
        fig.tight_layout()
        
        lines_1, labels_1 = ax1.get_legend_handles_labels()
        lines_2, labels_2 = ax2.get_legend_handles_labels()
        ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')

        plot_path = os.path.join(output_dir, f"02_engineered_visual_{rid}.png")
        plt.savefig(plot_path)
        print(f"-> Saved Before/After Plot: {plot_path}")
        plt.close()

def main():
    print("="*60)
    print(" STEP 2: FEATURE ENGINEERING (BUILDING THE DIGITAL TWIN)")
    print("="*60)
    
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    raw_df = fetch_all_data(client)
    
    if raw_df.empty:
        print("No ride data found.")
        return
        
    global_df = engineer_features(raw_df)
    
    # 5. Build the pristine final Machine Learning dataset
    ml_columns = [
        'timestamp', 'ride_id',
        'temp_c', 'humidity_pct', 'speed_kph', 'skin_temp_c',
        'torque_nm', 'rpm',
        'torque_rolling_3min', 'rpm_rolling_3min', 'exertion_debt_kj',
        'power_watts', 'exertion_intensity_kj_per_min',
        'sweat_rate_smoothed', 'is_sweating'
    ]
    
    available_cols = [col for col in ml_columns if col in global_df.columns]
    final_ml_dataset = global_df[available_cols] # Discard messy raw variables
    
    # Export it ready for the AI
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_ready_dataset.csv')
    final_ml_dataset.to_csv(output_path, index=False)
    
    # Generate the visualisations so the user can see what the math did!
    output_dir = os.path.dirname(os.path.abspath(__file__))
    plot_engineered_features(global_df, output_dir)
    
    print(f"\n✅ Feature Engineering Complete!")
    print(f"Generated Dataset Rows: {len(final_ml_dataset)}")
    print(f"Features Engineered: 'exertion_debt_kj', 'torque_rolling_3min', 'sweat_rate_smoothed'")
    print(f"Saved pristine ML dataset to: {output_path}")
    print("\nNext up: We can load this fast, clean CSV to instantly train a Binary Random Forest model!")

if __name__ == "__main__":
    main()
