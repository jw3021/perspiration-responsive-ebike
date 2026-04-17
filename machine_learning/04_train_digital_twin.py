import os
import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

try:
    from sklearn.model_selection import train_test_split
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import accuracy_score, classification_report
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
    csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ml_ready_dataset.csv')
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found. Run Step 2 (Feature Engineering) first!")
        return
        
    df = pd.read_csv(csv_path)
    print(f"Loaded dataset with {len(df)} 50ms interval rows.")
    
    # 2. Select the Features to feed the AI (Drop text IDs and Target variables)
    feature_cols = [
        'torque_nm', 'rpm', 
        'torque_rolling_3min', 'rpm_rolling_3min', 'exertion_debt_kj',
        'temp_c', 'humidity_pct', 'speed_kph', 'skin_temp_c'
    ]
    
    # Drop rows if they have NAs in our critical feature columns
    df = df.dropna(subset=feature_cols + ['is_sweating'])
    
    X = df[feature_cols]
    y = df['is_sweating']
    
    print(f"\nTraining on {len(X)} pristine rows across {len(feature_cols)} engineered features...")
    
    # 3. Train/Test Split (80% training data, 20% unseen "future" data for testing)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    
    # 4. INITIALIZE THE MODEL
    # We use a Random Forest because it compiles incredibly small for the Raspberry Pi Edge execution
    # and it handles non-linear human physics natively without scaling requirements.
    clf = RandomForestClassifier(n_estimators=100, max_depth=10, random_state=42, n_jobs=-1)
    
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
    
    # 6. Feature Importance: What actually governs your thermoregulation?
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
    
    plot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '04_feature_importance.png')
    plt.savefig(plot_path)
    print(f"\n-> Saved Feature Importance Graph: {plot_path}")
    
    # 7. Export the Model for the Raspberry Pi
    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'digital_twin_model.pkl')
    joblib.dump(clf, model_path)
    print(f"-> Exported Lightweight Edge Model to: {model_path}")
    
    print("\n✅ Step 4 Complete. You now have a working AI ready for edge deployment!")

if __name__ == "__main__":
    main()
