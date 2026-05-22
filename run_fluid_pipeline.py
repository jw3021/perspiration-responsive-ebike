import subprocess
import sys

scripts = [
    "machine_learning/fluid_loss_model/02_feature_engineering_fluid.py",
    "machine_learning/fluid_loss_model/04_train_digital_twin_fluid.py",
    "machine_learning/fluid_loss_model/06_threshold_sweep_fluid.py",
]

for s in scripts:
    print(f"\n{'='*55}\n  Running: {s}\n{'='*55}")
    result = subprocess.run([sys.executable, s])
    if result.returncode != 0:
        print(f"\n❌ Failed at: {s} — pipeline stopped.")
        sys.exit(1)

print("\n✅ Fluid pipeline complete.")
