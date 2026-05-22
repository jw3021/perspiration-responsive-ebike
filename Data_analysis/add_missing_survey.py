"""
add_missing_survey.py
---------------------
Manually add a post-ride comfort rating when the phone died before
the survey could be submitted from the dashboard.

Finds the most recent ride across both tables, shows you the ride
details to confirm, then inserts a score into ride_surveys.

Usage:
    python Data_analysis/add_missing_survey.py
"""

import sys
import os
import re
from datetime import datetime

# --- Credentials (same safe pattern as other Data_analysis scripts) ---
try:
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.py')
    with open(config_path, 'r') as f:
        config_text = f.read()

    SUPABASE_URL = re.search(r'SUPABASE_URL\s*=\s*["\']([^"\']+)["\']', config_text).group(1)
    SUPABASE_KEY = re.search(r'SUPABASE_KEY\s*=\s*["\']([^"\']+)["\']', config_text).group(1)

    from supabase import create_client
except Exception as e:
    print(f"Error loading credentials: {e}")
    print("Ensure config.py exists and run: pip install supabase")
    sys.exit(1)

SCORE_LABELS = {
    1: "Completely Dry",
    2: "Lightly Sweating",
    3: "Moderately Sweaty",
    4: "Very Sweaty",
    5: "Max Effort (Dripping)",
}


def find_most_recent_ride(client):
    """
    Queries both ride tables and returns the ride with the latest timestamp.
    Returns (ride_id, table_name, start_time, end_time, row_count).
    """
    candidates = []

    for table in ("ride_metrics_v2", "actuation_ride_metrics_v1"):
        try:
            # Get the single most-recent row for this table
            resp = (
                client.table(table)
                .select("ride_id, timestamp")
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
            )
            if resp.data:
                row = resp.data[0]
                candidates.append((row["ride_id"], table, row["timestamp"]))
        except Exception as e:
            print(f"  Warning: could not query {table}: {e}")

    if not candidates:
        print("No rides found in either table.")
        sys.exit(1)

    # Pick whichever table had the more recent row
    candidates.sort(key=lambda x: x[2], reverse=True)
    ride_id, table, _ = candidates[0]

    # Fetch start time, end time, and row count separately to avoid the 1000-row cap
    start_resp = (
        client.table(table)
        .select("timestamp")
        .eq("ride_id", ride_id)
        .order("timestamp", desc=False)
        .limit(1)
        .execute()
    )
    end_resp = (
        client.table(table)
        .select("timestamp")
        .eq("ride_id", ride_id)
        .order("timestamp", desc=True)
        .limit(1)
        .execute()
    )
    count_resp = (
        client.table(table)
        .select("*", count="exact")
        .eq("ride_id", ride_id)
        .limit(1)
        .execute()
    )

    start_ts = start_resp.data[0]["timestamp"]
    end_ts   = end_resp.data[0]["timestamp"]
    count    = count_resp.count

    # Parse for display
    fmt = "%Y-%m-%dT%H:%M:%S.%f" if "." in start_ts else "%Y-%m-%dT%H:%M:%S"
    start_dt = datetime.fromisoformat(start_ts[:26])
    end_dt   = datetime.fromisoformat(end_ts[:26])
    duration = end_dt - start_dt

    return ride_id, table, start_dt, end_dt, duration, count


def survey_already_exists(client, ride_id):
    resp = (
        client.table("ride_surveys")
        .select("ride_id, sweat_perception_score")
        .eq("ride_id", ride_id)
        .execute()
    )
    return resp.data  # empty list = no existing survey


def main():
    print("=" * 55)
    print("  ADD MISSING POST-RIDE SURVEY")
    print("=" * 55)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    print("\nSearching for most recent ride...")
    ride_id, table, start_dt, end_dt, duration, count = find_most_recent_ride(client)

    total_minutes = int(duration.total_seconds() // 60)
    total_seconds = int(duration.total_seconds() % 60)

    print(f"\n  Ride ID  : {ride_id}")
    print(f"  Table    : {table}")
    print(f"  Started  : {start_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Ended    : {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Duration : {total_minutes}m {total_seconds}s")
    print(f"  Rows     : {count}")

    # Check for an existing survey
    existing = survey_already_exists(client, ride_id)
    if existing:
        score = existing[0]['sweat_perception_score']
        label = SCORE_LABELS.get(score, "Unknown")
        print(f"\n  ⚠️  A survey already exists for this ride: {score}/5 — {label}")
        confirm = input("  Overwrite it with a new score? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Aborted — no changes made.")
            sys.exit(0)

    # Confirm this is the right ride
    print()
    confirm = input("Is this the correct ride? (y/n): ").strip().lower()
    if confirm != 'y':
        # Let them type a ride_id manually
        ride_id = input("Enter the ride_id manually (e.g. RIDE_20260517_143200): ").strip()
        if not ride_id:
            print("No ride_id entered. Aborted.")
            sys.exit(0)

    # Prompt for score
    print("\nSweat rating scale:")
    for k, v in SCORE_LABELS.items():
        print(f"  {k} — {v}")

    while True:
        raw = input("\nEnter your score (1–5): ").strip()
        if raw.isdigit() and int(raw) in SCORE_LABELS:
            score = int(raw)
            break
        print("  Invalid — please enter a number between 1 and 5.")

    print(f"\n  Submitting: ride_id={ride_id}, score={score} ({SCORE_LABELS[score]})")

    try:
        if existing:
            # Update the existing row
            client.table("ride_surveys").update(
                {"sweat_perception_score": score}
            ).eq("ride_id", ride_id).execute()
        else:
            client.table("ride_surveys").insert({
                "ride_id": ride_id,
                "sweat_perception_score": score,
            }).execute()

        print(f"\n  ✅ Survey saved successfully for {ride_id}.")
    except Exception as e:
        print(f"\n  ❌ Upload failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
