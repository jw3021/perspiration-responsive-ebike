import os
import sys
import pandas as pd
import numpy as np
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import plot_style
plot_style.apply()

try:
    from sklearn.model_selection import train_test_split, GroupKFold
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (accuracy_score, classification_report,
                                 confusion_matrix, ConfusionMatrixDisplay,
                                 roc_curve, auc)
    import joblib
except ImportError:
    print("Error: pip install scikit-learn joblib")
    sys.exit(1)

FEATURE_COLS = [
    'exertion_debt_kj',
    'exertion_intensity_kj_per_min',
    'humidity_pct',
    'temp_c',
    'torque_rolling_3min',
]

TARGET_COL = 'above_fluid_threshold'


def main():
    print("=" * 60)
    print(" FLUID LOSS MODEL — STEP 4: TRAIN DIGITAL TWIN")
    print("=" * 60)

    base_dir     = os.path.dirname(os.path.abspath(__file__))
    graphics_dir = os.path.join(base_dir, 'graphics')
    os.makedirs(graphics_dir, exist_ok=True)

    csv_path = os.path.join(base_dir, 'ml_ready_dataset_fluid.csv')
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found. Run 02_feature_engineering_fluid.py first.")
        return

    df = pd.read_csv(csv_path)
    df = df.dropna(subset=FEATURE_COLS + [TARGET_COL])
    print(f"Loaded {len(df)} rows across {df['ride_id'].nunique()} rides.")

    n_pos = (df[TARGET_COL] == 1).sum()
    n_neg = (df[TARGET_COL] == 0).sum()
    print(f"Label balance — above threshold: {n_pos} ({n_pos/len(df)*100:.1f}%)  |  below: {n_neg} ({n_neg/len(df)*100:.1f}%)")

    X = df[FEATURE_COLS]
    y = df[TARGET_COL]

    # Ride-level train/test split
    all_ride_ids = df['ride_id'].unique()
    train_ids, test_ids = train_test_split(all_ride_ids, test_size=0.2, random_state=42)

    print(f"\nRide-level split: {len(train_ids)} train / {len(test_ids)} test")
    print(f"  Train: {sorted(train_ids)}")
    print(f"  Test : {sorted(test_ids)}")

    train_mask = df['ride_id'].isin(train_ids)
    test_mask  = df['ride_id'].isin(test_ids)

    X_train, y_train = df.loc[train_mask, FEATURE_COLS], df.loc[train_mask, TARGET_COL]
    X_test,  y_test  = df.loc[test_mask,  FEATURE_COLS], df.loc[test_mask,  TARGET_COL]

    clf = RandomForestClassifier(
        n_estimators=100, max_depth=10,
        random_state=42, n_jobs=-1, class_weight='balanced'
    )
    print("\nTraining Random Forest...")
    clf.fit(X_train, y_train)

    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)

    print("\n" + "=" * 45)
    print(f"  MODEL ACCURACY ON UNSEEN DATA: {acc * 100:.2f}%")
    print("=" * 45)
    print(classification_report(y_test, y_pred, target_names=["Below threshold", "Above threshold"]))

    report = classification_report(y_test, y_pred, target_names=["Below threshold", "Above threshold"], output_dict=True)
    recall_above = report["Above threshold"]["recall"]
    recall_below = report["Below threshold"]["recall"]
    print(f"  Recall on ABOVE class : {recall_above*100:.1f}%  <- % of real threshold crossings caught")
    print(f"  Recall on BELOW class : {recall_below*100:.1f}%  <- % of sub-threshold periods correctly identified")

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred, normalize='true')
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    ConfusionMatrixDisplay(cm, display_labels=["Below threshold", "Above threshold"]).plot(
        ax=ax, cmap=plot_style.thesis_cmap, values_format='.2%', colorbar=False
    )
    ax.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.6)
    plt.tight_layout()
    plt.savefig(os.path.join(graphics_dir, '04_confusion_matrix.png'))
    plt.close()

    # ROC curve
    y_prob = clf.predict_proba(X_test)[:, 1]
    fpr, tpr, _ = roc_curve(y_test, y_prob)
    roc_auc = auc(fpr, tpr)

    plt.figure(figsize=(6, 5))
    plt.plot(fpr, tpr, color=plot_style.PRIMARY, linewidth=1.8, label=f'Random Forest (AUC = {roc_auc:.3f})')
    plt.plot([0, 1], [0, 1], color=plot_style.NEUTRAL, linestyle='--', linewidth=1.0, label='Random guess (AUC = 0.500)')
    plt.xlabel('False positive rate')
    plt.ylabel('True positive rate')
    plt.legend(loc='lower right')
    plt.tight_layout()
    plt.savefig(os.path.join(graphics_dir, '04_roc_curve.png'))
    plt.close()
    print(f"\nAUC = {roc_auc:.3f}")

    # Temporal prediction on one test ride
    sample_ride_id = sorted(test_ids)[0]
    ride_mask  = df['ride_id'] == sample_ride_id
    X_ride     = df.loc[ride_mask, FEATURE_COLS]
    y_ride     = df.loc[ride_mask, TARGET_COL].values
    proba_ride = clf.predict_proba(X_ride)[:, 1]

    fig, ax = plt.subplots(figsize=(14, 5))
    ax.fill_between(range(len(y_ride)), y_ride.astype(float), alpha=0.15,
                    color='#E74C3C', label='Actual: above fluid threshold')
    ax.plot(proba_ride, color='#8E44AD', linewidth=1.2, label='Predicted probability')
    ax.axhline(0.5, color='grey', linestyle='--', linewidth=0.8, label='Decision threshold (0.5)')
    ax.set_ylim(-0.05, 1.15)
    ax.set_xlabel('Reading index (~1s per row)')
    ax.set_ylabel('Probability / Label')
    ax.set_title(f'Temporal Prediction — Ride: {sample_ride_id}\nFluid-Loss Model')
    ax.legend(loc='upper left')
    ax.grid(True, linestyle='--', alpha=0.25)
    plt.tight_layout()
    plt.savefig(os.path.join(graphics_dir, '04_temporal_prediction.png'), dpi=150)
    plt.close()

    # Feature importance
    importances     = clf.feature_importances_
    sorted_indices  = np.argsort(importances)[::-1]
    print("\nFEATURE IMPORTANCE:")
    for i in sorted_indices:
        print(f"  {FEATURE_COLS[i]:>30}: {importances[i]*100:.1f}%")

    plt.figure(figsize=(10, 5))
    plt.bar(range(len(FEATURE_COLS)), importances[sorted_indices], color='#8E44AD')
    plt.xticks(range(len(FEATURE_COLS)), [FEATURE_COLS[i] for i in sorted_indices], rotation=30, ha='right')
    plt.ylabel("Importance")
    plt.title("Feature Importance — Fluid Loss Threshold Model")
    plt.grid(axis='y', linestyle='--', alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(graphics_dir, '04_feature_importance.png'), dpi=150)
    plt.close()

    # 5-fold cross-validation (ride-level)
    print("\n" + "=" * 60)
    print("  5-FOLD CROSS-VALIDATION (Ride-Level)")
    print("=" * 60)
    groups   = df['ride_id']
    X_all    = df[FEATURE_COLS]
    y_all    = df[TARGET_COL]
    n_splits = min(5, len(all_ride_ids))
    gkf      = GroupKFold(n_splits=n_splits)

    fold_scores = []
    for fold, (tr_idx, te_idx) in enumerate(gkf.split(X_all, y_all, groups), start=1):
        fc = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
        fc.fit(X_all.iloc[tr_idx], y_all.iloc[tr_idx])
        score = accuracy_score(y_all.iloc[te_idx], fc.predict(X_all.iloc[te_idx]))
        fold_scores.append(score)
        print(f"  Fold {fold}: {score*100:.2f}%")

    mean_cv = np.mean(fold_scores)
    std_cv  = np.std(fold_scores)
    print(f"\n  CV Accuracy: {mean_cv*100:.2f}% ± {std_cv*100:.2f}%")

    # Learning curve (ride-level)
    print("\n" + "=" * 60)
    print("  LEARNING CURVE (Does more data help?)")
    print("=" * 60)

    sorted_train_ids = sorted(train_ids)
    lc_train_scores  = []
    lc_test_scores   = []
    lc_n_rides       = []

    for n in range(2, len(sorted_train_ids) + 1):
        subset_ids  = sorted_train_ids[:n]
        subset_mask = df['ride_id'].isin(subset_ids)
        X_sub = df.loc[subset_mask, FEATURE_COLS]
        y_sub = df.loc[subset_mask, TARGET_COL]

        lc_clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
        lc_clf.fit(X_sub, y_sub)

        lc_train_scores.append(accuracy_score(y_sub, lc_clf.predict(X_sub)))
        lc_test_scores.append(accuracy_score(y_test, lc_clf.predict(X_test)))
        lc_n_rides.append(n)

    plt.figure(figsize=(8, 5))
    plt.plot(lc_n_rides, [s * 100 for s in lc_train_scores], 'o-', color=plot_style.PRIMARY, linewidth=1.8, label='Training accuracy')
    plt.plot(lc_n_rides, [s * 100 for s in lc_test_scores],  'o-', color=plot_style.ACCENT,   linewidth=1.8, label='Test accuracy')
    plt.xlabel('Number of training rides')
    plt.ylabel('Accuracy (%)')
    plt.legend()
    plt.ylim(40, 105)
    plt.tight_layout()
    lc_path = os.path.join(graphics_dir, '04_learning_curve_fluid.png')
    plt.savefig(lc_path, dpi=150)
    plt.close()
    print(f"  -> Saved Learning Curve: {lc_path}")

    last_5 = lc_test_scores[-5:]
    if max(last_5) - min(last_5) > 0.03:
        print("  ⚠️  Test accuracy still rising — more rides will improve the model.")
    else:
        print("  ✅ Test accuracy has plateaued — focus on features rather than more data.")

    # Export model
    model_path = os.path.join(base_dir, 'digital_twin_model_fluid.pkl')
    joblib.dump(clf, model_path)

    config = {
        'feature_cols':          FEATURE_COLS,
        'target':                TARGET_COL,
        'personal_threshold_l':  0.301,
        'deployment_threshold':  0.50,
        'n_training_rides':      int(len(train_ids)),
        'n_training_rows':       int(len(X_train)),
        'auc':                   round(float(roc_auc), 4),
        'cv_accuracy_mean':      round(float(mean_cv), 4),
        'cv_accuracy_std':       round(float(std_cv),  4),
        'training_date':         pd.Timestamp.now().strftime('%Y-%m-%d'),
    }
    config_path = os.path.join(base_dir, 'model_config_fluid.json')
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(f"\n-> Exported model : {model_path}")
    print(f"-> Exported config: {config_path}")
    print("\n✅ Fluid loss model training complete.")


if __name__ == "__main__":
    main()
