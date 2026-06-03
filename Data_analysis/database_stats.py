import sys
import os
import pandas as pd
from datetime import datetime
import textwrap

# Supabase credentials loaded from secrets.py (gitignored)
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from credentials import SUPABASE_URL, SUPABASE_KEY
    from supabase import create_client
except Exception as e:
    print("Error: Missing dependencies or could not load secrets.py!")
    print("Verify you have the Supabase url in config.py and run: pip install supabase pandas")
    print(f"Details: {e}")
    sys.exit(1)

def fetch_all_data(client):
    """Fetches all rows from Supabase, handling the 1000-row pagination limit autonomously."""
    print("Fetching raw data pipeline from Supabase... (This might take a moment if the database is huge)")
    all_data = []
    chunk_size = 1000
    start = 0
    while True:
        try:
            response = client.table("ride_metrics_v2").select("*").range(start, start + chunk_size - 1).execute()
        except Exception as e:
            print(f"Failed to query Supabase: {e}")
            sys.exit(1)
            
        data = response.data
        if not data:
            break
        all_data.extend(data)
        if len(data) < chunk_size:
            break
        start += chunk_size
        
    return pd.DataFrame(all_data)

def main():
    print("=" * 60)
    print("  MASTERS PROJECT: E-BIKE DATA COLLECTION DASHBOARD")
    print("=" * 60)
    
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
        print("\n>>> NO DATA FOUND! The 'ride_metrics_v2' table is completely empty.")
        print(">>> Go ride your bike and generate some sweat! 🚴💧")
        return
        
    # Standardize data formats
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # ---------------------------------------------------------
    # MACRO STATISTICS (Overall Progress)
    # ---------------------------------------------------------
    total_rows = len(df)
    unique_rides = df['ride_id'].nunique()
    
    total_duration_hours = 0
    total_fluid_overall = 0
    
    ride_summaries = []
    
    for ride_id, group in df.groupby('ride_id'):
        start_time = group['timestamp'].min()
        end_time = group['timestamp'].max()
        duration_hrs = (end_time - start_time).total_seconds() / 3600.0
        
        # Max fluid loss for this specific ride (since it functionally accumulates)
        max_fluid = group['fluid_loss_l'].max()
        if pd.isna(max_fluid): max_fluid = 0
        
        # Average metrics
        avg_speed = group['speed_kph'].mean()
        avg_torque = group['torque_nm'].mean()
        avg_skin_temp = group['skin_temp_c'].dropna().mean()
        
        avg_sweat_rate = group['sweat_rate_l_hr'].dropna().mean()
        if pd.isna(avg_sweat_rate): avg_sweat_rate = 0
            
        total_duration_hours += duration_hrs
        total_fluid_overall += max_fluid
        
        ride_summaries.append({
            'Ride ID': ride_id[:8] + "...", 
            'Date': start_time.strftime('%Y-%m-%d %H:%M'),
            'Duration (h)': duration_hrs,
            'Fluid (L)': max_fluid,
            'Avg Sweat (L/h)': avg_sweat_rate,
            'Avg Speed (km/h)': avg_speed,
            'Avg Torque (Nm)': avg_torque,
            'Avg Skin Temp (°C)': avg_skin_temp
        })
        
    # Print the beautiful macro output
    print("\n" + "=" * 60)
    print("  OVERALL PROJECT PROGRESS")
    print("=" * 60)
    print(f"Total Telemetry Rows Logged : {total_rows:,} data points")
    print(f"Total Unique Rides          : {unique_rides} rides")
    print(f"Total Hours in the Saddle   : {total_duration_hours:.2f} Hours")
    print(f"Total Sweat Collected       : {total_fluid_overall:.3f} Litres 💧")
    
    if unique_rides > 0:
        print("\n" + "=" * 60)
        print("  AVERAGES ACROSS ALL RIDES")
        print("=" * 60)
        print(f"Avg Ride Duration : {(total_duration_hours/unique_rides)*60:.1f} minutes")
        print(f"Avg Fluid per Ride: {total_fluid_overall/unique_rides:.3f} L")
    
    # ---------------------------------------------------------
    # INDIVIDUAL RIDE BREAKDOWN
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("  INDIVIDUAL RIDE BREAKDOWN")
    print("=" * 60)
    
    # Create a clean DataFrame for the console
    summary_df = pd.DataFrame(ride_summaries)
    
    # Format decimals dynamically for readability
    format_mapping = {
        'Duration (h)': '{:.2f}',
        'Fluid (L)': '{:.3f}',
        'Avg Sweat (L/h)': '{:.2f}',
        'Avg Speed (km/h)': '{:.1f}',
        'Avg Torque (Nm)': '{:.1f}',
        'Avg Skin Temp (°C)': '{:.1f}'
    }
    
    for col, fmt in format_mapping.items():
        summary_df[col] = summary_df[col].apply(lambda x: fmt.format(x) if pd.notnull(x) else 'N/A')
        
    # Sort by date naturally
    summary_df = summary_df.sort_values(by='Date', ascending=False).reset_index(drop=True)
    
    # Hack to allow wide dataframe printing in terminal without wrapping aggressively
    pd.set_option('display.max_rows', 50)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)
    
    print(summary_df.to_string(index=False))
    
    print("\n>>> Analysis complete. Keep generating data!")

if __name__ == "__main__":
    main()
