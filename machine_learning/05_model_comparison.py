import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# --- Core ML imports ---
try:
    from sklearn.model_selection import train_test_split, GroupKFold
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, classification_report
    import joblib
except ImportError:
    print("Error: pip install scikit-learn joblib")
    sys.exit(1)

# --- LightGBM (optional) ---
try:
    import lightgbm as lgb
    LGBM_AVAILABLE = True
except ImportError:
    LGBM_AVAILABLE = False
    print("⚠️  LightGBM not installed — skipping. Run: pip install lightgbm")

# --- TensorFlow/Keras for LSTM (optional) ---
try:
    import tensorflow as tf
    from tensorflow.keras.models import Sequential
    from tensorflow.keras.layers import LSTM, Dense, Dropout
    from tensorflow.keras.callbacks import EarlyStopping
    tf.get_logger().setLevel('ERROR')
    LSTM_AVAILABLE = True
except ImportError:
    LSTM_AVAILABLE = False
    print("⚠️  TensorFlow not installed — skipping LSTM. Run: pip install tensorflow")


# ── Shared config ────────────────────────────────────────────────────────────

FEATURE_COLS = [
    'exertion_debt_kj',
    'exertion_intensity_kj_per_min',
    'humidity_pct',
    'temp_c',
    'torque_rolling_3min',
]
TARGET_COL   = 'is_sweating'
RANDOM_STATE = 42
N_CV_FOLDS   = 5

# LSTM sequence window — how many consecutive 50ms readings form one input sequence.
# 200 steps = 10 seconds of riding context fed into the network.
LSTM_WINDOW  = 200
LSTM_STRIDE  = 20   # step between windows (1 second), keeps dataset size manageable


# ── Data loading ─────────────────────────────────────────────────────────────

def load_data():
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_ready_dataset.csv')
    if not os.path.exists(csv_path):
        print("Error: ml_ready_dataset.csv not found. Run Step 2 first.")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    df = df.dropna(subset=FEATURE_COLS + [TARGET_COL])
    print(f"Loaded {len(df)} rows across {df['ride_id'].nunique()} rides.")
    return df


# ── Ride-level CV helper ──────────────────────────────────────────────────────

def ride_level_cv(model_factory, X, y, groups, scale=False):
    """
    Run GroupKFold CV keeping rides intact across folds.
    model_factory: callable that returns a fresh unfitted model.
    scale: whether to StandardScale features (needed for Logistic Regression).
    Returns list of per-fold accuracy scores.
    """
    gkf = GroupKFold(n_splits=N_CV_FOLDS)
    scores = []
    for fold, (tr_idx, te_idx) in enumerate(gkf.split(X, y, groups), start=1):
        X_tr, X_te = X.iloc[tr_idx], X.iloc[te_idx]
        y_tr, y_te = y.iloc[tr_idx], y.iloc[te_idx]

        if scale:
            scaler = StandardScaler()
            X_tr = scaler.fit_transform(X_tr)
            X_te = scaler.transform(X_te)

        clf = model_factory()
        clf.fit(X_tr, y_tr)
        scores.append(accuracy_score(y_te, clf.predict(X_te)))
    return scores


# ── LSTM sequence builder ─────────────────────────────────────────────────────

def build_lstm_sequences(df, feature_cols, target_col, window, stride):
    """
    For each ride, slide a window of `window` rows across the data with step `stride`.
    Each sequence is labelled with the target value of its final timestep.
    Returns X (n_sequences, window, n_features), y (n_sequences,), groups (n_sequences,).
    """
    X_seqs, y_seqs, groups = [], [], []

    for ride_id, ride_df in df.groupby('ride_id'):
        ride_df = ride_df.reset_index(drop=True)
        features = ride_df[feature_cols].values
        targets  = ride_df[target_col].values

        for start in range(0, len(ride_df) - window, stride):
            end = start + window
            X_seqs.append(features[start:end])
            y_seqs.append(targets[end - 1])   # label = last timestep of the window
            groups.append(ride_id)

    return np.array(X_seqs), np.array(y_seqs), np.array(groups)


def run_lstm_cv(X_seq, y_seq, groups, n_features):
    """
    Run GroupKFold CV for the LSTM.
    Builds and trains a fresh Keras model each fold.
    """
    unique_groups = np.array(groups)
    gkf = GroupKFold(n_splits=N_CV_FOLDS)
    scores = []

    for fold, (tr_idx, te_idx) in enumerate(gkf.split(X_seq, y_seq, unique_groups), start=1):
        X_tr, X_te = X_seq[tr_idx], X_seq[te_idx]
        y_tr, y_te = y_seq[tr_idx], y_seq[te_idx]

        # Scale each feature across the training sequences
        scaler = StandardScaler()
        shape  = X_tr.shape
        X_tr   = scaler.fit_transform(X_tr.reshape(-1, n_features)).reshape(shape)
        X_te   = scaler.transform(X_te.reshape(-1, n_features)).reshape(X_te.shape)

        model = Sequential([
            LSTM(64, input_shape=(LSTM_WINDOW, n_features), return_sequences=False),
            Dropout(0.3),
            Dense(32, activation='relu'),
            Dense(1, activation='sigmoid')
        ])
        model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy'])

        early_stop = EarlyStopping(monitor='val_loss', patience=3, restore_best_weights=True)
        model.fit(
            X_tr, y_tr,
            epochs=20,
            batch_size=256,
            validation_split=0.1,
            callbacks=[early_stop],
            verbose=0
        )

        y_pred = (model.predict(X_te, verbose=0) > 0.5).astype(int).flatten()
        score  = accuracy_score(y_te, y_pred)
        scores.append(score)
        print(f"    Fold {fold}: {score*100:.2f}%")

    return scores


# ── Results table & plot ──────────────────────────────────────────────────────

def print_results_table(results):
    print("\n" + "="*65)
    print(f"  {'Model':<28} {'CV Mean':>10} {'CV Std':>10} {'Verdict':>12}")
    print("  " + "-"*60)
    for name, scores in results.items():
        mean = np.mean(scores) * 100
        std  = np.std(scores)  * 100
        verdict = "✅ Stable" if std < 8 else "⚠️  Variable"
        print(f"  {name:<28} {mean:>9.2f}% {std:>9.2f}%  {verdict}")
    print("="*65)


def plot_results(results, output_dir):
    names  = list(results.keys())
    means  = [np.mean(s) * 100 for s in results.values()]
    stds   = [np.std(s)  * 100 for s in results.values()]
    colors = ['#8E44AD', '#2ECC71', '#E67E22', '#3498DB'][:len(names)]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(names, means, yerr=stds, capsize=6, color=colors, alpha=0.85, edgecolor='black')

    for bar, mean, std in zip(bars, means, stds):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + std + 0.5,
                f'{mean:.1f}%', ha='center', va='bottom', fontweight='bold', fontsize=11)

    ax.set_ylabel('CV Accuracy (%)', fontsize=12)
    ax.set_title('Model Comparison: 5-Fold Ride-Level Cross-Validation Accuracy', fontsize=13, fontweight='bold')
    ax.set_ylim(50, 105)
    ax.axhline(y=np.mean(results[list(results.keys())[0]] ) * 100,
               color='grey', linestyle='--', alpha=0.4, label='RF baseline')
    ax.grid(axis='y', linestyle='--', alpha=0.3)
    plt.tight_layout()

    path = os.path.join(output_dir, '05_model_comparison.png')
    plt.savefig(path)
    plt.close()
    print(f"\n-> Saved comparison chart: {path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("="*65)
    print("  STEP 5: MODEL COMPARISON")
    print("  Random Forest vs Logistic Regression vs LightGBM vs LSTM")
    print("="*65)

    df      = load_data()
    X       = df[FEATURE_COLS]
    y       = df[TARGET_COL]
    groups  = df['ride_id']
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'graphics')
    os.makedirs(out_dir, exist_ok=True)

    results = {}

    # ── 1. Random Forest (baseline — same config as script 04) ───────────────
    print("\n[1/4] Random Forest (baseline)...")
    rf_scores = ride_level_cv(
        lambda: RandomForestClassifier(n_estimators=100, max_depth=10, random_state=RANDOM_STATE, n_jobs=-1),
        X, y, groups
    )
    for i, s in enumerate(rf_scores, 1):
        print(f"    Fold {i}: {s*100:.2f}%")
    results['Random Forest'] = rf_scores

    # ── 2. Logistic Regression (simple linear baseline) ──────────────────────
    # Tests whether the problem is linearly separable — if this matches RF,
    # the complex model isn't justified.
    print("\n[2/4] Logistic Regression (linear baseline)...")
    lr_scores = ride_level_cv(
        lambda: LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
        X, y, groups, scale=True
    )
    for i, s in enumerate(lr_scores, 1):
        print(f"    Fold {i}: {s*100:.2f}%")
    results['Logistic Regression'] = lr_scores

    # ── 3. LightGBM (sequential boosting — state-of-the-art tabular) ─────────
    # Builds trees sequentially, each correcting errors of the previous.
    # Generally the strongest model on tabular data with this structure.
    if LGBM_AVAILABLE:
        print("\n[3/4] LightGBM (gradient boosting)...")
        lgbm_scores = ride_level_cv(
            lambda: lgb.LGBMClassifier(n_estimators=200, max_depth=6,
                                        learning_rate=0.05, random_state=RANDOM_STATE,
                                        verbose=-1, n_jobs=-1),
            X, y, groups
        )
        for i, s in enumerate(lgbm_scores, 1):
            print(f"    Fold {i}: {s*100:.2f}%")
        results['LightGBM'] = lgbm_scores
    else:
        print("\n[3/4] LightGBM — SKIPPED (not installed)")

    # ── 4. LSTM (sequence model — learns temporal patterns across 10s windows) ─
    # Fundamentally different approach: instead of treating each 50ms reading
    # as independent, the LSTM sees a 10-second sequence of readings and learns
    # what patterns of effort and temperature *over time* precede sweat onset.
    if LSTM_AVAILABLE:
        print("\n[4/4] LSTM (sequential deep learning — 10s windows)...")
        print(f"    Building sequences (window={LSTM_WINDOW} steps, stride={LSTM_STRIDE})...")
        X_seq, y_seq, seq_groups = build_lstm_sequences(df, FEATURE_COLS, TARGET_COL,
                                                         LSTM_WINDOW, LSTM_STRIDE)
        print(f"    Generated {len(X_seq)} sequences from {df['ride_id'].nunique()} rides.")
        lstm_scores = run_lstm_cv(X_seq, y_seq, seq_groups, n_features=len(FEATURE_COLS))
        results['LSTM'] = lstm_scores
    else:
        print("\n[4/4] LSTM — SKIPPED (TensorFlow not installed)")

    # ── Results ───────────────────────────────────────────────────────────────
    print_results_table(results)
    plot_results(results, out_dir)

    # Best model verdict
    best_name  = max(results, key=lambda k: np.mean(results[k]))
    best_mean  = np.mean(results[best_name]) * 100
    print(f"\n  Best model: {best_name} at {best_mean:.2f}% CV accuracy")
    print("\n✅ Step 5 Complete.")


if __name__ == "__main__":
    main()
