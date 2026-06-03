import sys
import os
import pandas as pd
import numpy as np
import re

try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    from credentials import SUPABASE_URL, SUPABASE_KEY
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

# Personalised fluid loss threshold derived from survey midpoint (rating 2→3)
# Source: 03_eda_macro_survey.py — mean fluid loss at rating 2 = 0.240 L, rating 3 = 0.363 L
PERSONAL_FLUID_THRESHOLD = 0.17  # litres


def fetch_all_data(client):
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
    print("Engineering features with fluid-loss-based label...")
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    engineered_rides = []

    for rid in df['ride_id'].unique():
        ride_df = df[df['ride_id'] == rid].copy()
        ride_df = ride_df.sort_values('timestamp').reset_index(drop=True)

        # Delta time
        ride_df['dt_seconds'] = ride_df['timestamp'].diff().dt.total_seconds().fillna(0)

        # Mechanical features (identical to rate-based model)
        ride_df['power_watts'] = ride_df['torque_nm'] * ride_df['rpm'] * 0.10472
        ride_df['work_joules'] = ride_df['power_watts'] * ride_df['dt_seconds']
        ride_df['exertion_debt_kj'] = ride_df['work_joules'].cumsum() / 1000.0

        elapsed_minutes = ride_df['dt_seconds'].cumsum() / 60.0
        ride_df['exertion_intensity_kj_per_min'] = (
            ride_df['exertion_debt_kj'] / elapsed_minutes.replace(0, np.nan)
        ).fillna(0)

        ride_df = ride_df.set_index('timestamp')
        ride_df['torque_rolling_3min'] = ride_df['torque_nm'].rolling('3min').mean().fillna(0)
        ride_df['rpm_rolling_3min'] = ride_df['rpm'].rolling('3min').mean().fillna(0)
        ride_df = ride_df.reset_index()

        # Fluid loss: forward-fill sparse HDrop readings (cumulative signal, rarely updates)
        ride_df['fluid_loss_l'] = pd.to_numeric(ride_df['fluid_loss_l'], errors='coerce')
        ride_df['fluid_loss_l'] = ride_df['fluid_loss_l'].ffill().fillna(0)

        # Personalised binary label: has the rider crossed their personal fluid loss threshold?
        ride_df['above_fluid_threshold'] = (
            ride_df['fluid_loss_l'] > PERSONAL_FLUID_THRESHOLD
        ).astype(int)

        engineered_rides.append(ride_df)

    return pd.concat(engineered_rides, ignore_index=True)


def main():
    print("=" * 60)
    print(" FLUID LOSS MODEL — STEP 2: FEATURE ENGINEERING")
    print(f" Personal fluid threshold: {PERSONAL_FLUID_THRESHOLD} L")
    print("=" * 60)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    raw_df = fetch_all_data(client)
    raw_df = raw_df[~raw_df['ride_id'].isin(EXCLUDED_RIDES)]

    if raw_df.empty:
        print("No ride data found.")
        return

    global_df = engineer_features(raw_df)

    ml_columns = [
        'timestamp', 'ride_id',
        'temp_c', 'humidity_pct', 'speed_kph', 'skin_temp_c',
        'torque_nm', 'rpm',
        'torque_rolling_3min', 'rpm_rolling_3min',
        'exertion_debt_kj', 'power_watts', 'exertion_intensity_kj_per_min',
        'fluid_loss_l', 'above_fluid_threshold',
    ]

    available_cols = [c for c in ml_columns if c in global_df.columns]
    final_df = global_df[available_cols]

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'training_dataset.csv')
    final_df.to_csv(output_path, index=False)

    n_rides = final_df['ride_id'].nunique()
    n_positive = (final_df['above_fluid_threshold'] == 1).sum()
    n_total = len(final_df)
    print(f"\n✅ Feature engineering complete.")
    print(f"   Rides        : {n_rides}")
    print(f"   Total rows   : {n_total}")
    print(f"   Above threshold ({PERSONAL_FLUID_THRESHOLD} L): {n_positive} rows ({n_positive/n_total*100:.1f}%)")
    print(f"   Saved to     : {output_path}")


if __name__ == "__main__":
    main()
