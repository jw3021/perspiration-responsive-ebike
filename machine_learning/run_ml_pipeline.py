import subprocess
import sys
import os

base = os.path.dirname(os.path.abspath(__file__))

scripts = [
    os.path.join(base, "sweat_onset_model/02_feature_engineering.py"),
    os.path.join(base, "sweat_onset_model/04_train_sweat_onset_model.py"),
    os.path.join(base, "sweat_onset_model/06_threshold_sweep.py"),
]

for s in scripts:
    print(f"\n{'='*55}\n  Running: {os.path.basename(s)}\n{'='*55}")
    result = subprocess.run([sys.executable, s])
    if result.returncode != 0:
        print(f"\n❌ Failed at: {os.path.basename(s)} — pipeline stopped.")
        sys.exit(1)

print("\n✅ ML pipeline complete.")
