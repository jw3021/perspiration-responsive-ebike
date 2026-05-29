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
    from sklearn.metrics import accuracy_score, recall_score, precision_score
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

TARGET_COL = 'above_fluid_threshold'

# Decision thresholds to sweep
THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]

# Sustained trigger: model probability must exceed threshold for this many
# consecutive rows before counting as a trigger (~1s per row, so 30 = 30s)
SUSTAINED_READINGS = 30

# Rides where threshold crossing occurs within this many minutes of ride start
# are excluded — not enough precursor window to evaluate early prediction
MIN_ONSET_MINUTES = 3.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def first_sustained_trigger(proba, threshold, sustained):
    run = 0
    for i, p in enumerate(proba):
        if p > threshold:
            run += 1
            if run >= sustained:
                return i - sustained + 1
        else:
            run = 0
    return None


def lead_time_minutes(onset_idx, trigger_idx):
    return (onset_idx - trigger_idx) / 60.0  # positive = model early


def false_positive_rate(proba, y_true, threshold):
    dry_mask = y_true == 0
    if dry_mask.sum() == 0:
        return 0.0
    return (proba[dry_mask] > threshold).mean()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 65)
    print("  FLUID LOSS MODEL — STEP 6: THRESHOLD SWEEP")
    print("  Decision threshold vs recall, lead time, false positive rate")
    print("=" * 65)

    base_dir     = os.path.dirname(os.path.abspath(__file__))
    graphics_dir = os.path.join(base_dir, 'graphics')
    os.makedirs(graphics_dir, exist_ok=True)

    csv_path = os.path.join(base_dir, 'training_dataset.csv')
    if not os.path.exists(csv_path):
        print("Error: training_dataset.csv not found. Run 02_feature_engineering.py first.")
        return

    df = pd.read_csv(csv_path)
    df = df.dropna(subset=FEATURE_COLS + [TARGET_COL])
    print(f"Loaded {len(df)} rows across {df['ride_id'].nunique()} rides.")

    n_pos = (df[TARGET_COL] == 1).sum()
    print(f"Label balance — above threshold: {n_pos} ({n_pos/len(df)*100:.1f}%)")

    all_ride_ids = df['ride_id'].unique()
    train_ids, test_ids = train_test_split(all_ride_ids, test_size=0.2, random_state=42)

    train_mask = df['ride_id'].isin(train_ids)
    X_train = df.loc[train_mask, FEATURE_COLS]
    y_train = df.loc[train_mask, TARGET_COL]

    print(f"\nTraining Random Forest on {len(train_ids)} rides...")
    clf = RandomForestClassifier(
        n_estimators=100, max_depth=10,
        random_state=42, n_jobs=-1, class_weight='balanced'
    )
    clf.fit(X_train, y_train)
    print("Done.\n")

    # ── Per-ride probability and onset index for test rides ───────────────────
    ride_data = {}
    skipped   = []

    for rid in sorted(test_ids):
        mask       = df['ride_id'] == rid
        y_ride     = df.loc[mask, TARGET_COL].values
        proba_ride = clf.predict_proba(df.loc[mask, FEATURE_COLS])[:, 1]

        onset_idxs = np.where(y_ride == 1)[0]
        if len(onset_idxs) == 0:
            skipped.append((rid, 'never crossed fluid threshold'))
            continue

        onset_idx  = onset_idxs[0]
        onset_min  = onset_idx / 60.0

        if onset_min < MIN_ONSET_MINUTES:
            skipped.append((rid, f'onset at {onset_min:.1f} min — too early'))
            continue

        ride_data[rid] = {
            'proba':      proba_ride,
            'y_true':     y_ride,
            'onset_idx':  onset_idx,
            'onset_min':  onset_min,
        }

    print(f"Rides used in sweep : {len(ride_data)}")
    for rid, reason in skipped:
        print(f"  Skipped {rid}: {reason}")

    if not ride_data:
        print("\nNo rides available for sweep.")
        return

    # ── Sweep ─────────────────────────────────────────────────────────────────
    print(f"\n{'Threshold':>10}  {'Recall (above)':>15}  {'Mean lead (min)':>16}  "
          f"{'FP rate':>9}  {'Triggered':>10}")
    print("-" * 70)

    sweep_results = []

    for thresh in THRESHOLDS:
        lead_times  = []
        fp_rates    = []
        recalls     = []
        n_triggered = 0

        for rid, rd in ride_data.items():
            # Recall at this threshold (binary prediction)
            y_pred = (rd['proba'] > thresh).astype(int)
            if rd['y_true'].sum() > 0:
                recalls.append(recall_score(rd['y_true'], y_pred, zero_division=0))

            # Lead time
            trigger_idx = first_sustained_trigger(rd['proba'], thresh, SUSTAINED_READINGS)
            if trigger_idx is not None:
                lead_times.append(lead_time_minutes(rd['onset_idx'], trigger_idx))
                n_triggered += 1

            fp_rates.append(false_positive_rate(rd['proba'], rd['y_true'], thresh))

        mean_recall = np.mean(recalls)   if recalls    else float('nan')
        mean_lead   = np.mean(lead_times) if lead_times else float('nan')
        mean_fp     = np.mean(fp_rates)

        sweep_results.append({
            'threshold':     thresh,
            'mean_recall':   mean_recall,
            'mean_lead_min': mean_lead,
            'mean_fp_rate':  mean_fp,
            'n_triggered':   n_triggered,
        })

        lead_str   = f"{mean_lead:+.1f}" if not np.isnan(mean_lead) else "  N/A"
        recall_str = f"{mean_recall*100:.1f}%" if not np.isnan(mean_recall) else " N/A"
        print(f"{thresh:>10.2f}  {recall_str:>15}  {lead_str:>16}  "
              f"{mean_fp*100:>8.1f}%  {n_triggered:>4}/{len(ride_data)}")

    # ── Plot ──────────────────────────────────────────────────────────────────
    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(10, 11), sharex=True)

    ts         = [r['threshold']    for r in sweep_results]
    recalls    = [r['mean_recall']  * 100 for r in sweep_results]
    lead_times = [r['mean_lead_min'] for r in sweep_results]
    fp_rates   = [r['mean_fp_rate'] * 100 for r in sweep_results]

    ax1.plot(ts, recalls, 'o-', color='#2ECC71', linewidth=2.5)
    ax1.axhline(70, color='grey', linestyle='--', linewidth=0.8, label='70% recall target')
    ax1.set_ylabel('Recall on Above-Threshold Class (%)')
    ax1.set_title('Fluid Loss Model — Threshold Sweep')
    ax1.legend(fontsize=9)
    ax1.grid(True, linestyle='--', alpha=0.3)
    ax1.set_ylim(0, 105)

    ax2.plot(ts, lead_times, 'o-', color='#8E44AD', linewidth=2.5)
    ax2.axhline(0, color='black', linewidth=0.8, linestyle='--')
    ax2.set_ylabel('Mean Lead Time (min)\n+ = model early   − = model late')
    ax2.grid(True, linestyle='--', alpha=0.3)

    ax3.plot(ts, fp_rates, 'o-', color='#E74C3C', linewidth=2.5)
    ax3.set_xlabel('Decision Threshold')
    ax3.set_ylabel('Mean False Positive Rate (%)\n(sub-threshold readings above threshold)')
    ax3.grid(True, linestyle='--', alpha=0.3)

    plt.tight_layout()
    sweep_path = os.path.join(graphics_dir, '06_threshold_sweep_fluid.png')
    plt.savefig(sweep_path, dpi=150)
    plt.close()
    print(f"\n-> Saved sweep chart: {sweep_path}")

    # ── Recommendation ────────────────────────────────────────────────────────
    print("\n" + "=" * 65)
    print("  OPERATING POINT RECOMMENDATION")
    print("=" * 65)

    candidates = [
        r for r in sweep_results
        if not np.isnan(r['mean_recall'])
        and r['mean_recall'] >= 0.70
        and r['mean_fp_rate'] < 0.30
    ]

    if candidates:
        # Among those meeting recall ≥ 70% and FP < 30%, pick best lead time
        best = max(candidates, key=lambda r: r['mean_lead_min'] if not np.isnan(r['mean_lead_min']) else -999)
        print(f"  Best threshold (recall ≥ 70%, FP rate < 30%):")
        print(f"  Threshold = {best['threshold']:.2f} | "
              f"Recall = {best['mean_recall']*100:.1f}% | "
              f"Mean lead = {best['mean_lead_min']:+.1f} min | "
              f"FP rate = {best['mean_fp_rate']*100:.1f}%")
    else:
        print("  No threshold achieved recall ≥ 70% with FP rate < 30%.")
        print("  Best available (highest recall):")
        best = max(sweep_results, key=lambda r: r['mean_recall'] if not np.isnan(r['mean_recall']) else 0)
        print(f"  Threshold = {best['threshold']:.2f} | "
              f"Recall = {best['mean_recall']*100:.1f}% | "
              f"FP rate = {best['mean_fp_rate']*100:.1f}%")

    print("\n✅ Sweep complete.")


if __name__ == "__main__":
    main()
