import os
import pandas as pd

df = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_ready_dataset.csv'))
df['timestamp'] = pd.to_datetime(df['timestamp'])

print(f"{'Ride':<32} {'Rows':>7} {'Duration':>12} {'Avg gap (ms)':>14}")
print('-' * 70)

for rid, g in df.groupby('ride_id'):
    g = g.sort_values('timestamp')
    rows     = len(g)
    duration = (g['timestamp'].iloc[-1] - g['timestamp'].iloc[0]).total_seconds()
    avg_gap  = duration / rows * 1000 if rows > 1 else 0
    mins, secs = divmod(int(duration), 60)
    print(f"{rid:<32} {rows:>7} {mins:>5}m {secs:>02}s      {avg_gap:>8.0f} ms")

durations = []
for rid, g in df.groupby('ride_id'):
    g = g.sort_values('timestamp')
    durations.append((g['timestamp'].iloc[-1] - g['timestamp'].iloc[0]).total_seconds() / 60)

import numpy as np
durations = pd.Series(durations)
print()
print(f"Min ride duration : {durations.min():.1f} min")
print(f"Max ride duration : {durations.max():.1f} min")
print(f"Mean ride duration: {durations.mean():.1f} min")
print()
print("NOTE: If avg gap >> 50ms, rows are NOT at 50ms resolution.")
print("This means the label-shift row count must use timestamps, not row index.")
