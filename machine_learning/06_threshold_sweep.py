import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestClassifier
    import joblib
except ImportError:
    print("Error: pip install scikit-learn joblib")
    sys.exit(1)

# ── Config ────────────────────────────────────────────────────────────────────

FEATURE_COLS = [
    'exertion_debt_kj',
    'exertion_intensity_kj_per_min',
    'humidity_pct',
    'temp_c',
    'torque_rolling_3min',
]

# Thresholds to sweep — from aggressive (early, more FP) to conservative (late, fewer FP)
THRESHOLDS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.75]

# Sustained trigger: probability must exceed threshold for this many consecutive
# rows before the model is considered to have "triggered". At ~1s/row, 30 = 30s.
SUSTAINED_READINGS = 30

# Rides where onset occurs within this many minutes of ride start are excluded
# from lead time analysis — insufficient precursor window to evaluate prediction.
MIN_ONSET_MINUTES = 5.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def first_sustained_trigger(proba, threshold, sustained):
    """Return index of first sustained trigger, or None if never triggered."""
    run = 0
    for i, p in enumerate(proba):
        if p > threshold:
            run += 1
            if run >= sustained:
                return i - sustained + 1
        else:
            run = 0
    return None


def lead_time_minutes(sensor_onset_idx, trigger_idx):
    """Convert row indices to minutes (1s per row) and return lead time."""
    sensor_min  = sensor_onset_idx / 60.0
    trigger_min = trigger_idx      / 60.0
    return sensor_min - trigger_min   # positive = model ahead of sensor


def false_positive_rate(proba, y_true, threshold):
    """
    FP rate = fraction of truly-dry readings where model exceeds threshold.
    Only counts dry periods (y_true == 0).
    """
    dry_mask = y_true == 0
    if dry_mask.sum() == 0:
        return 0.0
    return (proba[dry_mask] > threshold).mean()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  STEP 6: THRESHOLD SWEEP")
    print("  Lead time and false positive rate vs decision threshold")
    print("=" * 65)

    base_dir     = os.path.dirname(os.path.abspath(__file__))
    graphics_dir = os.path.join(base_dir, 'graphics')
    os.makedirs(graphics_dir, exist_ok=True)

    # ── Load data ─────────────────────────────────────────────────────────────
    csv_path = os.path.join(base_dir, 'ml_ready_dataset.csv')
    if not os.path.exists(csv_path):
        print("Error: ml_ready_dataset.csv not found. Run Step 2 first.")
        return

    df = pd.read_csv(csv_path)
    df = df.dropna(subset=FEATURE_COLS + ['is_sweating'])
    print(f"Loaded {len(df)} rows across {df['ride_id'].nunique()} rides.")

    # ── Train model (identical setup to script 04) ────────────────────────────
    all_ride_ids = df['ride_id'].unique()
    train_ids, test_ids = train_test_split(all_ride_ids, test_size=0.2, random_state=42)

    train_mask = df['ride_id'].isin(train_ids)
    test_mask  = df['ride_id'].isin(test_ids)

    X_train = df.loc[train_mask, FEATURE_COLS]
    y_train = df.loc[train_mask, 'is_sweating']

    print(f"\nTraining Random Forest on {len(X_train)} rows "
          f"({len(train_ids)} rides)...")
    clf = RandomForestClassifier(
        n_estimators=100, max_depth=10,
        random_state=42, n_jobs=-1, class_weight='balanced'
    )
    clf.fit(X_train, y_train)
    print("Done.\n")

    # ── Pre-compute per-ride probabilities on test set ────────────────────────
    ride_data = {}
    skipped   = []

    for rid in sorted(test_ids):
        mask       = df['ride_id'] == rid
        X_ride     = df.loc[mask, FEATURE_COLS]
        y_ride     = df.loc[mask, 'is_sweating'].values
        proba_ride = clf.predict_proba(X_ride)[:, 1]

        sweating_idxs = np.where(y_ride == 1)[0]
        if len(sweating_idxs) == 0:
            skipped.append((rid, 'no sweat onset recorded'))
            continue

        sensor_onset_idx = sweating_idxs[0]
        onset_min        = sensor_onset_idx / 60.0

        if onset_min < MIN_ONSET_MINUTES:
            skipped.append((rid, f'onset at {onset_min:.1f} min — too early'))
            continue

        ride_data[rid] = {
            'proba':            proba_ride,
            'y_true':           y_ride,
            'sensor_onset_idx': sensor_onset_idx,
            'onset_min':        onset_min,
        }

    print(f"Rides used in sweep : {len(ride_data)}")
    for rid, reason in skipped:
        print(f"  Skipped {rid}: {reason}")

    if not ride_data:
        print("\nNo rides available for sweep — check exclusion criteria.")
        return

    # ── Sweep ─────────────────────────────────────────────────────────────────
    print(f"\n{'Threshold':>10}  {'Mean lead (min)':>16}  "
          f"{'FP rate':>9}  {'Rides triggered':>16}")
    print("-" * 58)

    sweep_results = []

    for thresh in THRESHOLDS:
        lead_times = []
        fp_rates   = []
        n_triggered = 0

        for rid, rd in ride_data.items():
            # Lead time
            trigger_idx = first_sustained_trigger(
                rd['proba'], thresh, SUSTAINED_READINGS
            )
            if trigger_idx is not None:
                lt = lead_time_minutes(rd['sensor_onset_idx'], trigger_idx)
                lead_times.append(lt)
                n_triggered += 1
            # FP rate (independent of whether trigger fires)
            fp_rates.append(false_positive_rate(rd['proba'], rd['y_true'], thresh))

        mean_lead = np.mean(lead_times) if lead_times else float('nan')
        mean_fp   = np.mean(fp_rates)

        sweep_results.append({
            'threshold':    thresh,
            'mean_lead_min': mean_lead,
            'mean_fp_rate':  mean_fp,
            'n_triggered':  n_triggered,
            'n_rides':      len(ride_data),
            'lead_times':   lead_times,
        })

        lead_str = f"{mean_lead:+.1f}" if not np.isnan(mean_lead) else "  N/A"
        print(f"{thresh:>10.2f}  {lead_str:>16}  "
              f"{mean_fp*100:>8.1f}%  "
              f"{n_triggered:>4}/{len(ride_data)}")

    # ── Per-ride breakdown at each threshold ──────────────────────────────────
    print(f"\n--- Per-ride lead times (minutes, + = model early) ---")
    header = f"{'Ride':<28}" + "".join(f"{t:>7.2f}" for t in THRESHOLDS)
    print(header)
    print("-" * len(header))

    for rid, rd in ride_data.items():
        row = f"{rid.replace('RIDE_',''):<28}"
        for thresh in THRESHOLDS:
            trig = first_sustained_trigger(rd['proba'], thresh, SUSTAINED_READINGS)
            if trig is None:
                row += f"{'--':>7}"
            else:
                lt = lead_time_minutes(rd['sensor_onset_idx'], trig)
                row += f"{lt:>+7.1f}"
        print(row)

    # ── Plot 1: Lead time vs threshold ────────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    mean_leads = [r['mean_lead_min'] for r in sweep_results]
    fp_rates   = [r['mean_fp_rate'] * 100 for r in sweep_results]

    # Individual ride lines
    for rid, rd in ride_data.items():
        ride_leads = []
        for thresh in THRESHOLDS:
            trig = first_sustained_trigger(rd['proba'], thresh, SUSTAINED_READINGS)
            ride_leads.append(
                lead_time_minutes(rd['sensor_onset_idx'], trig)
                if trig is not None else np.nan
            )
        ax1.plot(THRESHOLDS, ride_leads, 'o--', alpha=0.4, linewidth=1,
                 label=rid.replace('RIDE_', ''))

    ax1.plot(THRESHOLDS, mean_leads, 'o-', color='#8E44AD', linewidth=2.5,
             label='Mean', zorder=5)
    ax1.axhline(0, color='black', linewidth=0.8, linestyle='--')
    ax1.set_ylabel('Lead Time (minutes)\n+ = model early   − = model late')
    ax1.set_title('Threshold Sweep: Lead Time and False Positive Rate')
    ax1.legend(fontsize=8, loc='upper right')
    ax1.grid(True, linestyle='--', alpha=0.3)

    ax2.plot(THRESHOLDS, fp_rates, 'o-', color='#E74C3C', linewidth=2.5)
    ax2.set_xlabel('Decision Threshold')
    ax2.set_ylabel('Mean False Positive Rate (%)\n(dry readings above threshold)')
    ax2.grid(True, linestyle='--', alpha=0.3)

    plt.tight_layout()
    sweep_path = os.path.join(graphics_dir, '06_threshold_sweep.png')
    plt.savefig(sweep_path, dpi=150)
    plt.close()
    print(f"\n-> Saved sweep chart: {sweep_path}")

    # ── Recommendation ────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  OPERATING POINT RECOMMENDATION")
    print("=" * 65)

    # Find threshold with best positive lead time and FP rate < 20%
    candidates = [
        r for r in sweep_results
        if not np.isnan(r['mean_lead_min'])
        and r['mean_lead_min'] > 0
        and r['mean_fp_rate'] < 0.20
    ]

    if candidates:
        best = max(candidates, key=lambda r: r['mean_lead_min'])
        print(f"  Best threshold (lead time > 0, FP rate < 20%):")
        print(f"  Threshold = {best['threshold']:.2f} | "
              f"Mean lead = {best['mean_lead_min']:+.1f} min | "
              f"FP rate = {best['mean_fp_rate']*100:.1f}%")
    else:
        print("  No threshold achieved positive lead time with FP rate < 20%.")
        print("  Consider label-shifting the training target.")

    print("\n✅ Step 6 Complete.")


if __name__ == "__main__":
    main()
