import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

try:
    from sklearn.model_selection import train_test_split, GroupKFold
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import (accuracy_score, classification_report,
                                 confusion_matrix, ConfusionMatrixDisplay,
                                 roc_curve, auc)
    import joblib
except ImportError:
    print("Error: Required Machine Learning libraries are missing!")
    print("Please run this command in your terminal: pip install scikit-learn joblib")
    sys.exit(1)

def main():
    print("="*60)
    print(" STEP 4: TRAINING THE DIGITAL TWIN (Edge ML Prototype)")
    print("="*60)
    
    # 1. Load the pristine engineering dataset we built in Step 2
    csv_path     = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_ready_dataset.csv')
    graphics_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'graphics')
    os.makedirs(graphics_dir, exist_ok=True)
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found. Run Step 2 (Feature Engineering) first!")
        return
        
    df = pd.read_csv(csv_path)
    print(f"Loaded dataset with {len(df)} 50ms interval rows.")
    
    # 2. Select the Features to feed the AI (Drop text IDs and Target variables)
    feature_cols = [
        'exertion_debt_kj',
        'exertion_intensity_kj_per_min',
        'humidity_pct',
        'temp_c',
        'torque_rolling_3min',
    ]
    
    # Drop rows if they have NAs in our critical feature columns
    df = df.dropna(subset=feature_cols + ['is_sweating'])
    
    X = df[feature_cols]
    y = df['is_sweating']
    
    print(f"\nTraining on {len(X)} pristine rows across {len(feature_cols)} engineered features...")

    # 3. Ride-level Train/Test Split
    # We split on ride IDs (not individual rows) so the model is tested on rides it has
    # never seen at all. A row-level split would leak data because consecutive 50ms readings
    # from the same ride would appear in both train and test sets.
    all_ride_ids = df['ride_id'].unique()
    train_ids, test_ids = train_test_split(all_ride_ids, test_size=0.2, random_state=42)

    print(f"\nRide-level split: {len(train_ids)} training rides / {len(test_ids)} test rides")
    print(f"  Train rides: {sorted(train_ids)}")
    print(f"  Test  rides: {sorted(test_ids)}")

    train_mask = df['ride_id'].isin(train_ids)
    test_mask  = df['ride_id'].isin(test_ids)

    X_train, y_train = df.loc[train_mask, feature_cols], df.loc[train_mask, 'is_sweating']
    X_test,  y_test  = df.loc[test_mask,  feature_cols], df.loc[test_mask,  'is_sweating']

    print(f"  Training rows: {len(X_train)} | Test rows: {len(X_test)}")
    
    # 4. INITIALIZE THE MODEL
    # We use a Random Forest because it compiles incredibly small for the Raspberry Pi Edge execution
    # and it handles non-linear human physics natively without scaling requirements.
    clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1,
                                 class_weight='balanced')
    
    print("\nTraining Random Forest Model... (This is where the AI learns your physiology!)")
    clf.fit(X_train, y_train)
    
    # 5. Evaluate the Model on the 20% unseen test data
    y_pred = clf.predict(X_test)
    acc = accuracy_score(y_test, y_pred)
    
    print("\n" + "="*45)
    print(f"  MODEL ACCURACY ON UNSEEN DATA: {acc * 100:.2f}%")
    print("="*45)
    
    print("\nClassification Report (Precision & Recall):")
    print(classification_report(y_test, y_pred, target_names=["Dry/Comfortable", "Sweat Threshold Reached"]))

    # --- Per-class recall callout (the number that actually matters) ---
    report = classification_report(y_test, y_pred, target_names=["Dry/Comfortable", "Sweat Threshold Reached"], output_dict=True)
    recall_sweat = report["Sweat Threshold Reached"]["recall"]
    recall_dry   = report["Dry/Comfortable"]["recall"]
    print("KEY METRICS (what accuracy hides):")
    print(f"  Recall on SWEATING class  : {recall_sweat*100:.1f}%  <- % of real sweat events caught")
    print(f"  Recall on DRY class       : {recall_dry*100:.1f}%  <- % of dry periods correctly identified")
    if recall_sweat < 0.70:
        print("  ⚠️  Sweating recall below 70% — model is missing most real sweat onset events.")
    else:
        print("  ✅ Sweating recall acceptable.")

    # --- Confusion Matrix (normalised) ---
    cm = confusion_matrix(y_test, y_pred, normalize='true')
    fig, ax = plt.subplots(figsize=(7, 6))
    disp = ConfusionMatrixDisplay(confusion_matrix=cm,
                                  display_labels=["Dry/Comfortable", "Sweat Onset"])
    disp.plot(ax=ax, cmap='Blues', values_format='.2%')
    ax.set_title("Confusion Matrix (normalised)\nEach cell = % of actual class")
    plt.tight_layout()
    cm_path = os.path.join(graphics_dir, '04_confusion_matrix.png')
    plt.savefig(cm_path, dpi=150)
    plt.close()
    print(f"\n-> Saved Confusion Matrix: {cm_path}")

    # --- ROC Curve ---
    y_prob = clf.predict_proba(X_test)[:, 1]
    fpr, tpr, thresholds = roc_curve(y_test, y_prob)
    roc_auc = auc(fpr, tpr)

    plt.figure(figsize=(8, 6))
    plt.plot(fpr, tpr, color='#8E44AD', linewidth=2,
             label=f'Random Forest (AUC = {roc_auc:.3f})')
    plt.plot([0, 1], [0, 1], 'k--', linewidth=1, label='Random guess (AUC = 0.500)')
    plt.xlabel('False Positive Rate (Dry predicted as Sweating)')
    plt.ylabel('True Positive Rate (Sweat events correctly caught)')
    plt.title('ROC Curve — Sweat Onset Detection')
    plt.legend(loc='lower right')
    plt.grid(True, linestyle='--', alpha=0.3)
    plt.tight_layout()
    roc_path = os.path.join(graphics_dir, '04_roc_curve.png')
    plt.savefig(roc_path, dpi=150)
    plt.close()
    print(f"-> Saved ROC Curve (AUC = {roc_auc:.3f}): {roc_path}")
    if roc_auc < 0.75:
        print("  ⚠️  AUC below 0.75 — model is barely distinguishing the two classes.")
    elif roc_auc < 0.85:
        print("  ⚠️  AUC in moderate range — class_weight='balanced' may help; more data likely needed.")
    else:
        print("  ✅ AUC above 0.85 — model has strong discriminative ability.")
    
    # --- Temporal Prediction Plot (one test ride) ---
    # Shows predicted probability vs actual label over real time.
    # This is the most operationally meaningful plot: did the model detect sweat onset
    # at the right moment, or was it late / noisy?
    sample_ride_id = sorted(test_ids)[0]
    ride_mask = df['ride_id'] == sample_ride_id
    X_ride = df.loc[ride_mask, feature_cols]
    y_ride = df.loc[ride_mask, 'is_sweating'].values
    t_ride = df.loc[ride_mask, 'timestamp'] if 'timestamp' in df.columns else pd.RangeIndex(ride_mask.sum())
    proba_ride = clf.predict_proba(X_ride)[:, 1]

    fig, ax1 = plt.subplots(figsize=(14, 5))
    ax1.fill_between(range(len(y_ride)), y_ride.astype(float), alpha=0.15,
                     color='#E74C3C', label='Actual: Sweating (ground truth)')
    ax1.plot(proba_ride, color='#8E44AD', linewidth=1.2,
             label='Predicted sweat probability')
    ax1.axhline(0.5, color='grey', linestyle='--', linewidth=0.8, label='Decision threshold (0.5)')
    ax1.set_ylim(-0.05, 1.15)
    ax1.set_xlabel('Reading index (~1s per row)')
    ax1.set_ylabel('Probability / Label')
    ax1.set_title(f'Temporal Prediction — Ride: {sample_ride_id}\n'
                  f'Red shading = actual sweat onset periods | Purple line = model confidence')
    ax1.legend(loc='upper left')
    ax1.grid(True, linestyle='--', alpha=0.25)
    plt.tight_layout()
    temporal_path = os.path.join(graphics_dir, '04_temporal_prediction.png')
    plt.savefig(temporal_path, dpi=150)
    plt.close()
    print(f"-> Saved Temporal Prediction Plot (ride: {sample_ride_id}): {temporal_path}")

    # --- Lead Time Analysis ---
    # The core claim of a predictive system is that it detects onset *before* the sensor.
    # "Sustained trigger" = first point where predicted probability stays above 0.5
    # for 600 consecutive readings (30 seconds), avoiding false triggers from brief spikes.
    print("\n" + "="*60)
    print("  LEAD TIME ANALYSIS")
    print("  How far ahead does the model predict sweat onset?")
    print("="*60)

    SUSTAINED_READINGS = 30    # 30 seconds at ~1s per row
    PROB_THRESHOLD     = 0.5

    lead_time_results = []
    for rid in sorted(test_ids):
        ride_mask  = df['ride_id'] == rid
        X_ride     = df.loc[ride_mask, feature_cols]
        y_ride     = df.loc[ride_mask, 'is_sweating'].values
        proba_ride = clf.predict_proba(X_ride)[:, 1]

        sweating_idxs = np.where(y_ride == 1)[0]
        if len(sweating_idxs) == 0:
            print(f"  {rid}: No sweat onset recorded — skipped")
            continue
        sensor_onset_idx = sweating_idxs[0]

        # Walk forward to find first sustained run above threshold
        model_trigger_idx = None
        run_length        = 0
        for i, p in enumerate(proba_ride):
            if p > PROB_THRESHOLD:
                run_length += 1
                if run_length >= SUSTAINED_READINGS:
                    model_trigger_idx = i - SUSTAINED_READINGS + 1
                    break
            else:
                run_length = 0

        if model_trigger_idx is None:
            print(f"  {rid}: Model never sustained a trigger — skipped")
            continue

        sensor_onset_min  = sensor_onset_idx  / 60   # ~1s per row
        model_trigger_min = model_trigger_idx / 60
        lead_time_min     = sensor_onset_min - model_trigger_min

        lead_time_results.append({
            'ride_id':           rid,
            'sensor_onset_min':  round(sensor_onset_min,  1),
            'model_trigger_min': round(model_trigger_min, 1),
            'lead_time_min':     round(lead_time_min,     1),
        })

        symbol    = "✅" if lead_time_min > 0 else "⚠️ "
        direction = "ahead of" if lead_time_min > 0 else "behind"
        print(f"  {rid}:")
        print(f"    Sensor onset : {sensor_onset_min:.1f} min into ride")
        print(f"    Model trigger: {model_trigger_min:.1f} min into ride")
        print(f"    Lead time    : {abs(lead_time_min):.1f} min {symbol} (model {direction} sensor)")

    if lead_time_results:
        lt_df     = pd.DataFrame(lead_time_results)
        mean_lead = lt_df['lead_time_min'].mean()
        print(f"\n  Average lead time across {len(lt_df)} test rides: {mean_lead:.1f} minutes")
        if mean_lead > 0:
            print(f"  ✅ Model predicts onset {mean_lead:.1f} min ahead of sensor on average")
        else:
            print(f"  ⚠️  Model lags sensor by {abs(mean_lead):.1f} min on average")

        _, ax = plt.subplots(figsize=(10, 5))
        colors = ['#2ECC71' if lt > 0 else '#E74C3C' for lt in lt_df['lead_time_min']]
        ax.bar(range(len(lt_df)), lt_df['lead_time_min'],
               color=colors, edgecolor='black', alpha=0.85)
        ax.axhline(0, color='black', linewidth=1)
        ax.axhline(mean_lead, color='#8E44AD', linewidth=2, linestyle='--',
                   label=f'Mean: {mean_lead:.1f} min')
        ax.set_xticks(range(len(lt_df)))
        ax.set_xticklabels([r['ride_id'].replace('RIDE_', '') for r in lead_time_results],
                           rotation=30, ha='right', fontsize=9)
        ax.set_ylabel('Lead Time (minutes)\n+ = model early   − = model late')
        ax.set_title('Model Lead Time vs Sweat Sensor Onset\n'
                     'Green = predicted early | Red = predicted late')
        ax.legend()
        ax.grid(axis='y', linestyle='--', alpha=0.3)
        plt.tight_layout()
        lead_path = os.path.join(graphics_dir, '04_lead_time.png')
        plt.savefig(lead_path, dpi=150)
        plt.close()
        print(f"  -> Saved Lead Time Chart: {lead_path}")

    # 6. Per-ride summary: how many rides crossed the sweat threshold?
    print("\n" + "="*60)
    print("  PER-RIDE SWEAT THRESHOLD SUMMARY (all rides in dataset)")
    print("="*60)
    ride_summary = (
        df.groupby('ride_id')['is_sweating']
        .agg(total_rows='count', sweating_rows='sum')
        .assign(pct_sweating=lambda x: (x['sweating_rows'] / x['total_rows'] * 100).round(1),
                crossed_threshold=lambda x: x['sweating_rows'] > 0)
    )
    ride_summary = ride_summary.sort_values('ride_id')
    for ride_id, row in ride_summary.iterrows():
        flag = "YES" if row['crossed_threshold'] else " no"
        print(f"  [{flag}]  {ride_id}  —  {row['pct_sweating']:5.1f}% of readings above threshold")

    n_crossed = ride_summary['crossed_threshold'].sum()
    n_total   = len(ride_summary)
    print(f"\n  {n_crossed} of {n_total} rides crossed the sweat threshold (0.3 L/hr)")
    print("="*60)

    # 7. Feature Importance: What actually governs your thermoregulation?

    importances = clf.feature_importances_
    sorted_indices = np.argsort(importances)[::-1]
    
    print("\nFEATURE IMPORTANCE RANKING:")
    for i in sorted_indices:
        print(f"{feature_cols[i]:>25}: {importances[i]*100:.1f}%")
        
    # Plot Feature Importances
    plt.figure(figsize=(12, 6))
    plt.title("Digital Twin Feature Importance (% influence on Sweat Prediction)")
    plt.bar(range(X.shape[1]), importances[sorted_indices], align='center', color='#8E44AD')
    plt.xticks(range(X.shape[1]), [feature_cols[i] for i in sorted_indices], rotation=30, ha='right')
    plt.ylabel("Importance (%)")
    plt.grid(axis='y', linestyle='--', alpha=0.3)
    plt.tight_layout()
    
    plot_path = os.path.join(graphics_dir, '04_feature_importance.png')
    plt.savefig(plot_path)
    print(f"\n-> Saved Feature Importance Graph: {plot_path}")
    
    # 8. Cross-Validation (ride-level)
    # GroupKFold ensures rides are never split across train/test within a fold —
    # the same principle as our ride-level split above, applied 5 times over.
    print("\n" + "="*60)
    print("  5-FOLD CROSS-VALIDATION (Ride-Level)")
    print("="*60)

    groups = df['ride_id']
    X_all  = df[feature_cols]
    y_all  = df['is_sweating']

    n_splits = min(5, len(all_ride_ids))
    gkf = GroupKFold(n_splits=n_splits)

    fold_scores = []
    for fold, (tr_idx, te_idx) in enumerate(gkf.split(X_all, y_all, groups), start=1):
        X_tr, X_te = X_all.iloc[tr_idx], X_all.iloc[te_idx]
        y_tr, y_te = y_all.iloc[tr_idx], y_all.iloc[te_idx]
        fold_clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
        fold_clf.fit(X_tr, y_tr)
        score = accuracy_score(y_te, fold_clf.predict(X_te))
        fold_scores.append(score)
        test_rides = df.iloc[te_idx]['ride_id'].unique()
        print(f"  Fold {fold}: {score*100:.2f}%  (test rides: {len(test_rides)})")

    mean_cv  = np.mean(fold_scores)
    std_cv   = np.std(fold_scores)
    print(f"\n  CV Accuracy: {mean_cv*100:.2f}% ± {std_cv*100:.2f}%")
    if std_cv > 0.08:
        print("  ⚠️  High variance across folds — model is sensitive to which rides it trains on.")
    else:
        print("  ✅ Low variance across folds — model is learning a consistent pattern.")

    # 9. Learning Curve (ride-level)
    # Incrementally add rides to the training set and measure test accuracy.
    # A still-rising curve means more data will help; a plateau means better features are needed.
    print("\n" + "="*60)
    print("  LEARNING CURVE (Does more data help?)")
    print("="*60)

    sorted_train_ids = sorted(train_ids)
    lc_train_scores = []
    lc_test_scores  = []
    lc_n_rides      = []

    for n in range(2, len(sorted_train_ids) + 1):
        subset_ids   = sorted_train_ids[:n]
        subset_mask  = df['ride_id'].isin(subset_ids)
        X_sub = df.loc[subset_mask, feature_cols]
        y_sub = df.loc[subset_mask, 'is_sweating']

        lc_clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
        lc_clf.fit(X_sub, y_sub)

        lc_train_scores.append(accuracy_score(y_sub, lc_clf.predict(X_sub)))
        lc_test_scores.append(accuracy_score(y_test, lc_clf.predict(X_test)))
        lc_n_rides.append(n)

    # Plot learning curve
    plt.figure(figsize=(10, 6))
    plt.plot(lc_n_rides, [s * 100 for s in lc_train_scores], 'o-', color='#2ECC71', linewidth=2, label='Training Accuracy')
    plt.plot(lc_n_rides, [s * 100 for s in lc_test_scores],  'o-', color='#E74C3C', linewidth=2, label='Test Accuracy')
    plt.xlabel('Number of Training Rides')
    plt.ylabel('Accuracy (%)')
    plt.title('Learning Curve: Model Performance vs Number of Training Rides')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.3)
    plt.ylim(40, 105)
    plt.tight_layout()

    lc_path = os.path.join(graphics_dir, '04_learning_curve.png')
    plt.savefig(lc_path)
    plt.close()
    print(f"  -> Saved Learning Curve: {lc_path}")

    # Print verdict on whether more data is needed
    last_5_test = lc_test_scores[-5:]
    improvement = max(last_5_test) - min(last_5_test)
    if improvement > 0.03:
        print("  ⚠️  Test accuracy still rising — collecting more rides will improve the model.")
    else:
        print("  ✅ Test accuracy has plateaued — more data is unlikely to help, focus on features.")

    # 10. Export the Model for the Raspberry Pi
    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'digital_twin_model.pkl')
    joblib.dump(clf, model_path)
    print(f"-> Exported Lightweight Edge Model to: {model_path}")
    
    print("\n✅ Step 4 Complete. You now have a working AI ready for edge deployment!")

if __name__ == "__main__":
    main()
